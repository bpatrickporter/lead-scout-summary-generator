import streamlit as st
import pandas as pd
import numpy as np
import locale

NEEDED_COLUMNS = [
        'Lead Date', 'Prospect Date', 'Approved Date', 'Current Status',
        'Current Milestone', 'Current Milestone Date', 'Job Value'
    ]

def prepare_raw_data(df):
    covert_dates_to_datetime(df)
    add_start_of_week_columns(df)

def process_data(df):
    result = get_unique_weeks(df)
    add_job_counts(result, df)
    result = add_weekly_job_values(result, df)
    result['Week'] = result['Week'].dt.date
    result.set_index('Week', inplace=True)
    return result

def covert_dates_to_datetime(df):
    df['Lead Date'] = pd.to_datetime(df['Lead Date'], format="%m/%d/%y", errors='coerce')
    df['Prospect Date'] = pd.to_datetime(df['Prospect Date'], format="%m/%d/%y", errors='coerce')
    df['Approved Date'] = pd.to_datetime(df['Approved Date'], format="%m/%d/%y", errors='coerce')
    df['Current Milestone Date'] = pd.to_datetime(df['Current Milestone Date'], format="%m/%d/%y", errors='coerce')
    
def add_start_of_week_columns(df):
    df['Lead Week'] = df['Lead Date'] - pd.to_timedelta(df['Lead Date'].dt.weekday, unit='D')
    df['Prospect Week'] = df['Prospect Date'] - pd.to_timedelta(df['Prospect Date'].dt.weekday, unit='D')
    df['Approved Week'] = df['Approved Date'] - pd.to_timedelta(df['Approved Date'].dt.weekday, unit='D')
    df['Current Milestone Week'] = df['Current Milestone Date'] - pd.to_timedelta(df['Current Milestone Date'].dt.weekday, unit='D')

def get_unique_weeks(df):
    result = pd.DataFrame()
    result['week'] = df[['Lead Week', 'Prospect Week', 'Approved Week']].apply(lambda x: ', '.join(sorted(set(x.dropna().astype(str)))), axis=1)

    # Split the comma-separated strings in the 'week' column
    split_weeks = result['week'].str.split(', ', expand=True).stack()

    # Get the unique values from the stacked Series
    unique_weeks = split_weeks.unique()

    # Create a new DataFrame with the unique weeks
    final_result = pd.DataFrame(unique_weeks, columns=['Week'])
    final_result['Week'] = pd.to_datetime(final_result['Week'])

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
    # Calculate the weekly sum of Job Value for approved jobs
    approved_jobs = df[df['Approved Date'].notna()]  # Filter for approved jobs
    weekly_job_value_sum = approved_jobs.groupby('Approved Week')['Job Value'].sum().reset_index()  # Group by Approved Week and sum
    weekly_job_value_sum.rename(columns={'Job Value': 'Approved Job Value Sum'}, inplace=True)  # Rename column

    # Merge with the result dataframe
    result = pd.merge(result, weekly_job_value_sum, left_on='Week', right_on='Approved Week', how='left')  # Merge
    result['Approved Job Value Sum'] = result['Approved Job Value Sum'].fillna(0)  # Fill NaN with 0

    # Remove the 'Approved Week' column if desired (it's redundant after the merge)
    result.drop('Approved Week', axis=1, inplace=True)

    format_currency(result)
    return result 

def format_currency(df):
    locale.setlocale(locale.LC_ALL, 'en_US.UTF-8') 
    df['Approved Job Value Sum'] = df['Approved Job Value Sum'].apply(lambda x: locale.currency(x, grouping=True))

def main():
    raw_df = pd.read_csv('data/acculynx_leads.csv', usecols=NEEDED_COLUMNS)
    prepare_raw_data(raw_df)
    processed_df = process_data(raw_df)

    st.title("🐆 Acculynx Lead Summary")
    st.write("Your Acculynx Lead Summary:")
    st.dataframe(processed_df)  # Interactive table view

if __name__ == "__main__":
    main()