# pages/2_Rules.py
import streamlit as st
import pandas as pd
import gspread
import json
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="Predicto Ads Dashboard — Rules", layout="wide")
st.title("Rules")

# ---- Google Sheets connection (דרך st.secrets) ----
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds_dict = json.loads(st.secrets["GOOGLE_SHEETS_CREDENTIALS"])
creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
client = gspread.authorize(creds)

SPREADSHEET_ID = "1wRDzNImkWSDmS5uZAgaECFO7X8HO2XO2f69FqQ1Qu7k"
SHEET_NAME = "Rules"

try:
    sheet = client.open_by_key(SPREADSHEET_ID)
    ws = sheet.worksheet(SHEET_NAME)
    df = pd.DataFrame(ws.get_all_records())
    if df.empty:
        st.warning("The 'Rules' sheet is empty.")
    else:
        st.success("Loaded 'Rules' from Google Sheets ✅")
        st.dataframe(df, use_container_width=True, hide_index=True)
except Exception as e:
    st.error(f"Failed to load 'Rules' sheet: {e}")
