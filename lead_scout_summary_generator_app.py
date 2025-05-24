import streamlit as st
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import pytz
import plotly.express as px
from geopy.geocoders import ArcGIS
from geopy.extra.rate_limiter import RateLimiter

def get_sunset_time(date_str, lat=39.8436, lon=-86.1190):
    url = f"https://api.sunrise-sunset.org/json?lat={lat}&lng={lon}&date={date_str}&formatted=0"
    response = requests.get(url)
    data = response.json()
    utc_time = datetime.fromisoformat(data["results"]["sunset"])
    eastern = pytz.timezone("America/Indiana/Indianapolis")
    return utc_time.astimezone(eastern)

def process_data(df):
    # Ensure correct types and clean values
    df["Lead Status Updated At"] = pd.to_datetime(df["Lead Status Updated At"], errors="coerce")
    df = df[df["Lead Status Updated At"].notnull()].copy()
    df["Tags"] = df["Tags"].fillna("").astype(str).str.strip().str.lower()
    df["Lead Status"] = df["Lead Status"].astype(str).str.strip()
    df["Lead Status Lower"] = df["Lead Status"].str.lower()
    df["Lead Status Updated By"] = df["Lead Status Updated By"].astype(str)
    df["Date"] = df["Lead Status Updated At"].dt.date
    df = df.sort_values(by=["Lead Status Updated By", "Lead Status Updated At"]).reset_index(drop=True)

    # Time deltas
    df["Previous Time"] = df.groupby("Lead Status Updated By")["Lead Status Updated At"].shift(1)
    df["Time Since Last Pin"] = df["Lead Status Updated At"] - df["Previous Time"]
    # Create helper column: time gaps in seconds
    df["Time Since Last Pin (s)"] = df["Time Since Last Pin"].dt.total_seconds()
    # Filter to only gaps > 20 minutes (1200 seconds)
    df["Long Gaps"] = df["Time Since Last Pin (s)"].where(df["Time Since Last Pin (s)"] > 1800, 0)
    # Sum long gaps per rep + date
    long_gaps = df.groupby(["Lead Status Updated By", "Date"])["Long Gaps"].sum().reset_index()
    long_gaps.rename(columns={"Long Gaps": "Total Long Gaps (s)"}, inplace=True)

    # Classification
    df["Is Conversation"] = df.apply(lambda row: int(
        row["Lead Status Lower"] in [
            "interested - follow up", "inspection scheduled", "not interested - yet"
        ] or (
            row["Lead Status Lower"] == "do not knock" and
            "yard sign" not in row["Tags"] and
            "custom no soliciting sign" not in row["Tags"]
        )
    ), axis=1)

    df["Is Inspection"] = df["Lead Status"].str.contains("Inspected", case=False, na=False).astype(int)
    df["<30s Pin"] = df["Time Since Last Pin"].dt.total_seconds().lt(30).fillna(False).astype(int)
    df[">5m Non-Inspection"] = (
        df["Time Since Last Pin"].dt.total_seconds().gt(300) & (df["Is Inspection"] == 0)
    ).fillna(False).astype(int)

    df["Is Inspection Scheduled"] = (df["Lead Status Lower"] == "inspection scheduled").astype(int)
    df["Is Inspected - No Damage"] = (df["Lead Status"] == "Inspected - No Damage").astype(int)
    df["Is Inspected - Damage"] = (df["Lead Status"] == "Inspected - Damage").astype(int)
    df["Is Claim Filed"] = (df["Lead Status"] == "Claim Filed").astype(int)
    
    # Group and aggregate
    grouped = df.groupby(["Lead Status Updated By", "Date"]).agg(
        Start=("Lead Status Updated At", "min"),
        Finish=("Lead Status Updated At", "max"),
        Total_Pins=("Lead Status Updated At", "count"),
        Conversations=("Is Conversation", "sum"),
        Inspections=("Is Inspection", "sum"),
        Pins_Lt_30s=("<30s Pin", "sum"),
        Pins_Gt_5m_NonInsp=(">5m Non-Inspection", "sum"),
        Insp_Scheduled=("Is Inspection Scheduled", "sum"),
        Insp_No_Damage=("Is Inspected - No Damage", "sum"),
        Insp_Damage=("Is Inspected - Damage", "sum"),
        Claims_Filed=("Is Claim Filed", "sum")
    ).reset_index()

    # Derived metrics
    grouped["Time in Field (Hours)"] = (grouped["Finish"] - grouped["Start"]).dt.total_seconds() / 3600
    grouped["Time in Field"] = (grouped["Finish"] - grouped["Start"])
    grouped["Time in Field"] = grouped["Time in Field"].apply(
        lambda td: f"{int(td.total_seconds() // 3600)}h {int((td.total_seconds() % 3600) // 60)}m"
        if pd.notnull(td) else "0h 0m"
    )

    grouped["Convo %"] = (grouped["Conversations"] / grouped["Total_Pins"]).round(2)
    grouped["Inspections/Door"] = (grouped["Inspections"] / grouped["Total_Pins"]).round(2)
    grouped["Inspections/Convo"] = (
        grouped["Inspections"] / grouped["Conversations"]
    ).replace([np.inf, -np.inf], np.nan).round(2)
    grouped["DPH"] = (
        grouped["Total_Pins"] / grouped["Time in Field (Hours)"]
        ).replace([np.inf, -np.inf], np.nan).round(2)
    grouped["Closing %"] = (
        grouped["Claims_Filed"] / grouped["Insp_Damage"]
    ).replace([np.inf, -np.inf], np.nan).round(2)

    # Sunset time and "Before Sunset"
    grouped["Sunset Time"] = grouped["Date"].apply(lambda d: get_sunset_time(d.strftime('%Y-%m-%d')))
    grouped["Finish"] = grouped["Finish"].dt.tz_localize(None)
    grouped["Sunset Time"] = grouped["Sunset Time"].dt.tz_localize(None)
    grouped[["Before Sunset", "Before Sunset (Hours)"]] = grouped.apply(
      lambda row: (
        [
            f"{int(diff.total_seconds() // 3600)}h {int((diff.total_seconds() % 3600) // 60)}m",
            round(diff.total_seconds() / 3600, 2)
        ] if pd.notnull(row["Sunset Time"]) and pd.notnull(row["Finish"]) and (diff := row["Sunset Time"] - row["Finish"]) > timedelta(0)
        else ["0h 0m", 0.0]
      ),
      axis=1,
      result_type="expand"
    )

    # Placeholder columns
    for col in [
        "Adj Time in Field", "Inspection Time", "Field Time Less Inspections",
        "True AVG Time/Door", "True DPH", "Position", "Note"
    ]:
        grouped[col] = "TBD"

    # Merge with grouped data
    grouped = pd.merge(grouped, long_gaps, on=["Lead Status Updated By", "Date"], how="left")
    # Calculate Adjusted Time in Field (raw timedelta)
    grouped["Adj Time in Field (Hours)"] = (grouped["Finish"] - grouped["Start"]) - pd.to_timedelta(grouped["Total Long Gaps (s)"], unit="s")
    # Format as hh:mm string
    grouped["Adj Time in Field"] = grouped["Adj Time in Field (Hours)"].apply(
        lambda td: f"{int(td.total_seconds() // 3600)}h {int((td.total_seconds() % 3600) // 60)}m"
        if pd.notnull(td) and td > timedelta(0) else "0h 0m"
    )
    
    return grouped
    
