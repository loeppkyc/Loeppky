"""
My Profile — view account info and change password.
"""

import streamlit as st
from utils.auth import require_auth, get_current_user, change_password, update_display_name

st.set_page_config(
    page_title="My Profile",
    page_icon="👤",
    layout="centered",
)

require_auth("business")

st.title("👤 My Profile")
st.divider()

user = get_current_user()
if not user:
    st.error("Could not load your profile. Please sign out and sign back in.")
    st.stop()

# ── Account Info ───────────────────────────────────────────────────────────────

st.subheader("Account Info")

ic1, ic2 = st.columns(2)
ic1.markdown(f"**Username**  \n{user.get('Username', '—')}")
ic2.markdown(f"**Role**  \n{user.get('Role', '—').capitalize()}")

ic3, ic4 = st.columns(2)
ic3.markdown(f"**Email**  \n{user.get('Email', '—')}")
ic4.markdown(f"**Member since**  \n{user.get('Created At', '—')}")

st.divider()

# ── Change Display Name ────────────────────────────────────────────────────────

st.subheader("Display Name")

with st.form("name_form"):
    new_name = st.text_input("Name", value=user.get("Name", ""), max_chars=60)
    if st.form_submit_button("Update Name", type="secondary"):
        if not new_name.strip():
            st.error("Name can't be blank.")
        elif new_name.strip() == user.get("Name", ""):
            st.info("That's already your current name.")
        else:
            ok, msg = update_display_name(user["Username"], new_name)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

st.divider()

# ── Change Password ────────────────────────────────────────────────────────────

st.subheader("Change Password")

with st.form("pw_form"):
    current_pw = st.text_input("Current password", type="password")
    new_pw     = st.text_input("New password (min 8 chars)", type="password")
    confirm_pw = st.text_input("Confirm new password", type="password")

    if st.form_submit_button("Update Password", type="primary"):
        if not all([current_pw, new_pw, confirm_pw]):
            st.error("All fields are required.")
        elif new_pw != confirm_pw:
            st.error("New passwords don't match.")
        elif len(new_pw) < 8:
            st.error("New password must be at least 8 characters.")
        elif new_pw == current_pw:
            st.error("New password must be different from your current password.")
        else:
            ok, msg = change_password(user["Username"], current_pw, new_pw)
            if ok:
                st.success(msg)
            else:
                st.error(msg)
