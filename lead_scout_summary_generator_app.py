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

def main():
    acculynx = st.Page("./pages/acculynx.py", title="Acculynx Report Generator", icon=":material/paid:")
    lead_scout = st.Page("./pages/Lead_Scout.py", title="Lead Scout Report Generator", icon=":material/leaderboard:")
    pg = st.navigation([acculynx, lead_scout])
    st.set_page_config(page_title="📊 Report Generator", page_icon=":material/edit:", layout="wide")
    pg.run()


if __name__ == "__main__":
    main()