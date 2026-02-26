"""
Admin panel — login activity log and user management.
Visible to admin role only.
"""

import streamlit as st
import pandas as pd
from utils.auth import require_auth, LOG_SHEET, USERS_SHEET
from utils.sheets import get_spreadsheet

st.set_page_config(
    page_title="Admin",
    page_icon="🔧",
    layout="wide",
)

require_auth("business")

# Admin-only guard
if st.session_state.get("_auth_role") != "admin":
    st.error("🔒 Admin access only.")
    st.stop()

st.title("🔧 Admin Panel")
st.divider()


@st.cache_data(ttl=30)
def _load_sheet(sheet_name: str) -> list[dict]:
    try:
        return get_spreadsheet().worksheet(sheet_name).get_all_records()
    except Exception:
        return []


col_refresh, _ = st.columns([1, 5])
if col_refresh.button("🔄 Refresh", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

# ── Login Log ──────────────────────────────────────────────────────────────────

st.subheader("📋 Login Activity")

log = _load_sheet(LOG_SHEET)

if not log:
    st.info("No login events recorded yet. Events are logged on next sign-in.")
else:
    df = pd.DataFrame(log)
    df.columns = [c.strip() for c in df.columns]

    # Filters
    fc1, fc2, fc3 = st.columns(3)
    users      = ["All"] + sorted(df["Username"].dropna().unique().tolist())
    actions    = ["All", "Login", "Logout"]
    user_filt  = fc1.selectbox("User", users, key="log_user")
    action_filt = fc2.selectbox("Action", actions, key="log_action")
    n_rows     = fc3.number_input("Show last N rows (0 = all)", min_value=0, value=50, step=10, key="log_n")

    filtered = df.copy()
    if user_filt != "All":
        filtered = filtered[filtered["Username"] == user_filt]
    if action_filt != "All":
        filtered = filtered[filtered["Action"] == action_filt]

    filtered = filtered.sort_values("Timestamp", ascending=False)
    if n_rows > 0:
        filtered = filtered.head(int(n_rows))

    lc1, lc2, lc3 = st.columns(3)
    lc1.metric("Total Events", len(df))
    lc2.metric("Logins",  len(df[df["Action"] == "Login"]))
    lc3.metric("Logouts", len(df[df["Action"] == "Logout"]))

    st.dataframe(filtered, hide_index=True, use_container_width=True)

    csv = filtered.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Download log as CSV",
        data=csv,
        file_name="login_log.csv",
        mime="text/csv",
    )

st.divider()

# ── Users ──────────────────────────────────────────────────────────────────────

st.subheader("👤 Registered Users")

users_data = _load_sheet(USERS_SHEET)

if not users_data:
    st.info("No users found.")
else:
    safe_cols = ["Username", "Name", "Email", "Role", "Verified", "Created At"]
    users_df  = pd.DataFrame(users_data)
    show_cols = [c for c in safe_cols if c in users_df.columns]
    st.dataframe(users_df[show_cols], hide_index=True, use_container_width=True)
    st.caption("To change a user's role or verification status, edit the 👤 Users sheet directly in Google Sheets.")