def prep_for_output(df):
    # Output formatting and export
    output = df.rename(columns={
        "Total_Pins": "Knocks",
        "Conversations": "Convos",
        "Pins_Lt_30s": "< 30s",
        "Pins_Gt_5m_NonInsp": "> 5m No Inspection",
        "Insp_Scheduled": "Inpsections Scheduled",
        "Insp_Damage": "Inspected - Damaged",
        "Insp_No_Damage": "Inspected - No Damage",
        "Claims_Filed": "Claims Filed"
    })[[
        "Lead Status Updated By", "Date", "Start", "Finish", "Time in Field",
        "Adj Time in Field", "Sunset Time", "Before Sunset", 
        "Knocks", "Convos", "Convo %", "Inspections", "Inspected - No Damage", 
        "Inspected - Damaged", "Claims Filed", "Closing %", "Inspections/Door", 
        "Inspections/Convo", "Inspection Time", "DPH", "Field Time Less Inspections", 
        "True AVG Time/Door", "True DPH", "< 30s", "> 5m No Inspection", 
        "Position", "Note"
    ]]
    return output

def generate_dashboards(df):
    chart_specs = [
        ("Knocks", "Knocks"),
        ("Convos", "Convos"),
        ("Convo %", "Convo %"),
        ("Inspections", "Inspections"),
        ("Claims Filed", "Claims Filed"),
        ("Closing %", "Closing %"),
        ("Inspections/Door", "Inspections/Door"),
        ("Inspections/Convo", "Inspections/Convo"),
    ]

    # Pair charts 3 at a time
    for i in range(0, len(chart_specs), 3):
        col1, col2, col3 = st.columns(3)

        for j, col in enumerate((col1, col2, col3)):
            if i + j < len(chart_specs):
                metric, title = chart_specs[i + j]
                data = df.sort_values(by=metric, ascending=False)
                fig = px.bar(data, x="Lead Status Updated By", y=metric, title=title, height=300)
                col.plotly_chart(fig, use_container_width=True)

