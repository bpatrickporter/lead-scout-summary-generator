import streamlit as st
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import pytz
import plotly.express as px
from geopy.geocoders import ArcGIS
from geopy.extra.rate_limiter import RateLimiter
from collections import defaultdict

gap_notes = defaultdict(list)

def get_sunset_time(date_str, lat=39.8436, lon=-86.1190):
    url = f"https://api.sunrise-sunset.org/json?lat={lat}&lng={lon}&date={date_str}&formatted=0"
    response = requests.get(url)
    data = response.json()
    utc_time = datetime.fromisoformat(data["results"]["sunset"])
    eastern = pytz.timezone("America/Indiana/Indianapolis")
    return utc_time.astimezone(eastern)

def combine_notes(row):
    key = (row["Lead Status Updated By"], row["Date"])
    notes = gap_notes.get(key, [])
    return "\n".join(notes) if notes else ""

def classify_gap_and_note(row):
    gap = row["Time Since Last Pin (s)"]
    if pd.isnull(gap):
        return 0

    first_addr = row.get("Previous Address", "Unknown")
    second_addr = row.get("Address1", "Unknown")
    rep = row["Lead Status Updated By"]
    date = row["Lead Status Updated At"].date()

    if gap > 7200:
        reason = "Rule 2: >120 min"
    elif gap > 1800 and row["Is Inspection"] == 0:
        reason = "Rule 1: >30 min, not inspection"
    else:
        return 0

    hrs = int(gap // 3600)
    mins = int((gap % 3600) // 60)
    time_str = f"{hrs}h {mins}m" if hrs else f"{mins}m"
    note = f"Removed {time_str} gap between '{first_addr}' and '{second_addr}' ({reason})"
    gap_notes[(rep, date)].append(note)

    return gap

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

    # Time deltas
    df["Previous Time"] = df.groupby("Lead Status Updated By")["Lead Status Updated At"].shift(1)
    df["Time Since Last Pin"] = df["Lead Status Updated At"] - df["Previous Time"]
    # Create helper column: time gaps in seconds
    df["Time Since Last Pin (s)"] = df["Time Since Last Pin"].dt.total_seconds()

    df["Is Inspection"] = df["Lead Status"].str.contains("Inspected", case=False, na=False).astype(int)
    df["Previous Is Inspection"] = df.groupby("Lead Status Updated By")["Is Inspection"].shift(1)
    df["Inspection Gap (s)"] = df.apply(
        lambda row: row["Time Since Last Pin (s)"]
        if pd.notnull(row["Time Since Last Pin (s)"]) and row["Previous Is Inspection"] == 1
        else 0,
        axis=1
    )
    inspection_gaps = (
        df.groupby(["Lead Status Updated By", "Date"])["Inspection Gap (s)"]
        .sum()
        .reset_index()
        .rename(columns={"Inspection Gap (s)": "Inspection Time (s)"})
    )
    df["<30s Pin"] = df["Time Since Last Pin"].dt.total_seconds().lt(30).fillna(False).astype(int)
    df[">5m Non-Inspection"] = (
        df["Time Since Last Pin"].dt.total_seconds().gt(300) & (df["Is Inspection"] == 0)
    ).fillna(False).astype(int)

    df["Previous Address"] = df.groupby("Lead Status Updated By")["Address1"].shift(1)
    df["Long Gaps (s)"] = df.apply(classify_gap_and_note, axis=1)
    long_gaps = df.groupby(["Lead Status Updated By", "Date"])["Long Gaps (s)"].sum().reset_index()
    long_gaps.rename(columns={"Long Gaps (s)": "Total Long Gaps (s)"}, inplace=True)

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

    grouped = pd.merge(grouped, inspection_gaps, on=["Lead Status Updated By", "Date"], how="left")

    # Format to "xh ym"
    grouped["Inspection Time"] = grouped["Inspection Time (s)"].apply(
        lambda s: f"{int(s // 3600)}h {int((s % 3600) // 60)}m" if pd.notnull(s) and s > 0 else "0h 0m"
    )

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
        "True DPH", "Position", "Note"
    ]:
        grouped[col] = "TBD"

    # Merge with grouped data
    grouped = pd.merge(grouped, long_gaps, on=["Lead Status Updated By", "Date"], how="left")
    grouped["Note"] = grouped.apply(combine_notes, axis=1)

    # Calculate Adjusted Time in Field (raw timedelta)
    grouped["Adj Time in Field (Timedelta)"] = ((grouped["Finish"] - grouped["Start"]) - pd.to_timedelta(grouped["Total Long Gaps (s)"], unit="s"))
    grouped["Adj Time in Field (Hours)"] = grouped["Adj Time in Field (Timedelta)"].dt.total_seconds() / 3600
    grouped["Adj Time in Field"] = grouped["Adj Time in Field (Timedelta)"].apply(
        lambda td: f"{int(td.total_seconds() // 3600)}h {int((td.total_seconds() % 3600) // 60)}m"
        if pd.notnull(td) and td.total_seconds() > 0 else "0h 0m"
    )
    grouped["Field Time Less Inspections (Hours)"] = grouped["Adj Time in Field (Hours)"] - (grouped["Inspection Time (s)"] / 3600)
    grouped["Field Time Less Inspections"] = grouped["Field Time Less Inspections (Hours)"].apply(
        lambda hrs: f"{int(hrs)}h {int(round((hrs % 1) * 60))}m" if pd.notnull(hrs) and hrs > 0 else "0h 0m"
    )

    grouped["True AVG Time/Door"] = (
        (grouped["Field Time Less Inspections (Hours)"] * 60) / grouped["Total_Pins"]
    ).replace([np.inf, -np.inf], np.nan)

    grouped["True AVG Time/Door"] = grouped["True AVG Time/Door"].apply(
        lambda mins: f"{int(mins)}m {int(round((mins % 1) * 60))}s"
        if pd.notnull(mins) and mins > 0 else "0m 0s"
    )

    grouped["True DPH"] = (
        grouped["Total_Pins"] / grouped["Field Time Less Inspections (Hours)"]
    ).replace([np.inf, -np.inf], np.nan).round(2)

    grouped["True DPH (Formatted)"] = grouped["True DPH"].apply(
        lambda dph: f"{dph} DPH" if pd.notnull(dph) else "N/A"
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

@st.cache_data(show_spinner=False)
def geocode_single_address(address):
    geolocator = ArcGIS(user_agent="lead-scout-app", timeout=10)
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1)

    try:
        location = geocode(address)
        if location:
            return location.latitude, location.longitude
    except:
        pass
    return None, None

def compute_map_df(df, selected_rep):
    if "Full Address" not in df.columns:
        st.warning("⚠️ 'Full Address' column not found. Cannot map pins.")
        return pd.DataFrame()

    rep_df = df[df["Lead Status Updated By"] == selected_rep]
    if rep_df.empty:
        st.warning("⚠️ No addresses found for selected rep.")
        return pd.DataFrame()

    pin_count = len(rep_df)
    info_placeholder = st.empty()
    info_placeholder.info(
        f"📍 Geocoding {pin_count} pins for {selected_rep}... ⏳ This may take ~1 second per pin."
    )

    latitudes = []
    longitudes = []
    progress = st.progress(0)

    for i, addr in enumerate(rep_df["Full Address"]):
        lat, lng = geocode_single_address(addr)  # ✅ cache hit if already called
        latitudes.append(lat)
        longitudes.append(lng)
        progress.progress((i + 1) / pin_count)

    progress.empty()
    info_placeholder.empty()

    rep_df["Latitude"] = latitudes
    rep_df["Longitude"] = longitudes

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