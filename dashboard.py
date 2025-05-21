import streamlit as st
import requests
import openai
import numpy as np
import pandas as pd
import plotly.express as px
import gspread
import json
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta, timezone, date
from requests.auth import HTTPBasicAuth

# --- Завантаження з secrets ---
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
EMAIL = st.secrets["EMAIL"]
API_TOKEN = st.secrets["API_TOKEN"]
JIRA_DOMAIN = st.secrets["JIRA_DOMAIN"]
SPREADSHEET_ID = st.secrets["SPREADSHEET_ID"]
SHEET_NAME = st.secrets["SHEET_NAME"]
JIRA_PROJECT = st.secrets["JIRA_PROJECT"]

# --- Google credentials ---
creds = Credentials.from_service_account_info(
    json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"]),
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)

# Привітальний текст
st.title("📊 Jira Dashboard")
st.write("✅ Все працює. Тепер можна додавати свій функціонал!")
