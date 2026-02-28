"""
Net Worth
Live balance sheet — enter current account balances to see P&L + net worth snapshot.
Compare against QuickBooks to verify accuracy.
"""

import streamlit as st
import pandas as pd
from datetime import date
from utils.sheets import get_spreadsheet
from utils.auth import require_auth

st.set_page_config(
    page_title="Net Worth",
    page_icon="💰",
    layout="wide",
)

require_auth("business")

SHEET_NAME = "📊 Net Worth"

# Row positions in the sheet (1-based)
ROW_LAST_UPDATED = 2
ROW_BANK         = 3
ROW_AMAZON_OWED  = 4
ROW_INVENTORY    = 5
ROW_TESLA_LOAN   = 6
ROW_AMEX_PLAT    = 7
ROW_AMEX_BON     = 8
ROW_CAP_ONE      = 9


# ─── Data loaders ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_balances() -> dict:
    try:
        ws   = get_spreadsheet().worksheet(SHEET_NAME)
        vals = ws.col_values(2)   # column B

        def _f(idx):
            try:
                return float(str(vals[idx - 1]).replace(",", "").replace("$", "") or 0)
            except Exception:
                return 0.0

        return {
            "last_updated": vals[ROW_LAST_UPDATED - 1] if len(vals) >= ROW_LAST_UPDATED else "",
            "bank":         _f(ROW_BANK),
            "amazon_owed":  _f(ROW_AMAZON_OWED),
            "inventory":    _f(ROW_INVENTORY),
            "tesla_loan":   _f(ROW_TESLA_LOAN),
            "amex_plat":    _f(ROW_AMEX_PLAT),
            "amex_bon":     _f(ROW_AMEX_BON),
            "cap_one":      _f(ROW_CAP_ONE),
        }
    except Exception:
        return {
            "last_updated": "", "bank": 0.0, "amazon_owed": 0.0,
            "inventory": 0.0, "tesla_loan": 0.0,
            "amex_plat": 0.0, "amex_bon": 0.0, "cap_one": 0.0,
        }


@st.cache_data(ttl=120)
def load_ytd_revenue() -> float:
    try:
        ws    = get_spreadsheet().worksheet("📊 Amazon 2026")
        vals  = ws.get_all_values()
        total = 0.0
        for row in vals[1:]:
            if row and len(row) > 1 and row[1]:
                try:
                    total += float(str(row[1]).replace(",", ""))
                except ValueError:
                    pass
        return round(total, 2)
    except Exception:
        return 0.0


@st.cache_data(ttl=120)
def load_ytd_expenses() -> tuple[float, dict]:
    """Returns (total, {category: amount}) from Business Transactions (col F = Total)."""
    try:
        ws   = get_spreadsheet().worksheet("📒 Business Transactions")
        rows = ws.get_all_values()
        total  = 0.0
        by_cat: dict[str, float] = {}
        for row in rows[3:]:   # skip title, warning, headers
            if not row or not row[0]:
                continue
            try:
                cat = row[2] if len(row) > 2 else "Uncategorized"
                val = float(str(row[5]).replace(",", "").replace("$", "") or 0) if len(row) > 5 else 0.0
                total += val
                by_cat[cat] = by_cat.get(cat, 0.0) + val
            except (ValueError, IndexError):
                continue
        return round(total, 2), {k: round(v, 2) for k, v in sorted(by_cat.items(), key=lambda x: -x[1])}
    except Exception:
        return 0.0, {}


# ─── Page ─────────────────────────────────────────────────────────────────────

st.title("💰 Net Worth")

if st.button("🔄 Refresh"):
    st.cache_data.clear()
    st.rerun()

bal              = load_balances()
revenue          = load_ytd_revenue()
total_exp, cats  = load_ytd_expenses()
net_profit       = round(revenue - total_exp, 2)

total_assets = round(bal["bank"] + bal["amazon_owed"] + bal["inventory"], 2)
total_liab   = round(bal["tesla_loan"] + bal["amex_plat"] + bal["amex_bon"] + bal["cap_one"], 2)
net_worth    = round(total_assets - total_liab, 2)


# ─── P&L Summary ──────────────────────────────────────────────────────────────

st.markdown('<div class="section-label">P&L — 2026 Year to Date</div>', unsafe_allow_html=True)

c1, c2, c3 = st.columns(3)
c1.metric("YTD Revenue",  f"${revenue:,.2f}")
c2.metric("YTD Expenses", f"${total_exp:,.2f}")
c3.metric("Net Profit",   f"${net_profit:,.2f}",
          delta="profitable" if net_profit >= 0 else "in the hole",
          delta_color="normal" if net_profit >= 0 else "inverse")

