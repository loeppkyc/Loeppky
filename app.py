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

# ─── PWA + branding meta tags ──────────────────────────────────────────────────

st.markdown("""
<link rel="manifest"         href="/app/static/manifest.json">
<link rel="apple-touch-icon" href="/app/static/icon-192.png">
<meta name="apple-mobile-web-app-capable"          content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title"            content="Loeppky">
<meta name="theme-color"                           content="#2d6a9f">
""", unsafe_allow_html=True)

# ─── Global CSS ───────────────────────────────────────────────────────────────

st.markdown("""
<style>
/* ── Metric cards ── */
[data-testid="metric-container"] {
    background: #1a1f2e;
    border: 1px solid rgba(45, 106, 159, 0.35);
    border-radius: 10px;
    padding: 18px 16px 14px 16px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.35);
}
[data-testid="stMetricValue"] > div {
    font-size: 1.65rem !important;
    font-weight: 700 !important;
}
[data-testid="stMetricLabel"] > div {
    font-size: 0.78rem !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #8899aa !important;
}

/* ── Buttons ── */
.stButton > button {
    border-radius: 8px !important;
    font-weight: 600 !important;
    letter-spacing: 0.02em;
    transition: all 0.15s ease !important;
}
.stButton > button[kind="primary"] {
    background: #2d6a9f !important;
    border: none !important;
}
.stButton > button:hover {
    filter: brightness(1.15) !important;
    box-shadow: 0 4px 12px rgba(45,106,159,0.4) !important;
}

/* ── Sidebar branding ── */
[data-testid="stSidebar"] > div:first-child {
    padding-top: 0 !important;
}
.sidebar-brand {
    background: linear-gradient(160deg, #12172a 0%, #1a2540 100%);
    border-bottom: 2px solid #c89b37;
    padding: 18px 20px 14px 20px;
    margin: -1rem -1rem 1rem -1rem;
}
.sidebar-brand .brand-name {
    font-size: 1.25rem;
    font-weight: 800;
    color: #c89b37;
    letter-spacing: 0.04em;
}
.sidebar-brand .brand-sub {
    font-size: 0.72rem;
    color: #6a7f99;
    margin-top: 2px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}

/* ── Dividers ── */
hr {
    border-color: rgba(255,255,255,0.08) !important;
    margin: 1.2rem 0 !important;
}

/* ── Dataframe ── */
[data-testid="stDataFrame"] {
    border-radius: 10px !important;
    overflow: hidden;
    border: 1px solid rgba(45, 106, 159, 0.2) !important;
}

/* ── Section labels ── */
.section-label {
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: #2d6a9f;
    margin-bottom: 0.5rem;
}

/* ── Nav card grid ── */
.nav-card {
    background: #1a1f2e;
    border: 1px solid rgba(45,106,159,0.25);
    border-radius: 10px;
    padding: 14px 16px;
    margin-bottom: 8px;
    cursor: pointer;
    transition: border-color 0.15s ease;
}
.nav-card:hover {
    border-color: #2d6a9f;
}
.nav-card .nav-icon { font-size: 1.4rem; }
.nav-card .nav-title { font-weight: 600; font-size: 0.9rem; margin-top: 4px; }
.nav-card .nav-desc  { font-size: 0.75rem; color: #6a7f99; margin-top: 2px; }
</style>
""", unsafe_allow_html=True)

