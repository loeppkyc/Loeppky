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
c1.metric("Sales (CAD)",       f"${y_sales:,.2f}")
c2.metric("Est. Payout (CAD)", f"${y_payout:,.2f}")
c3.metric("Units Sold",        str(y_units))
c4.metric("Orders",            str(y_orders))

st.divider()


# ─── Month to date ────────────────────────────────────────────────────────────

st.markdown(f'<div class="section-label">Month to Date — {now.strftime("%B %Y")}</div>',
            unsafe_allow_html=True)
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("MTD Sales (CAD)",        f"${mtd_sales:,.2f}")
c2.metric("MTD Est. Payout (CAD)",  f"${mtd_payout:,.2f}")
c3.metric("MTD Gross Profit (CAD)", f"${mtd_profit:,.2f}")
c4.metric("Unlisted Books",         str(unlisted))
c5.metric("Listed on FBA",          str(listed))

st.divider()


# ─── Sales chart with time frame selector ─────────────────────────────────────

today = now.date()

tf_label = st.radio(
    "Time frame",
    ["Today", "7 Days", "MTD", "YTD"],
    index=2,
    horizontal=True,
    label_visibility="collapsed",
)

if not df.empty:
    if tf_label == "Today":
        chart_df = df[df["Date"].dt.date == today]
        prior_df = df[df["Date"].dt.date == yesterday]
    elif tf_label == "7 Days":
        chart_df = df[df["Date"].dt.date >= (today - timedelta(days=6))]
        prior_df = df[
            (df["Date"].dt.date >= (today - timedelta(days=13))) &
            (df["Date"].dt.date <= (today - timedelta(days=7)))
        ]
    elif tf_label == "MTD":
        chart_df = df_month
        _first     = now.replace(day=1).date()
        _prev_last = _first - timedelta(days=1)
        _prev_first = _prev_last.replace(day=1)
        _prev_end  = _prev_last if today.day > _prev_last.day else _prev_first.replace(day=today.day)
        prior_df = df[
            (df["Date"].dt.date >= _prev_first) &
            (df["Date"].dt.date <= _prev_end)
        ]
    else:  # YTD
        chart_df = df[df["Date"].dt.year == now.year]
        prior_df = pd.DataFrame()  # 2025 data is monthly — skip YTD delta
else:
    chart_df = pd.DataFrame()
    prior_df = pd.DataFrame()

st.markdown(f'<div class="section-label">Sales — {tf_label}</div>',
            unsafe_allow_html=True)

if not chart_df.empty:
    _sales   = float(chart_df["SalesOrganic"].sum())
    _payout  = float(chart_df["EstimatedPayout"].sum())
    _units   = int(chart_df["UnitsOrganic"].sum())
    _orders  = int(chart_df["Orders"].sum())
    _days    = int((chart_df["SalesOrganic"] > 0).sum())
    _avg_u   = round(_units / _orders, 2) if _orders > 0 else 0.0
    _avg_s   = round(_sales / _orders, 2) if _orders > 0 else 0.0

    def _dpct(curr, prev):
        return f"{(curr - prev) / prev * 100:+.1f}%" if prev != 0 else None

    if not prior_df.empty:
        p_sales  = float(prior_df["SalesOrganic"].sum())
        p_payout = float(prior_df["EstimatedPayout"].sum())
        p_units  = int(prior_df["UnitsOrganic"].sum())
        p_orders = int(prior_df["Orders"].sum())
        p_avg_u  = round(p_units / p_orders, 2) if p_orders > 0 else 0.0
        p_avg_s  = round(p_sales / p_orders, 2) if p_orders > 0 else 0.0
        d_sales  = _dpct(_sales,  p_sales)
        d_payout = _dpct(_payout, p_payout)
        d_units  = _dpct(_units,  p_units)
        d_orders = _dpct(_orders, p_orders)
        d_avg_u  = _dpct(_avg_u,  p_avg_u)
        d_avg_s  = _dpct(_avg_s,  p_avg_s)
    else:
        d_sales = d_payout = d_units = d_orders = d_avg_u = d_avg_s = None

    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("Sales (CAD)",         f"${_sales:,.2f}",  delta=d_sales)
    mc2.metric("Est. Payout (CAD)",   f"${_payout:,.2f}", delta=d_payout)
    mc3.metric("Units Sold",          str(_units),        delta=d_units)
    mc4.metric("Orders",              str(_orders),       delta=d_orders)

    mc5, mc6, mc7, mc8 = st.columns(4)
    mc5.metric("Avg Units/Order",       f"{_avg_u:.2f}",    delta=d_avg_u)
    mc6.metric("Avg Sales/Order (CAD)", f"${_avg_s:,.2f}",  delta=d_avg_s)
    mc7.metric("Days w/ Sales",         str(_days))
    mc8.write("")

if not chart_df.empty:
    chart = chart_df[["Date", "SalesOrganic", "EstimatedPayout"]].copy()
    chart = chart.rename(columns={"SalesOrganic": "Sales (CAD)", "EstimatedPayout": "Est. Payout (CAD)"})
    chart = chart.set_index("Date")
    st.line_chart(chart, color=["#2d6a9f", "#c89b37"])
elif tf_label == "Today":
    st.info("Today's data not yet available — updates at 6am daily.")
else:
    st.info(f"No data found for {tf_label}.")

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
