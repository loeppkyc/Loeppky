"""
Loeppky — Business Dashboard
Home page: yesterday's snapshot + month-to-date metrics + daily sales chart.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from utils.sheets import get_spreadsheet
from utils.auth import require_auth

st.set_page_config(
    page_title="Loeppky",
    page_icon="📚",
    layout="wide",
)

require_auth("business")

TIMEZONE = ZoneInfo("America/Edmonton")
now = datetime.now(TIMEZONE)


# ─── Data loaders ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_amazon_data() -> pd.DataFrame:
    ws = get_spreadsheet().worksheet("📊 Amazon 2026")
    data = ws.get_all_records()
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    df["Date"] = pd.to_datetime(df["Date"], format="%d/%m/%Y", errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date")
    # Ensure numeric columns
    for col in ["SalesOrganic", "UnitsOrganic", "Orders", "AmazonFees",
                "Refunds", "EstimatedPayout", "GrossProfit"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


@st.cache_data(ttl=300)
def load_inventory_counts() -> tuple[int, int]:
    try:
        ws = get_spreadsheet().worksheet("📦 Book Inventory")
        data = ws.get_all_records()
        if not data:
            return 0, 0
        df = pd.DataFrame(data)
        if "Status" not in df.columns:
            return len(df), 0
        unlisted = int((df["Status"] == "Unlisted").sum())
        listed   = int((df["Status"] == "Listed").sum())
        return unlisted, listed
    except Exception:
        return 0, 0


# ─── Load data ────────────────────────────────────────────────────────────────

df = load_amazon_data()
unlisted, listed = load_inventory_counts()
current_month = now.strftime("%Y-%m")
yesterday = (now - timedelta(days=1)).date()

if not df.empty:
    df_month     = df[df["Date"].dt.strftime("%Y-%m") == current_month]
    df_yesterday = df[df["Date"].dt.date == yesterday]

    y_sales  = float(df_yesterday["SalesOrganic"].sum())
    y_payout = float(df_yesterday["EstimatedPayout"].sum())
    y_units  = int(df_yesterday["UnitsOrganic"].sum())
    y_orders = int(df_yesterday["Orders"].sum())

    mtd_sales  = float(df_month["SalesOrganic"].sum())
    mtd_payout = float(df_month["EstimatedPayout"].sum())
    mtd_units  = int(df_month["UnitsOrganic"].sum())
    mtd_orders = int(df_month["Orders"].sum())
    mtd_profit = float(df_month["GrossProfit"].sum())
else:
    y_sales = y_payout = y_units = y_orders = 0
    mtd_sales = mtd_payout = mtd_units = mtd_orders = mtd_profit = 0
    df_month = pd.DataFrame()


# ─── Header ───────────────────────────────────────────────────────────────────

st.title("📚 Loeppky")
st.caption(f"Updated: {now.strftime('%B %d, %Y  %I:%M %p')}")

# Refresh button
if st.button("🔄 Refresh data"):
    st.cache_data.clear()
    st.rerun()

st.divider()


# ─── Yesterday ────────────────────────────────────────────────────────────────

st.subheader(f"Yesterday — {yesterday.strftime('%B %d')}")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Sales",        f"${y_sales:,.2f}")
c2.metric("Est. Payout",  f"${y_payout:,.2f}")
c3.metric("Units Sold",   str(y_units))
c4.metric("Orders",       str(y_orders))

st.divider()


# ─── Month to date ────────────────────────────────────────────────────────────

st.subheader(f"Month to Date — {now.strftime('%B %Y')}")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("MTD Sales",       f"${mtd_sales:,.2f}")
c2.metric("MTD Est. Payout", f"${mtd_payout:,.2f}")
c3.metric("MTD Gross Profit",f"${mtd_profit:,.2f}")
c4.metric("Unlisted Books",  str(unlisted))
c5.metric("Listed on FBA",   str(listed))

st.divider()


# ─── Daily sales chart ────────────────────────────────────────────────────────

if not df_month.empty and len(df_month) > 1:
    st.subheader("Daily Sales This Month")
    chart = df_month[["Date", "SalesOrganic", "EstimatedPayout"]].copy()
    chart = chart.rename(columns={"SalesOrganic": "Sales", "EstimatedPayout": "Est. Payout"})
    chart = chart.set_index("Date")
    st.line_chart(chart, color=["#2d6a9f", "#4caf82"])


# ─── Recent days table ────────────────────────────────────────────────────────

st.subheader("Recent Days")
if not df.empty:
    cols = ["Date", "SalesOrganic", "UnitsOrganic", "Orders", "AmazonFees",
            "Refunds", "EstimatedPayout", "GrossProfit"]
    cols = [c for c in cols if c in df.columns]
    recent = df[cols].tail(10).copy()
    recent["Date"] = recent["Date"].dt.strftime("%b %d")
    recent = recent.iloc[::-1].reset_index(drop=True)
    rename = {
        "SalesOrganic": "Sales",
        "UnitsOrganic": "Units",
        "AmazonFees":   "Amazon Fees",
        "EstimatedPayout": "Est. Payout",
        "GrossProfit":  "Gross Profit",
    }
    recent = recent.rename(columns=rename)
    st.dataframe(recent, use_container_width=True, hide_index=True)
else:
    st.info("No Amazon data loaded yet.")
