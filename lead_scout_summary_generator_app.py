import streamlit as st
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import pytz
import plotly.express as px

def get_sunset_time(date_str, lat=39.8436, lon=-86.1190):
    url = f"https://api.sunrise-sunset.org/json?lat={lat}&lng={lon}&date={date_str}&formatted=0"
    response = requests.get(url)
    data = response.json()
    utc_time = datetime.fromisoformat(data["results"]["sunset"])
    eastern = pytz.timezone("America/Indiana/Indianapolis")
    return utc_time.astimezone(eastern)

st.title("📊 Lead Scout Summary Generator")

# Upload or load CSV file
csv_file = st.file_uploader("Upload your scouting report here", type=["csv"])

if csv_file is not None:
    df = pd.read_csv(csv_file)
    st.success("✅ File loaded successfully!")

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

    # Output formatting and export
    output = grouped.rename(columns={
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
    output_indexed = output.set_index("Lead Status Updated By")

    st.write("Your Lead Scout Summary:")
    st.dataframe(output_indexed)  # Interactive table view

    ## Dashboards

    # Knocks
    knocks = output.sort_values(by="Knocks", ascending=False)
    fig = px.bar(knocks, x="Lead Status Updated By", y="Knocks", title="Knocks by Rep")
    st.plotly_chart(fig, use_container_width=True)

    # Time in Field
    time_in_field = grouped.sort_values(by="Time in Field (Hours)", ascending=False)
    fig_2 = px.bar(time_in_field, x="Lead Status Updated By", y="Time in Field (Hours)", title="Time in Field by Rep")
    st.plotly_chart(fig_2, use_container_width=True)

    # Adj Time in Field
    adj_time_in_field = grouped.sort_values(by="Adj Time in Field (Hours)", ascending=False)
    fig_3 = px.bar(adj_time_in_field, x="Lead Status Updated By", y="Adj Time in Field (Hours)", title="Adj Time in Field by Rep")
    st.plotly_chart(fig_3, use_container_width=True)

    # Before Sunset
    before_sunset = grouped.sort_values(by="Before Sunset (Hours)", ascending=False)
    fig_4 = px.bar(before_sunset, x="Lead Status Updated By", y="Before Sunset (Hours)", title="Knocks Before Sunset by Rep")
    st.plotly_chart(fig_4, use_container_width=True)

    # Convos
    convos = output.sort_values(by="Convos", ascending=False)
    fig_5 = px.bar(convos, x="Lead Status Updated By", y="Convos", title="Convos by Rep")
    st.plotly_chart(fig_5, use_container_width=True)

    # Convo %
    convo_perc = output.sort_values(by="Convo %", ascending=False)
    fig_6 = px.bar(convo_perc, x="Lead Status Updated By", y="Convo %", title="Convo % by Rep")
    st.plotly_chart(fig_6, use_container_width=True)

    # Inspections
    inspections = output.sort_values(by="Inspections", ascending=False)
    fig_7 = px.bar(inspections, x="Lead Status Updated By", y="Inspections", title="Inspections by Rep")
    st.plotly_chart(fig_7, use_container_width=True)

    # Claims Filed
    claims = output.sort_values(by="Claims Filed", ascending=False)
    claims_y_max = claims["Claims Filed"].max()
    claims_y_range = [0, claims_y_max * 1.1 if claims_y_max > 0 else 5]
    fig_8 = px.bar(claims, x="Lead Status Updated By", y="Claims Filed", title="Claims Filed by Rep", range_y=claims_y_range)
    st.plotly_chart(fig_8, use_container_width=True)

    # Closing %
    closing_perc = output.sort_values(by="Closing %", ascending=False)
    closing_y_max = closing_perc["Closing %"].max()
    closing_y_range = [0, claims_y_max * 1.1 if claims_y_max > 0 else 10]
    fig_9 = px.bar(closing_perc, x="Lead Status Updated By", y="Closing %", title="Closing % by Rep", range_y=closing_y_range)
    st.plotly_chart(fig_9, use_container_width=True)

    # Inspections/Door
    inspections_per_door = output.sort_values(by="Inspections/Door", ascending=False)
    fig_10 = px.bar(inspections_per_door, x="Lead Status Updated By", y="Inspections/Door", title="Inspections/Door by Rep")
    st.plotly_chart(fig_10, use_container_width=True)

    # Inspections/Convo
    inspections_per_convo = output.sort_values(by="Inspections/Convo", ascending=False)
    fig_11 = px.bar(inspections_per_convo, x="Lead Status Updated By", y="Inspections/Convo", title="Inspections/Convo by Rep")
    st.plotly_chart(fig_11, use_container_width=True)
else:
    st.info("👆 Upload a CSV file to get started.")