with st.expander("Expense breakdown by category"):
    if cats:
        cat_df = pd.DataFrame([
            {"Category": k, "Total ($)": f"${v:,.2f}"}
            for k, v in cats.items()
        ])
        st.dataframe(cat_df, use_container_width=True, hide_index=True)
    else:
        st.info("No expense data found.")

st.caption("Revenue = Amazon 2026 organic sales. Expenses = all rows in Business Transactions ledger.")

st.divider()


# ─── Balance Sheet ────────────────────────────────────────────────────────────

st.markdown('<div class="section-label">Balance Sheet — Current Snapshot</div>', unsafe_allow_html=True)

if bal["last_updated"]:
    st.caption(f"Balances last updated: **{bal['last_updated']}**  ·  Edit below to update")
else:
    st.info("No balances entered yet — fill in the form below.")

col_a, col_l, col_s = st.columns(3)

with col_a:
    st.markdown("**Assets**")
    st.metric("TD Bank Balance",       f"${bal['bank']:,.2f}")
    st.metric("Amazon Pending Payout", f"${bal['amazon_owed']:,.2f}")
    st.metric("FBA Inventory Value",   f"${bal['inventory']:,.2f}")
    st.divider()
    st.metric("Total Assets",          f"${total_assets:,.2f}")

with col_l:
    st.markdown("**Liabilities**")
    st.metric("Tesla Loan",            f"${bal['tesla_loan']:,.2f}")
    st.metric("Amex Platinum",         f"${bal['amex_plat']:,.2f}")
    st.metric("Amex Bonvoy",           f"${bal['amex_bon']:,.2f}")
    st.metric("Capital One Visa",      f"${bal['cap_one']:,.2f}")
    st.divider()
    st.metric("Total Liabilities",     f"${total_liab:,.2f}")

with col_s:
    st.markdown("**Net Position**")
    st.metric("Total Assets",      f"${total_assets:,.2f}")
    st.metric("Total Liabilities", f"${total_liab:,.2f}")
    st.divider()
    st.metric("Net Worth",         f"${net_worth:,.2f}",
              delta="positive" if net_worth >= 0 else "negative",
              delta_color="normal" if net_worth >= 0 else "inverse")
    st.metric("YTD Net Profit",    f"${net_profit:,.2f}",
              delta_color="normal" if net_profit >= 0 else "inverse")

st.divider()


# ─── Update balances form ─────────────────────────────────────────────────────

st.markdown('<div class="section-label">Update Current Balances</div>', unsafe_allow_html=True)
st.caption("Enter values as of today. Saves to the 📊 Net Worth sheet.")

with st.form("balances_form", clear_on_submit=False):
    col_fa, col_fl = st.columns(2)

    with col_fa:
        st.markdown("**Assets**")
        f_bank       = st.number_input("TD Bank Balance ($)",       min_value=0.0, step=100.0, value=bal["bank"],        format="%.2f")
        f_amz_owed   = st.number_input("Amazon Pending Payout ($)", min_value=0.0, step=100.0, value=bal["amazon_owed"], format="%.2f")
        f_inventory  = st.number_input("FBA Inventory Value ($)",   min_value=0.0, step=100.0, value=bal["inventory"],   format="%.2f")

    with col_fl:
        st.markdown("**Liabilities**")
        f_tesla  = st.number_input("Tesla Loan Balance ($)",    min_value=0.0, step=100.0, value=bal["tesla_loan"], format="%.2f")
        f_amex_p = st.number_input("Amex Platinum Balance ($)", min_value=0.0, step=100.0, value=bal["amex_plat"],  format="%.2f")
        f_amex_b = st.number_input("Amex Bonvoy Balance ($)",   min_value=0.0, step=100.0, value=bal["amex_bon"],   format="%.2f")
        f_cap    = st.number_input("Capital One Visa ($)",      min_value=0.0, step=100.0, value=bal["cap_one"],    format="%.2f")

    if st.form_submit_button("💾 Save Balances", type="primary"):
        ws        = get_spreadsheet().worksheet(SHEET_NAME)
        today_str = date.today().strftime("%Y-%m-%d")
        ws.batch_update([
            {"range": f"B{ROW_LAST_UPDATED}", "values": [[today_str]]},
            {"range": f"B{ROW_BANK}",         "values": [[f_bank]]},
            {"range": f"B{ROW_AMAZON_OWED}",  "values": [[f_amz_owed]]},
            {"range": f"B{ROW_INVENTORY}",    "values": [[f_inventory]]},
            {"range": f"B{ROW_TESLA_LOAN}",   "values": [[f_tesla]]},
            {"range": f"B{ROW_AMEX_PLAT}",    "values": [[f_amex_p]]},
            {"range": f"B{ROW_AMEX_BON}",     "values": [[f_amex_b]]},
            {"range": f"B{ROW_CAP_ONE}",      "values": [[f_cap]]},
        ])
        st.success(f"Balances saved as of {today_str}")
        st.cache_data.clear()
        st.rerun()
