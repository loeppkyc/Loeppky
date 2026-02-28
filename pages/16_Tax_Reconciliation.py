"""
Tax Reconciliation — 2025
Compare app-calculated Amazon totals against QuickBooks and accountant numbers.
"""

import streamlit as st
import pandas as pd
from utils.sheets import get_spreadsheet
from utils.auth import require_auth

st.set_page_config(
    page_title="Tax Reconciliation",
    page_icon="🧾",
    layout="wide",
)

require_auth("business")

RECON_SHEET = "📋 Tax Reconciliation 2025"

# Metrics in order — must match the sheet rows exactly
METRICS = [
    "Gross Revenue",
    "Refunds",
    "Amazon Fees",
    "Net Payout",
    "COGS",
    "Gross Profit",
    "Operating Expenses",
    "Net Profit",
]


# ─── Data loaders ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_2025_totals() -> dict:
    """Sum all 12 months from Amazon 2025 sheet."""
    ws   = get_spreadsheet().worksheet("📊 Amazon 2025")
    data = ws.get_all_records()
    if not data:
        return {}
    df = pd.DataFrame(data)

    def s(col):
        if col not in df.columns:
            return 0.0
        return round(float(pd.to_numeric(df[col], errors="coerce").fillna(0).sum()), 2)

    gross_revenue      = round(s("SalesOrganic") + s("SalesPPC"), 2)
    refunds            = s("Refunds")          # count of refunds (units), not dollars
    refund_cost        = s("RefundCost")        # dollar value (negative)
    amazon_fees        = s("AmazonFees")        # negative
    net_payout         = s("EstimatedPayout")
    cogs               = s("Cost of Goods")     # negative
    gross_profit       = s("GrossProfit")
    expenses           = s("Expenses")
    net_profit         = s("NetProfit")

    return {
        "Gross Revenue":       gross_revenue,
        "Refunds":             refund_cost,    # dollar impact (negative)
        "Amazon Fees":         amazon_fees,    # negative
        "Net Payout":          net_payout,
        "COGS":                cogs,           # negative
        "Gross Profit":        gross_profit,
        "Operating Expenses":  expenses,
        "Net Profit":          net_profit,
    }


@st.cache_data(ttl=60)
def load_recon_data() -> dict:
    """Load saved QuickBooks + accountant numbers from the reconciliation sheet."""
    ws   = get_spreadsheet().worksheet(RECON_SHEET)
    data = ws.get_all_records()
    result = {}
    for row in data:
        metric = str(row.get("Metric", "")).strip()
        if not metric:
            continue
        try:
            qb   = float(str(row.get("QuickBooks",       "") or "").replace(",", "") or 0)
        except (ValueError, TypeError):
            qb = 0.0
        try:
            acct = float(str(row.get("Accountant Final", "") or "").replace(",", "") or 0)
        except (ValueError, TypeError):
            acct = 0.0
        notes = str(row.get("Notes", "") or "")
        result[metric] = {"qb": qb, "acct": acct, "notes": notes}
    return result


# ─── Page ─────────────────────────────────────────────────────────────────────

st.title("🧾 Tax Reconciliation — 2025")
st.caption(
    "Compare what our Finance API calculated against QuickBooks and your accountant's final numbers. "
    "When all three columns match, you can trust this system for 2026."
)

totals = load_2025_totals()
recon  = load_recon_data()

st.divider()

# ─── How to use ───────────────────────────────────────────────────────────────

with st.expander("ℹ️ How to use this page"):
    st.markdown("""
**Step 1 — App column** is auto-calculated from your Sellerboard 2025 export (already loaded).

**Step 2 — QuickBooks column**: Once your bookkeeper finalizes 2025, enter each figure below.

**Step 3 — Accountant Final**: After your accountant signs off, enter their final numbers.

**Variance** shows the dollar difference between the App and each other source.
If variance = $0, the numbers match perfectly.

> **Note on signs:** Fees, Refunds, and COGS are shown as negative (money out).
> Net Payout and Gross Revenue are positive (money in).
    """)

# ─── Comparison table ─────────────────────────────────────────────────────────

st.markdown('<div style="font-size:0.72rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:#2d6a9f;margin-bottom:0.5rem;">2025 Annual Comparison</div>', unsafe_allow_html=True)

rows = []
for metric in METRICS:
    app_val  = totals.get(metric, 0.0)
    qb_val   = recon.get(metric, {}).get("qb", 0.0)
    acct_val = recon.get(metric, {}).get("acct", 0.0)
    notes    = recon.get(metric, {}).get("notes", "")

    qb_var   = round(app_val - qb_val, 2)   if qb_val   != 0 else None
    acct_var = round(app_val - acct_val, 2) if acct_val != 0 else None

    rows.append({
        "Metric":           metric,
        "App (Sellerboard)":  app_val,
        "QuickBooks":       qb_val   if qb_val   != 0 else "",
        "QB Variance":      qb_var   if qb_var   is not None else "",
        "Accountant Final": acct_val if acct_val != 0 else "",
        "Acct Variance":    acct_var if acct_var is not None else "",
        "Notes":            notes,
    })