# ─── Sidebar branding ─────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("""
    <div class="sidebar-brand">
        <div class="brand-name">📚 LOEPPKY</div>
        <div class="brand-sub">Business Dashboard</div>
    </div>
    """, unsafe_allow_html=True)

# ─── Data loaders ─────────────────────────────────────────────────────────────

TIMEZONE = ZoneInfo("America/Edmonton")
now = datetime.now(TIMEZONE)


@st.cache_data(ttl=300)
def load_amazon_data() -> pd.DataFrame:
    ws = get_spreadsheet().worksheet("📊 Amazon 2026")
    data = ws.get_all_records()
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    df["Date"] = pd.to_datetime(df["Date"], format="%d/%m/%Y", errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date")
    for col in ["SalesOrganic", "UnitsOrganic", "Orders", "AmazonFees",
                "Refunds", "EstimatedPayout", "GrossProfit"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


@st.cache_data(ttl=300)
def load_inventory_counts() -> tuple[int, int]:
    try:
        ws   = get_spreadsheet().worksheet("📦 Book Inventory")
        data = ws.get_all_records()
        if not data:
            return 0, 0
        df = pd.DataFrame(data)
        if "Status" not in df.columns:
            return len(df), 0
        return int((df["Status"] == "Unlisted").sum()), int((df["Status"] == "Listed").sum())
    except Exception:
        return 0, 0


# ─── Compute metrics ──────────────────────────────────────────────────────────

df = load_amazon_data()
unlisted, listed = load_inventory_counts()
current_month = now.strftime("%Y-%m")
yesterday     = (now - timedelta(days=1)).date()

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

col_title, col_btn = st.columns([5, 1])
with col_title:
    st.markdown("""
    <div style="padding: 4px 0 0 0;">
        <span style="font-size:2rem; font-weight:800; color:#fafafa; letter-spacing:0.02em;">
            📚 Loeppky
        </span>
        <span style="font-size:0.85rem; color:#6a7f99; margin-left:12px;">
            Business Dashboard
        </span>
    </div>
    """, unsafe_allow_html=True)
    st.caption(f"Edmonton  ·  {now.strftime('%A, %B %d %Y  ·  %I:%M %p')}")

with col_btn:
    st.write("")
    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

st.divider()


# ─── Yesterday ────────────────────────────────────────────────────────────────

st.markdown(f'<div class="section-label">Yesterday — {yesterday.strftime("%B %d")}</div>',
            unsafe_allow_html=True)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Sales",       f"${y_sales:,.2f}")
c2.metric("Est. Payout", f"${y_payout:,.2f}")
c3.metric("Units Sold",  str(y_units))
c4.metric("Orders",      str(y_orders))

st.divider()


# ─── Month to date ────────────────────────────────────────────────────────────

st.markdown(f'<div class="section-label">Month to Date — {now.strftime("%B %Y")}</div>',
            unsafe_allow_html=True)
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("MTD Sales",        f"${mtd_sales:,.2f}")
c2.metric("MTD Est. Payout",  f"${mtd_payout:,.2f}")
c3.metric("MTD Gross Profit", f"${mtd_profit:,.2f}")
c4.metric("Unlisted Books",   str(unlisted))
c5.metric("Listed on FBA",    str(listed))

st.divider()


# ─── Daily sales chart ────────────────────────────────────────────────────────

if not df_month.empty and len(df_month) > 1:
    st.markdown('<div class="section-label">Daily Sales This Month</div>',
                unsafe_allow_html=True)
    chart = df_month[["Date", "SalesOrganic", "EstimatedPayout"]].copy()
    chart = chart.rename(columns={"SalesOrganic": "Sales", "EstimatedPayout": "Est. Payout"})
    chart = chart.set_index("Date")
    st.line_chart(chart, color=["#2d6a9f", "#c89b37"])

st.divider()


# ─── Recent days table ────────────────────────────────────────────────────────

st.markdown('<div class="section-label">Recent Days</div>', unsafe_allow_html=True)
if not df.empty:
    cols = ["Date", "SalesOrganic", "UnitsOrganic", "Orders", "AmazonFees",
            "Refunds", "EstimatedPayout", "GrossProfit"]
    cols   = [c for c in cols if c in df.columns]
    recent = df[cols].tail(10).copy()
    recent["Date"] = recent["Date"].dt.strftime("%b %d")
    recent = recent.iloc[::-1].reset_index(drop=True)
    recent = recent.rename(columns={
        "SalesOrganic":    "Sales",
        "UnitsOrganic":    "Units",
        "AmazonFees":      "Amazon Fees",
        "EstimatedPayout": "Est. Payout",
        "GrossProfit":     "Gross Profit",
    })
    st.dataframe(recent, use_container_width=True, hide_index=True)
else:
    st.info("No Amazon data loaded yet. Run daily_pl.py or trigger it manually.")

st.divider()


# ─── Phone / PWA install tip ──────────────────────────────────────────────────

with st.expander("📱 Add to your phone's home screen"):
    local_ip = "192.168.1.75"
    port     = 8501
    st.markdown(f"""
**Step 1 — Find your PC's IP address**
Open Command Prompt → type `ipconfig` → look for **IPv4 Address** (e.g. `192.168.1.42`)

**Step 2 — Open the app on your phone**
Make sure your phone is on the same Wi-Fi, then open your browser and go to:
```
http://{local_ip}:{port}
```

**Step 3 — Add to home screen**

| Phone | Steps |
|-------|-------|
| **iPhone (Safari)** | Tap Share button → "Add to Home Screen" → tap Add |
| **Android (Chrome)** | Tap the 3-dot menu → "Add to Home screen" → Add |

The app will appear on your home screen like a native app with the Loeppky icon.

> **Tip:** Streamlit must be running on your PC for the app to load on your phone.
    """)
