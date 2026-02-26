"""
GST Summary
Annual ITC tracker and CRA filing prep — pulled live from GST Annual Summary sheet.
"""

import streamlit as st
import pandas as pd
from utils.sheets import get_spreadsheet
from utils.auth import require_auth

st.set_page_config(
    page_title="GST Summary",
    page_icon="🇨🇦",
    layout="centered",
)

require_auth("business")


@st.cache_data(ttl=300)
def load_gst_data() -> dict:
    ws = get_spreadsheet().worksheet("🇨🇦 GST Annual Summary")
    data = ws.get_all_values()

    result = {
        "amazon_sales":   0.0,
        "amazon_gst":     0.0,
        "itcs_by_cat":    {},
        "total_itcs":     0.0,
        "cra_101":        0.0,
        "cra_103":        0.0,
        "cra_106":        0.0,
        "cra_109":        0.0,
    }

    for row in data:
        label = row[0].strip() if row else ""
        val_str = row[1].strip() if len(row) > 1 else ""
        try:
            val = float(str(val_str).replace(",", "").replace("$", "") or 0)
        except ValueError:
            val = 0.0

        if "Total Amazon Sales" in label:
            result["amazon_sales"] = val
        elif "GST Collected via Amazon" in label:
            result["amazon_gst"] = val
        elif "TOTAL ITCs" in label:
            result["total_itcs"] = val
        elif label == "101":
            result["cra_101"] = val
        elif label == "103":
            result["cra_103"] = val
        elif label == "106":
            result["cra_106"] = val
        elif label == "109":
            result["cra_109"] = val
        elif label in {
            "Inventory — Books (Pallets)", "Inventory — Other",
            "Amazon PPC / Advertising", "Bank Fees",
            "Software & Subscriptions", "Shipping & Packaging",
            "Professional Fees", "Vehicle & Travel", "Office Supplies",
            "Phone & Internet", "Insurance", "Other Business Expense",
        }:
            result["itcs_by_cat"][label] = val

    return result


# ─── Page ─────────────────────────────────────────────────────────────────────

st.title("🇨🇦 GST Annual Summary — 2026")
st.caption("Alberta 5% GST · Annual filer · Amazon is marketplace facilitator")

if st.button("🔄 Refresh"):
    st.cache_data.clear()
    st.rerun()

gst = load_gst_data()

# ─── Amazon income ────────────────────────────────────────────────────────────
st.subheader("Amazon Sales")
c1, c2 = st.columns(2)
c1.metric("Total Amazon Sales (YTD)", f"${gst['amazon_sales']:,.2f}")
c2.metric("GST Collected via Amazon", f"${gst['amazon_gst']:,.2f}",
          help="Amazon remits this directly to CRA — not your liability")

st.caption(
    "📌 Amazon is a marketplace facilitator. They collect and remit GST on your behalf. "
    "Confirm with your accountant whether to report this on Line 103 or enter $0."
)

st.divider()

# ─── ITCs ─────────────────────────────────────────────────────────────────────
st.subheader("Input Tax Credits (GST Paid on Expenses)")
st.caption("These are ITCs you can claim back from CRA on your annual return.")

if gst["itcs_by_cat"]:
    itc_df = pd.DataFrame(
        list(gst["itcs_by_cat"].items()),
        columns=["Category", "GST Paid ($)"]
    )
    itc_df = itc_df[itc_df["GST Paid ($)"] != 0].sort_values(
        "GST Paid ($)", ascending=False
    )
    if not itc_df.empty:
        st.dataframe(itc_df, use_container_width=True, hide_index=True)
        st.metric("**Total ITCs (Line 106)**", f"${gst['total_itcs']:,.2f}")
    else:
        st.info("No expenses with GST recorded yet.")
else:
    st.info("No expenses recorded yet. Log expenses using the Log Expense page.")

st.divider()

# ─── CRA filing prep ──────────────────────────────────────────────────────────
st.subheader("CRA Annual Filing Prep")

net = gst["cra_109"]
net_label = "You OWE CRA" if net > 0 else "CRA OWES YOU (refund)"
net_color = "inverse" if net > 0 else "normal"

c1, c2 = st.columns(2)
c1.metric("Line 101 — Total Sales",         f"${gst['cra_101']:,.2f}")
c1.metric("Line 103 — GST Collected",       f"${gst['cra_103']:,.2f}")
c2.metric("Line 106 — ITCs",                f"${gst['cra_106']:,.2f}")
c2.metric("Line 109 — Net Tax",             f"${abs(net):,.2f}",
          delta=net_label, delta_color=net_color)

st.divider()
st.warning(
    "**Before filing:** Confirm with your accountant whether Line 103 should show "
    "the Amazon-remitted GST amount or $0 (marketplace facilitator rules). "
    "Either way, your ITC claim on Line 106 stands."
)
