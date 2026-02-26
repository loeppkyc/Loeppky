"""
Google Sheets connection helper.
Cached as a resource so the connection is reused across reruns.
"""

import os
import gspread
import streamlit as st
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1arXxho2gD8IeWbQNcOt8IwZ7DRl2wz-qJzC3J4hiR4k"
SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]


@st.cache_resource
def get_spreadsheet():
    """Returns authenticated gspread Spreadsheet. Cached for the session lifetime."""
    # Cloud deployment: read from Streamlit secrets
    try:
        creds_info = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    except Exception:
        # Local development: walk up from this file to find sheets-credentials.json
        here = os.path.dirname(os.path.abspath(__file__))          # .../utils/
        app_dir = os.path.dirname(here)                            # .../streamlit_app/
        workspace_dir = os.path.dirname(app_dir)                  # workspace root
        creds_path = os.path.join(workspace_dir, "sheets-credentials.json")
        creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)

    gc = gspread.authorize(creds)
    return gc.open_by_key(SPREADSHEET_ID)