display_df = pd.DataFrame(rows)

def fmt(val):
    if val == "" or val is None:
        return "—"
    try:
        v = float(val)
        return f"${v:,.2f}"
    except (ValueError, TypeError):
        return str(val)

def variance_color(val):
    if val == "" or val is None:
        return ""
    try:
        v = float(val)
        if abs(v) < 0.01:
            return "color: #4caf50"  # green = match
        elif abs(v) < 100:
            return "color: #ff9800"  # orange = small diff
        else:
            return "color: #f44336"  # red = big diff
    except (ValueError, TypeError):
        return ""

# Format for display
disp = display_df.copy()
for col in ["App (Sellerboard)", "QuickBooks", "Accountant Final"]:
    disp[col] = disp[col].apply(fmt)

# Show variance with colour styling
st.dataframe(
    display_df.assign(**{
        "App (Sellerboard)": display_df["App (Sellerboard)"].apply(fmt),
        "QuickBooks":        display_df["QuickBooks"].apply(fmt),
        "QB Variance":       display_df["QB Variance"].apply(fmt),
        "Accountant Final":  display_df["Accountant Final"].apply(fmt),
        "Acct Variance":     display_df["Acct Variance"].apply(fmt),
    }),
    use_container_width=True,
    hide_index=True,
    column_config={
        "Metric":            st.column_config.TextColumn("Metric",            width="medium"),
        "App (Sellerboard)": st.column_config.TextColumn("App (Sellerboard)", width="medium"),
        "QuickBooks":        st.column_config.TextColumn("QuickBooks",        width="medium"),
        "QB Variance":       st.column_config.TextColumn("QB Variance ±",     width="small"),
        "Accountant Final":  st.column_config.TextColumn("Accountant Final",  width="medium"),
        "Acct Variance":     st.column_config.TextColumn("Acct Variance ±",   width="small"),
        "Notes":             st.column_config.TextColumn("Notes",             width="large"),
    },
)

st.divider()

# ─── Monthly breakdown (read-only) ────────────────────────────────────────────

with st.expander("📅 Monthly breakdown (2025)"):
    if totals:
        ws   = get_spreadsheet().worksheet("📊 Amazon 2025")
        data = ws.get_all_records()
        if data:
            mdf = pd.DataFrame(data)
            show = ["DateFrom", "SalesOrganic", "SalesPPC", "Refunds",
                    "AmazonFees", "EstimatedPayout", "Cost of Goods",
                    "GrossProfit", "Expenses", "NetProfit"]
            show = [c for c in show if c in mdf.columns]
            mdf  = mdf[show].rename(columns={
                "DateFrom":       "Month",
                "SalesOrganic":   "Sales (Organic)",
                "SalesPPC":       "Sales (PPC)",
                "AmazonFees":     "Amazon Fees",
                "EstimatedPayout":"Est. Payout",
                "Cost of Goods":  "COGS",
                "GrossProfit":    "Gross Profit",
                "NetProfit":      "Net Profit",
            })
            st.dataframe(mdf, use_container_width=True, hide_index=True)

st.divider()

# ─── Enter QuickBooks / Accountant numbers ────────────────────────────────────

st.markdown('<div style="font-size:0.72rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:#2d6a9f;margin-bottom:0.5rem;">Enter QuickBooks & Accountant Numbers</div>', unsafe_allow_html=True)
st.caption("Fill these in when you have your bookkeeper's QuickBooks totals or accountant's final numbers. Saves to Google Sheets.")

with st.form("recon_form"):
    st.markdown("**Enter dollar amounts — use negatives for fees/costs (e.g. -8,269 for Amazon Fees)**")

    col_a, col_b = st.columns(2)

    qb_inputs   = {}
    acct_inputs = {}
    note_inputs = {}

    for i, metric in enumerate(METRICS):
        existing = recon.get(metric, {})
        col = col_a if i % 2 == 0 else col_b
        with col:
            st.markdown(f"**{metric}**")
            sub1, sub2, sub3 = st.columns([2, 2, 3])
            qb_inputs[metric]   = sub1.number_input("QuickBooks",       value=float(existing.get("qb",   0)), key=f"qb_{metric}",   label_visibility="collapsed", format="%.2f")
            acct_inputs[metric] = sub2.number_input("Accountant Final", value=float(existing.get("acct", 0)), key=f"ac_{metric}",   label_visibility="collapsed", format="%.2f")
            note_inputs[metric] = sub3.text_input(  "Notes",            value=str(existing.get("notes", "")), key=f"nt_{metric}",   label_visibility="collapsed", placeholder="Notes")

    if st.form_submit_button("💾 Save Numbers", type="primary"):
        ws = get_spreadsheet().worksheet(RECON_SHEET)
        # Build update rows (skip header, rows 2-9)
        update_data = []
        for metric in METRICS:
            update_data.append([
                metric,
                qb_inputs[metric],
                acct_inputs[metric],
                note_inputs[metric],
            ])
        ws.update("A2", update_data)
        st.success("Saved! Refresh the page to see updated variances.")
        st.cache_data.clear()
        st.rerun()
