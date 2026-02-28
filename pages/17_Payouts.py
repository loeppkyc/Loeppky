"""
Payout Register
Log actual Amazon disbursements and compare to estimated payout from Finance API.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from utils.sheets import get_spreadsheet
from utils.auth import require_auth

st.set_page_config(
    page_title="Payout Register",
    page_icon="💰",
    layout="wide",
)

require_auth("business")

TIMEZONE      = ZoneInfo("America/Edmonton")
PAYOUT_SHEET  = "💰 Payout Register"
AMAZON_SHEET  = "📊 Amazon 2026"


# ─── Loaders ──────────────────────────────────────────────────────────────────

@st.cache_data(ttl=120)
def load_payouts() -> pd.DataFrame:
    ws   = get_spreadsheet().worksheet(PAYOUT_SHEET)
    data = ws.get_all_records()
    if not data:
        return pd.DataFrame(columns=[
            "Date Received", "Period Label", "Amount Expected ($)",
            "Amount Received ($)", "Difference ($)", "Account", "Status", "Notes"
        ])
    df = pd.DataFrame(data)
    for col in ["Amount Expected ($)", "Amount Received ($)", "Difference ($)"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


@st.cache_data(ttl=300)
def load_amazon_daily() -> pd.DataFrame:
    ws   = get_spreadsheet().worksheet(AMAZON_SHEET)
    data = ws.get_all_records()
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    df["Date"] = pd.to_datetime(df["Date"], format="%d/%m/%Y", errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date")
    df["EstimatedPayout"] = pd.to_numeric(df["EstimatedPayout"], errors="coerce").fillna(0)
    return df


# ─── Page ─────────────────────────────────────────────────────────────────────

st.title("💰 Payout Register")
st.caption("Log each Amazon disbursement that hits your TD account. Compare actual vs estimated.")

col_r, _ = st.columns([1, 5])
with col_r:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

payouts    = load_payouts()
amazon_df  = load_amazon_daily()

# ─── Summary metrics ──────────────────────────────────────────────────────────

ytd_estimated = float(amazon_df["EstimatedPayout"].sum()) if not amazon_df.empty else 0.0
ytd_received  = float(payouts["Amount Received ($)"].sum()) if not payouts.empty else 0.0
ytd_variance  = ytd_received - ytd_estimated
payout_count  = len(payouts[payouts["Amount Received ($)"] > 0]) if not payouts.empty else 0

st.markdown('<div style="font-size:0.72rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:#2d6a9f;margin-bottom:0.5rem;">2026 YTD Summary (CAD)</div>', unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)
c1.metric("YTD Estimated Payout",  f"${ytd_estimated:,.2f}",
          help="Sum of all daily EstimatedPayout from Finance API")
c2.metric("YTD Actually Received", f"${ytd_received:,.2f}",
          help="Sum of actual Amazon deposits logged below")
c3.metric("Variance (Actual − Est.)", f"${ytd_variance:,.2f}",
          delta=f"${ytd_variance:,.2f}",
          delta_color="normal" if ytd_variance >= -500 else "inverse",
          help="Negative = Amazon still owes you vs estimate. Usually due to reserve or timing.")
c4.metric("Payouts Logged", str(payout_count))

st.divider()

# ─── Log a new payout ─────────────────────────────────────────────────────────

st.markdown('<div style="font-size:0.72rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:#2d6a9f;margin-bottom:0.5rem;">Log a New Payout</div>', unsafe_allow_html=True)

with st.form("payout_form"):
    fc1, fc2 = st.columns(2)

    with fc1:
        date_received = st.date_input(
            "Date Received (when it hit your bank)",
            value=datetime.now(TIMEZONE).date() - timedelta(days=1),
        )
        amount_received = st.number_input(
            "Amount Received — CAD $ (from your bank statement)",
            min_value=0.0, value=0.0, format="%.2f",
        )
        account = st.selectbox("Account", ["TD Bank", "Other"])

    with fc2:
        period_label = st.text_input(
            "Period Label (e.g. Feb 1–14 2026)",
            placeholder="Feb 1–14 2026",
        )
        st.markdown("**Auto-calculate Expected from Amazon data:**")
        period_start = st.date_input("Period Start", value=datetime.now(TIMEZONE).date() - timedelta(days=14))
        period_end   = st.date_input("Period End",   value=datetime.now(TIMEZONE).date() - timedelta(days=1))

    notes = st.text_input("Notes (optional)", placeholder="e.g. matches Seller Central disbursement #xxx")

    submitted = st.form_submit_button("💾 Save Payout", type="primary")

    if submitted:
        # Calculate expected from Amazon daily data for the period
        if not amazon_df.empty:
            mask = (
                (amazon_df["Date"].dt.date >= period_start) &
                (amazon_df["Date"].dt.date <= period_end)
            )
            expected = round(float(amazon_df.loc[mask, "EstimatedPayout"].sum()), 2)
        else:
            expected = 0.0

        difference = round(amount_received - expected, 2)
        status     = "✅ Match" if abs(difference) < 50 else ("⚠️ Small Diff" if abs(difference) < 500 else "❌ Review")

        new_row = [
            date_received.strftime("%Y-%m-%d"),
            period_label or f"{period_start} to {period_end}",
            expected,
            round(amount_received, 2),
            difference,
            account,
            status,
            notes,
        ]

        ws = get_spreadsheet().worksheet(PAYOUT_SHEET)
        ws.append_row(new_row, value_input_option="USER_ENTERED")
        st.success(f"Saved! Expected ${expected:,.2f} · Received ${amount_received:,.2f} · Variance ${difference:,.2f}")
        st.cache_data.clear()
        st.rerun()

st.divider()

# ─── Payout history ───────────────────────────────────────────────────────────

st.markdown('<div style="font-size:0.72rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:#2d6a9f;margin-bottom:0.5rem;">Payout History</div>', unsafe_allow_html=True)

if payouts.empty:
    st.info("No payouts logged yet. Use the form above to log your first Amazon deposit.")
else:
    # Format for display
    disp = payouts.copy()
    for col in ["Amount Expected ($)", "Amount Received ($)", "Difference ($)"]:
        if col in disp.columns:
            disp[col] = disp[col].apply(lambda x: f"${x:,.2f}" if x != 0 else "—")
    st.dataframe(disp, use_container_width=True, hide_index=True)

    # Monthly summary if multiple payouts
    if len(payouts) > 1 and "Date Received" in payouts.columns:
        with st.expander("📅 Monthly rollup"):
            try:
                p = payouts.copy()
                p["Month"] = pd.to_datetime(p["Date Received"], errors="coerce").dt.strftime("%Y-%m")
                rollup = p.groupby("Month").agg(
                    Payouts=("Amount Received ($)", "count"),
                    Received=("Amount Received ($)", "sum"),
                    Expected=("Amount Expected ($)", "sum"),
                ).reset_index()
                rollup["Variance"] = rollup["Received"] - rollup["Expected"]
                for col in ["Received", "Expected", "Variance"]:
                    rollup[col] = rollup[col].apply(lambda x: f"${x:,.2f}")
                st.dataframe(rollup, use_container_width=True, hide_index=True)
            except Exception:
                pass

st.divider()

# ─── How payouts work ─────────────────────────────────────────────────────────

with st.expander("ℹ️ How Amazon payouts work"):
    st.markdown("""
**Amazon pays every 14 days** (bi-weekly), covering orders that settled during that period.

**Why Actual ≠ Estimated:**
- Amazon holds a **reserve** (usually 3–7% of recent sales) as a buffer for refunds
- There's a **1–3 day processing lag** between settlement and deposit
- Refunds processed after the payout period may be deducted from the next payout

**To find your actual disbursements:**
Seller Central → Payments → Transaction View → filter by "Transfer" type

**Where to find the period covered:**
Seller Central → Payments → Disbursements → click any disbursement for the date range
    """)
