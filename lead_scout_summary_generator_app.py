import streamlit as st

def main():
    acculynx = st.Page("./pages/acculynx.py", title="Acculynx Report Generator", icon=":material/paid:")
    lead_scout = st.Page("./pages/Lead_Scout.py", title="Lead Scout Report Generator", icon=":material/leaderboard:")
    pg = st.navigation([acculynx, lead_scout])
    st.set_page_config(page_title="📊 Report Generator", page_icon=":material/edit:", layout="wide")
    pg.run()

if __name__ == "__main__":
    main()