def generate_map(df):
    rep_list = sorted(df["Lead Status Updated By"].dropna().unique().tolist())
    rep_options = ["-- Select a Rep --"] + rep_list
    selected_rep = st.selectbox("Select a rep to view map:", rep_options)

    if selected_rep == "-- Select a Rep --":
        st.info("👆 Please select a rep to view their pins on the map. ⏳ Note: This may take ~1 second per pin as addresses are geocoded in real time.")
    else:
        map_df = compute_map_df(df, selected_rep)
        if not map_df.empty:
            plot_knock_map(map_df)
        else:
            st.warning(f"⚠️ No mappable addresses found for {selected_rep}.")

@st.cache_data(show_spinner=True)
def geocode_addresses(ep_name: str, addresses: pd.Series):
    geolocator = ArcGIS(user_agent="lead-scout-app", timeout=10)
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1)

    def safe_geocode(addr):
        try:
            location = geocode(addr)
            if location:
                return pd.Series([location.latitude, location.longitude])
        except:
            pass
        return pd.Series([None, None])

    # Apply to full Series
    coords = addresses.apply(safe_geocode)
    coords.columns = ["Latitude", "Longitude"]
    return coords

def compute_map_df(df, selected_rep):
    if "Full Address" not in df.columns:
        st.warning("⚠️ 'Full Address' column not found. Cannot map pins.")
        return pd.DataFrame()

    rep_df = df[df["Lead Status Updated By"] == selected_rep]
    if rep_df.empty:
        st.warning("⚠️ No addresses found for selected rep.")
        return pd.DataFrame()

    info_placeholder = st.empty()
    info_placeholder.info(f"📍 Geocoding addresses for {selected_rep}... ⏳ This may take ~1 second per pin.")

    coords = geocode_addresses(selected_rep, rep_df["Full Address"])
    rep_df = rep_df.join(coords)

    info_placeholder.empty()
    return rep_df[rep_df["Latitude"].notnull() & rep_df["Longitude"].notnull()]

def plot_knock_map(df):
    if "Latitude" in df.columns and "Longitude" in df.columns:
        st.subheader("🗺️ Knock Map by Rep")
        map_fig = px.scatter_mapbox(
            df,
            lat="Latitude",
            lon="Longitude",
            color="Lead Status Updated By",
            hover_name="Lead Status Updated By",
            hover_data=["Lead Status", "Lead Status Updated At"],
            zoom=11,
            height=600
        )
        map_fig.update_layout(mapbox_style="open-street-map")
        map_fig.update_traces(marker=dict(size=8))
        st.plotly_chart(map_fig, use_container_width=True)
    else:
        st.warning("📍 Latitude and Longitude not found in uploaded file.")

st.set_page_config(layout="wide")

st.title("📊 Lead Scout Summary Generator")

# Upload or load CSV file
csv_file = st.file_uploader("Upload your scouting report here", type=["csv"])

if csv_file is not None:
    df = pd.read_csv(csv_file)
    st.success("✅ File loaded successfully!")

    processed_df = process_data(df)
    output_df = prep_for_output(processed_df)
    output_indexed = output_df.set_index("Lead Status Updated By")

    st.write("Your Lead Scout Summary:")
    st.dataframe(output_indexed)  # Interactive table view

    generate_dashboards(output_df)

    generate_map(df)

else:
    st.info("👆 Upload a CSV file to get started.")