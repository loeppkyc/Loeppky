"""
Monthly P&L
Visual breakdown of income vs expenses by month, pulled from Monthly Cashflow sheet.
"""

import streamlit as st
import pandas as pd
from utils.sheets import get_spreadsheet
from utils.auth import require_auth

st.set_page_config(
    page_title="Monthly P&L",
    page_icon="📈",
    layout="wide",
)

require_auth("business")


@st.cache_data(ttl=300)
def load_cashflow() -> pd.DataFrame:
    ws = get_spreadsheet().worksheet("📊 Monthly Cashflow")
    data = ws.get_all_values()
    if len(data) < 3:
        return pd.DataFrame()

    # Row 2 (index 1) = month headers, Row 3 (index 2) = month keys
    # We want: label rows with their monthly values
    # Build a simple dict: {label: [jan_val, feb_val, ...]}
    month_headers = data[1][1:13]   # Jan–Dec (columns B–M)
    rows = []
    for row in data[3:]:            # Skip title, headers, helper row
        if not row or not row[0]:
            continue
        label  = row[0].strip()
        values = []
        for v in row[1:13]:
            try:
                values.append(float(str(v).replace(",", "").replace("$", "") or 0))
            except ValueError:
                values.append(0.0)
        if any(v != 0 for v in values):
            rows.append({"Label": label, **dict(zip(month_headers, values))})

    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ─── Page ─────────────────────────────────────────────────────────────────────

st.title("📈 Monthly P&L")

if st.button("🔄 Refresh"):
    st.cache_data.clear()
    st.rerun()

df = load_cashflow()

if df.empty:
    st.info("No data yet — add expenses and the dashboard will populate automatically.")
    st.stop()

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
available_months = [m for m in MONTHS if m in df.columns]

# Pull key rows
def get_row(label_fragment: str) -> list[float]:
    match = df[df["Label"].str.contains(label_fragment, case=False, na=False)]
    if match.empty:
        return [0.0] * len(available_months)
    return [float(match.iloc[0].get(m, 0) or 0) for m in available_months]

payout   = get_row("Est. Net Payout")
expenses = get_row("Total Business Expenses")
profit   = get_row("Operating Profit")

# ─── Summary metrics ──────────────────────────────────────────────────────────
ytd_payout   = sum(payout)
ytd_expenses = sum(expenses)
ytd_profit   = sum(profit)

c1, c2, c3 = st.columns(3)
c1.metric("YTD Payout",           f"${ytd_payout:,.2f}")
c2.metric("YTD Business Expenses",f"${ytd_expenses:,.2f}")
delta_color = "normal" if ytd_profit >= 0 else "inverse"
c3.metric("YTD Operating Profit", f"${ytd_profit:,.2f}",
          delta=f"${ytd_profit:,.2f}", delta_color=delta_color)

st.divider()

# ─── Bar chart: Payout vs Expenses ────────────────────────────────────────────
st.subheader("Payout vs Expenses by Month")
chart_df = pd.DataFrame({
    "Month":    available_months,
    "Payout":   payout,
    "Expenses": expenses,
}).set_index("Month")
st.bar_chart(chart_df, color=["#2d6a9f", "#e07b39"])

# ─── Profit line ──────────────────────────────────────────────────────────────
st.subheader("Operating Profit by Month")
profit_df = pd.DataFrame({
    "Month":  available_months,
    "Profit": profit,
}).set_index("Month")
st.bar_chart(profit_df, color="#4caf82")

st.divider()

# ─── Full table ───────────────────────────────────────────────────────────────
st.subheader("Full Breakdown")
display = df.set_index("Label")[available_months] if available_months else df
st.dataframe(display, use_container_width=True)
