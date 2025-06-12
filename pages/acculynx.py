import streamlit as st
import pandas as pd
import numpy as np
import requests
import locale
from datetime import datetime, timedelta
import pytz
import plotly.express as px
from geopy.geocoders import ArcGIS
from geopy.extra.rate_limiter import RateLimiter
from collections import defaultdict

NEEDED_COLUMNS = [
        'Lead Date', 'Prospect Date', 'Approved Date', 'Current Status',
        'Current Milestone', 'Current Milestone Date', 'Job Value'
    ]

def read_csv(csv_file):
    df = pd.read_csv(csv_file, usecols=NEEDED_COLUMNS)
    return df

def process_data(df):
    df = covert_dates_to_datetime(df)
    df = add_start_of_week_columns(df)
    result = get_unique_weeks(df)
    result = add_job_counts(result, df)
    result['Week'] = pd.to_datetime(result['Week'])
    result = add_weekly_job_values(result, df)
    result = format_currency(result)
    result['Week'] = result['Week'].dt.date
    result.set_index('Week', inplace=True)
    return result

def covert_dates_to_datetime(df):
    df['Lead Date'] = pd.to_datetime(df['Lead Date'], format="%m/%d/%y", errors='coerce')
    df['Prospect Date'] = pd.to_datetime(df['Prospect Date'], format="%m/%d/%y", errors='coerce')
    df['Approved Date'] = pd.to_datetime(df['Approved Date'], format="%m/%d/%y", errors='coerce')
    df['Current Milestone Date'] = pd.to_datetime(df['Current Milestone Date'], format="%m/%d/%y", errors='coerce')
    return df
    
def add_start_of_week_columns(df):
    df['Lead Week'] = df['Lead Date'] - pd.to_timedelta(df['Lead Date'].dt.weekday, unit='D')
    df['Prospect Week'] = df['Prospect Date'] - pd.to_timedelta(df['Prospect Date'].dt.weekday, unit='D')
    df['Approved Week'] = df['Approved Date'] - pd.to_timedelta(df['Approved Date'].dt.weekday, unit='D')
    df['Current Milestone Week'] = df['Current Milestone Date'] - pd.to_timedelta(df['Current Milestone Date'].dt.weekday, unit='D')
    return df

def get_unique_weeks(df):
    result = pd.DataFrame()
    result['week'] = df[['Lead Week', 'Prospect Week', 'Approved Week']].apply(lambda x: ', '.join(sorted(set(x.dropna().astype(str)))), axis=1)

    # Split the comma-separated strings in the 'week' column
    split_weeks = result['week'].str.split(', ', expand=True).stack()

    # Get the unique values from the stacked Series
    unique_weeks = split_weeks.unique()

    # Create a new DataFrame with the unique weeks
    final_result = pd.DataFrame(unique_weeks, columns=['Week'])

    # Sort the final result
    final_result = final_result.sort_values(by='Week')
    return final_result

def add_job_counts(result, df):
    # Initialize count columns in the unique_weeks_df
    result['Leads'] = 0
    result['Prospects'] = 0
    result['Approved'] = 0

    # Iterate through unique weeks and count occurrences in the raw data
    for index, row in result.iterrows():
        week = row['Week']
        
        # Count leads for the current week
        lead_count = df[df['Lead Week'] == week].shape[0]
        result.loc[index, 'Leads'] = lead_count
        
        # Count prospects for the current week
        prospect_count = df[df['Prospect Week'] == week].shape[0]
        result.loc[index, 'Prospects'] = prospect_count
        
        # Count approved jobs for the current week
        approved_count = df[df['Approved Week'] == week].shape[0]
        result.loc[index, 'Approved'] = approved_count    

    return result

def add_weekly_job_values(result, df):
    # 1. Calculate the weekly sum of Job Value for approved jobs
    approved_jobs = df[df['Approved Date'].notna()]  # Filter for approved jobs
    weekly_job_value_sum = approved_jobs.groupby('Approved Week')['Job Value'].sum().reset_index()  # Group by Approved Week and sum
    weekly_job_value_sum.rename(columns={'Job Value': 'Approved Job Value Sum'}, inplace=True)  # Rename column

    # 2. Merge with the result dataframe
    result = pd.merge(result, weekly_job_value_sum, left_on='Week', right_on='Approved Week', how='left')  # Merge
    result['Approved Job Value Sum'] = result['Approved Job Value Sum'].fillna(0)  # Fill NaN with 0

    # Remove the 'Approved Week' column if desired (it's redundant after the merge)
    result.drop('Approved Week', axis=1, inplace=True)
    return result 

def format_currency(df):
    locale.setlocale(locale.LC_ALL, 'en_US.UTF-8') 
    df['Approved Job Value Sum'] = df['Approved Job Value Sum'].apply(lambda x: locale.currency(x, grouping=True))
    return df

def main():
    st.set_page_config(layout="wide")

    st.title("📊 Acculynx Summary Generator")

    # Upload or load CSV file
    csv_file = st.file_uploader("Upload your Acculynx lead progress report here", type=["csv"])

    if csv_file is not None:
        
        # Read CSV and process data
        raw_df = read_csv(csv_file)
        st.success("✅ File loaded successfully!")
        processed_df = process_data(raw_df)

        # Display table
        st.write("Your Acculynx Lead Summary:")
        st.dataframe(processed_df)  # Interactive table view

    else:
        seperator = ", "
        st.info(f"""
        👆 Upload a CSV file to get started.
        The following columns are required:
        {seperator.join(NEEDED_COLUMNS)}
        """)

if __name__ == "__main__":
    main()