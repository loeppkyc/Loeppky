"""
Bookkeeping Hub — YTD dashboard, receipt checklist, and accountant export.
Pulls from Business Transactions, Monthly P&L, and GST Annual Summary sheets.
"""

import streamlit as st
import pandas as pd
from datetime import date, datetime
from utils.sheets import get_spreadsheet
from utils.auth import require_auth

st.set_page_config(
    page_title="Bookkeeping Hub",
    page_icon="📒",
    layout="wide",
)

require_auth("business")

CATEGORIES = [
    "Inventory — Books (Pallets)",
    "Inventory — Other",
    "Amazon PPC / Advertising",
    "Bank Fees",
    "Software & Subscriptions",
    "Shipping & Packaging",
    "Professional Fees",
    "Vehicle & Travel",
    "Office Supplies",
    "Phone & Internet",
    "Insurance",
    "Other Business Expense",
]

MONTHS = [f"2026-{m:02d}" for m in range(1, 13)]
MONTH_LABELS = {
    "2026-01": "Jan", "2026-02": "Feb", "2026-03": "Mar",
    "2026-04": "Apr", "2026-05": "May", "2026-06": "Jun",
    "2026-07": "Jul", "2026-08": "Aug", "2026-09": "Sep",
    "2026-10": "Oct", "2026-11": "Nov", "2026-12": "Dec",
}


# ── Data loaders ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_transactions() -> list[dict]:
    try:
        ws       = get_spreadsheet().worksheet("📒 Business Transactions")
        all_vals = ws.get_all_values()
    except Exception:
        return []

    if len(all_vals) < 3:
        return []

    header = all_vals[2]
    rows   = []
    for i, raw in enumerate(all_vals[3:], start=4):
        if not any(raw):
            continue
        padded = raw + [""] * max(0, len(header) - len(raw))
        d = dict(zip(header, padded))
        d["_sheet_row"] = i

        def _f(key):
            try:
                return float(str(d.get(key, 0)).replace(",", "").replace("$", "") or 0)
            except (ValueError, TypeError):
                return 0.0

        d["_pretax"] = _f("Pre-Tax ($)")
        d["_gst"]    = _f("GST ($)")
        d["_total"]  = d["_pretax"] + d["_gst"]

        date_str = str(d.get("Date", "")).strip()
        d["_month_key"] = date_str[:7] if len(date_str) >= 7 else ""
        if not d["_month_key"]:
            continue
        rows.append(d)
    return rows


_MONTH_TO_KEY = {
    "january": "2026-01", "february": "2026-02", "march": "2026-03",
    "april": "2026-04",   "may": "2026-05",      "june": "2026-06",
    "july": "2026-07",    "august": "2026-08",   "september": "2026-09",
    "october": "2026-10", "november": "2026-11", "december": "2026-12",
}


@st.cache_data(ttl=60)
def load_monthly_pl() -> dict:
    """Load Monthly P&L sheet — returns dict keyed by YYYY-MM.
    Uses get_all_values() because row 1 is a title, not the header row.
    Finds the real header by locating the row where col A == 'Month'.
    """
    try:
        ws   = get_spreadsheet().worksheet("📊 Monthly P&L")
        rows = ws.get_all_values()
    except Exception:
        return {}

    # Find the header row
    header = None
    data_rows = []
    for i, row in enumerate(rows):
        if row and str(row[0]).strip().lower() == "month":
            header = row
            data_rows = rows[i + 1:]
            break

    if not header:
        return {}

    result = {}
    for raw in data_rows:
        if not any(raw):
            continue
        padded = raw + [""] * max(0, len(header) - len(raw))
        row = dict(zip(header, padded))
        raw_month = str(row.get("Month", "")).strip()
        mk = _MONTH_TO_KEY.get(raw_month.lower())  # None if not a valid month name
        if not mk:
            continue  # skip header repeats, totals, blank rows
        # Normalize revenue column name for downstream code
        if "Total Revenue" in row and "Amazon Revenue" not in row:
            row["Amazon Revenue"] = row["Total Revenue"]
        result[mk] = row
    return result


# ── Page ───────────────────────────────────────────────────────────────────────

st.title("📒 Bookkeeping Hub")

hc1, hc2 = st.columns([6, 1])
with hc2:
    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

st.divider()

txns   = load_transactions()
pl_data = load_monthly_pl()

tab_dash, tab_receipts, tab_export = st.tabs([
    "📊 Dashboard", "🧾 Receipt Checklist", "📤 Accountant Export"
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

with tab_dash:

    today_mk = date.today().strftime("%Y-%m")
    past_months = [m for m in MONTHS if m <= today_mk]

    # ── YTD totals ────────────────────────────────────────────────────────────
    ytd_pretax = sum(r["_pretax"] for r in txns)
    ytd_gst    = sum(r["_gst"]    for r in txns)
    ytd_total  = ytd_pretax + ytd_gst

    # Revenue from Monthly P&L
    ytd_revenue = sum(
        float(str(row.get("Amazon Revenue", 0)).replace(",", "").replace("$", "") or 0)
        for row in pl_data.values()
    )
    ytd_profit = ytd_revenue - ytd_pretax

    st.subheader("📈 Year-to-Date Summary")
    mc1, mc2, mc3, mc4, mc5 = st.columns(5)
    mc1.metric("Revenue (YTD)",   f"${ytd_revenue:,.0f}")
    mc2.metric("Expenses (YTD)",  f"${ytd_pretax:,.0f}")
    mc3.metric("GST Paid (ITCs)", f"${ytd_gst:,.2f}")
    mc4.metric("Net Profit (YTD)", f"${ytd_profit:,.0f}",
               delta_color="normal" if ytd_profit >= 0 else "inverse")
    mc5.metric("Transactions",    len(txns))

    st.divider()

    # ── Month-by-month table ──────────────────────────────────────────────────
    st.subheader("📅 Month-by-Month Breakdown")

    month_rows = []
    for mk in past_months:
        mo_txns   = [r for r in txns if r["_month_key"] == mk]
        mo_pretax = sum(r["_pretax"] for r in mo_txns)
        mo_gst    = sum(r["_gst"]    for r in mo_txns)
        mo_pl     = pl_data.get(mk, {})
        mo_rev    = float(str(mo_pl.get("Amazon Revenue", 0)).replace(",", "").replace("$", "") or 0)
        mo_profit = mo_rev - mo_pretax
        missing_receipts = sum(1 for r in mo_txns if str(r.get("Hubdoc (Y/N)", "N")).upper() != "Y")

        status = "✅" if mo_txns else "⚠️ No expenses"
        if mo_rev == 0:
            status = "❓ No revenue data"

        month_rows.append({
            "Month":             MONTH_LABELS.get(mk, mk),
            "Revenue":           f"${mo_rev:,.0f}"    if mo_rev    else "—",
            "Expenses":          f"${mo_pretax:,.0f}" if mo_pretax else "—",
            "GST (ITCs)":        f"${mo_gst:.2f}"     if mo_gst    else "—",
            "Net Profit":        f"${mo_profit:,.0f}" if (mo_rev or mo_pretax) else "—",
            "# Transactions":    len(mo_txns)         if mo_txns   else 0,
            "Missing Receipts":  missing_receipts     if mo_txns   else 0,
            "Status":            status,
        })

    st.dataframe(pd.DataFrame(month_rows), hide_index=True, use_container_width=True)

    st.divider()

    # ── Expenses by category ──────────────────────────────────────────────────
    st.subheader("🗂️ Expenses by Category (YTD)")

    cat_totals = {}
    for r in txns:
        cat = r.get("Category", "Other Business Expense")
        cat_totals[cat] = cat_totals.get(cat, 0) + r["_pretax"]

    if cat_totals:
        cat_df = pd.DataFrame([
            {"Category": k, "Amount ($)": round(v, 2), "% of Total": round(v / ytd_pretax * 100, 1) if ytd_pretax else 0}
            for k, v in sorted(cat_totals.items(), key=lambda x: x[1], reverse=True)
        ])
        cc1, cc2 = st.columns([2, 3])
        with cc1:
            st.dataframe(cat_df, hide_index=True, use_container_width=True)
        with cc2:
            st.bar_chart(
                cat_df.set_index("Category")["Amount ($)"],
                y_label="Amount ($)",
                use_container_width=True,
            )
    else:
        st.info("No expenses logged yet.")

    st.divider()

    # ── GST summary ───────────────────────────────────────────────────────────
    st.subheader("🇨🇦 GST Snapshot")

    # Pull YTD COGS from Monthly P&L (negative values — convert to positive)
    def _parse_dollar(v):
        try:
            return abs(float(str(v).replace(",", "").replace("$", "").replace("-", "").strip() or 0))
        except (ValueError, TypeError):
            return 0.0

    ytd_cogs = sum(
        _parse_dollar(row.get("COGS", 0))
        for row in pl_data.values()
    )

    gst_collected_est = ytd_revenue * 0.05  # Amazon collects and remits as marketplace facilitator

    # Inventory ITCs — GST paid on non-book (taxable) inventory purchases
    # Books are zero-rated in Canada. LEGO/other from Canadian retailers = 5% GST.
    sc1, sc2 = st.columns([3, 1])
    with sc1:
        st.caption(
            f"YTD COGS (from Monthly P&L): **${ytd_cogs:,.0f}** — "
            "adjust the slider to reflect what % came from Canadian taxable sources "
            "(e.g. LEGO/other from Costco/Walmart = taxable; books = zero-rated)."
        )
    with sc2:
        taxable_pct = st.slider(
            "Non-book COGS %", 0, 100, 80,
            help="% of COGS from Canadian retailers where you paid 5% GST. "
                 "Books = 0%. LEGO/other = ~100%.",
            key="gst_taxable_pct",
        ) / 100

    cogs_itc = round(ytd_cogs * taxable_pct * 0.05, 2)
    total_itc = ytd_gst + cogs_itc
    gst_net   = total_itc - gst_collected_est  # positive = refund / over-collected

    gc1, gc2, gc3, gc4 = st.columns(4)
    gc1.metric("GST Collected (est.)",
               f"${gst_collected_est:,.2f}",
               help="Estimated — Amazon remits this as marketplace facilitator. Confirm with accountant.")
    gc2.metric("GST on Expenses (ITCs)",
               f"${ytd_gst:,.2f}",
               help="GST you paid on business expenses logged in the Transactions sheet.")
    gc3.metric("GST on Inventory (est.)",
               f"${cogs_itc:,.2f}",
               help=f"Estimated GST on taxable COGS: ${ytd_cogs:,.0f} × {int(taxable_pct*100)}% × 5%. "
                    "Adjust the slider above. Verify purchase receipts with your accountant.")
    gc4.metric("Est. Net GST Owing",
               f"${gst_net:,.2f}",
               delta_color="inverse" if gst_net > 0 else "normal",
               help="Positive = you owe CRA. Negative = you over-paid (likely a refund). Verify with accountant.")

    rule_of_thumb = ytd_revenue * 0.02
    variance      = gst_net - rule_of_thumb
    st.caption(
        f"Total ITCs (expenses + inventory est.): **${total_itc:,.2f}**  ·  "
        f"📌 Accountant's rule of thumb (~2% of revenue): **${rule_of_thumb:,.0f}**  ·  "
        f"Variance from rule: **{'+ ' if variance >= 0 else ''}${variance:,.0f}** "
        f"({'over' if variance >= 0 else 'under'} estimate)  |  "
        "⚠️ Confirm with your accountant whether Amazon's marketplace facilitator role means Line 103 = $0, "
        "and whether inventory ITCs should be based on purchase date vs. sale date."
    )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — RECEIPT CHECKLIST
# ══════════════════════════════════════════════════════════════════════════════

with tab_receipts:
    st.subheader("🧾 Expenses Missing Receipts")
    st.caption("These expenses have Hubdoc = N. Track down receipts or mark them as documented.")

    no_receipt = [
        r for r in txns
        if str(r.get("Hubdoc (Y/N)", "N")).strip().upper() != "Y"
    ]

    if not no_receipt:
        st.success("All expenses have receipts documented. You're good to go!")
    else:
        # Filter by month
        months_with_missing = sorted({r["_month_key"] for r in no_receipt}, reverse=True)
        month_filter = st.selectbox(
            "Filter by month",
            ["All months"] + months_with_missing,
            key="receipt_month_filter",
        )

        filtered = no_receipt if month_filter == "All months" else [
            r for r in no_receipt if r["_month_key"] == month_filter
        ]

        rc1, rc2, rc3 = st.columns(3)
        rc1.metric("Missing Receipts", len(no_receipt))
        rc2.metric("Total Value", f"${sum(r['_total'] for r in no_receipt):,.2f}")
        rc3.metric("Showing", len(filtered))

        st.divider()

        # Display table
        display = []
        for r in sorted(filtered, key=lambda x: x.get("Date", ""), reverse=True):
            display.append({
                "Date":     r.get("Date", ""),
                "Vendor":   r.get("Vendor / Description", ""),
                "Category": r.get("Category", ""),
                "Pre-Tax":  f"${r['_pretax']:.2f}",
                "GST":      f"${r['_gst']:.2f}",
                "Total":    f"${r['_total']:.2f}",
                "Method":   r.get("Payment Method", ""),
                "Notes":    r.get("Notes", ""),
            })
        st.dataframe(pd.DataFrame(display), hide_index=True, use_container_width=True)

        # Mark all as documented button
        st.divider()
        st.caption("Once you've filed receipts in Hubdoc, update them individually in Monthly Expenses, or use the sheet directly.")

        # Download missing receipts list
        csv = pd.DataFrame(display).to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Download missing receipts list",
            data=csv,
            file_name=f"missing_receipts_{date.today().isoformat()}.csv",
            mime="text/csv",
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — ACCOUNTANT EXPORT
# ══════════════════════════════════════════════════════════════════════════════

with tab_export:
    st.subheader("📤 Accountant Export")
    st.info(
        "Download clean reports to share with your accountant. "
        "All amounts in CAD. GST separated from pre-tax amounts."
    )

    if not txns:
        st.warning("No transactions to export yet.")
    else:
        # ── Full transaction ledger ───────────────────────────────────────────
        st.markdown("**Full Transaction Ledger**")
        st.caption("Every expense entry with date, vendor, category, amounts, and payment method.")

        ledger_rows = []
        for r in sorted(txns, key=lambda x: x.get("Date", "")):
            ledger_rows.append({
                "Date":           r.get("Date", ""),
                "Vendor":         r.get("Vendor / Description", ""),
                "Category":       r.get("Category", ""),
                "Pre-Tax ($)":    round(r["_pretax"], 2),
                "GST ($)":        round(r["_gst"], 2),
                "Total ($)":      round(r["_total"], 2),
                "Payment Method": r.get("Payment Method", ""),
                "Receipt":        r.get("Hubdoc (Y/N)", "N"),
                "Notes":          r.get("Notes", ""),
            })

        ledger_df = pd.DataFrame(ledger_rows)
        st.dataframe(ledger_df.head(10), hide_index=True, use_container_width=True)
        st.caption(f"Showing first 10 of {len(ledger_rows)} rows.")

        ledger_csv = ledger_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            f"⬇️ Full Ledger ({len(ledger_rows)} rows)",
            data=ledger_csv,
            file_name=f"transaction_ledger_2026_{date.today().isoformat()}.csv",
            mime="text/csv",
            use_container_width=True,
        )

        st.divider()

        # ── Category summary ──────────────────────────────────────────────────
        st.markdown("**Expense Summary by Category**")
        st.caption("Totals grouped by category — the format most accountants want for Schedule T2125.")

        cat_summary = {}
        for r in txns:
            cat = r.get("Category", "Other")
            if cat not in cat_summary:
                cat_summary[cat] = {"Pre-Tax ($)": 0.0, "GST (ITCs) ($)": 0.0,
                                    "Total ($)": 0.0, "# Transactions": 0}
            cat_summary[cat]["Pre-Tax ($)"]    += r["_pretax"]
            cat_summary[cat]["GST (ITCs) ($)"] += r["_gst"]
            cat_summary[cat]["Total ($)"]       += r["_total"]
            cat_summary[cat]["# Transactions"]  += 1

        cat_rows = [
            {"Category": k, **{kk: round(vv, 2) if isinstance(vv, float) else vv
                                for kk, vv in v.items()}}
            for k, v in sorted(cat_summary.items(), key=lambda x: x[1]["Pre-Tax ($)"], reverse=True)
        ]
        # Totals row
        cat_rows.append({
            "Category":        "TOTAL",
            "Pre-Tax ($)":     round(sum(r["Pre-Tax ($)"] for r in cat_rows), 2),
            "GST (ITCs) ($)":  round(sum(r["GST (ITCs) ($)"] for r in cat_rows), 2),
            "Total ($)":       round(sum(r["Total ($)"] for r in cat_rows), 2),
            "# Transactions":  sum(r["# Transactions"] for r in cat_rows),
        })

        cat_df = pd.DataFrame(cat_rows)
        st.dataframe(cat_df, hide_index=True, use_container_width=True)

        cat_csv = cat_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Category Summary",
            data=cat_csv,
            file_name=f"expense_by_category_2026_{date.today().isoformat()}.csv",
            mime="text/csv",
            use_container_width=True,
        )

        st.divider()

        # ── Monthly P&L summary ───────────────────────────────────────────────
        st.markdown("**Monthly P&L Summary**")
        st.caption("Revenue vs expenses month by month — income statement format.")

        pl_rows = []
        for mk in MONTHS:
            mo_txns   = [r for r in txns if r["_month_key"] == mk]
            mo_pretax = round(sum(r["_pretax"] for r in mo_txns), 2)
            mo_gst    = round(sum(r["_gst"]    for r in mo_txns), 2)
            mo_pl     = pl_data.get(mk, {})
            mo_rev    = round(float(str(mo_pl.get("Amazon Revenue", 0)).replace(",", "").replace("$", "") or 0), 2)
            mo_profit = round(mo_rev - mo_pretax, 2)
            pl_rows.append({
                "Month":          f"{MONTH_LABELS.get(mk, mk)} 2026",
                "Revenue ($)":    mo_rev,
                "Expenses ($)":   mo_pretax,
                "GST Paid ($)":   mo_gst,
                "Net Profit ($)": mo_profit,
            })

        # Totals
        pl_rows.append({
            "Month":          "TOTAL 2026",
            "Revenue ($)":    round(sum(r["Revenue ($)"]    for r in pl_rows), 2),
            "Expenses ($)":   round(sum(r["Expenses ($)"]   for r in pl_rows), 2),
            "GST Paid ($)":   round(sum(r["GST Paid ($)"]   for r in pl_rows), 2),
            "Net Profit ($)": round(sum(r["Net Profit ($)"] for r in pl_rows), 2),
        })

        pl_df = pd.DataFrame(pl_rows)
        st.dataframe(pl_df, hide_index=True, use_container_width=True)

        pl_csv = pl_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Monthly P&L Summary",
            data=pl_csv,
            file_name=f"monthly_pl_2026_{date.today().isoformat()}.csv",
            mime="text/csv",
            use_container_width=True,
        )

        st.divider()

        # ── All-in-one package ────────────────────────────────────────────────
        st.markdown("**All Reports Combined**")
        st.caption("One CSV with all three reports as separate sections — easiest to email to your accountant.")

        import io
        buf = io.StringIO()
        buf.write("LOEPPKY BUSINESS — 2026 BOOKKEEPING REPORT\n")
        buf.write(f"Generated: {date.today().isoformat()}\n\n")
        buf.write("--- MONTHLY P&L SUMMARY ---\n")
        pl_df.to_csv(buf, index=False)
        buf.write("\n--- EXPENSE SUMMARY BY CATEGORY ---\n")
        cat_df.to_csv(buf, index=False)
        buf.write("\n--- FULL TRANSACTION LEDGER ---\n")
        ledger_df.to_csv(buf, index=False)

        st.download_button(
            "⬇️ All Reports Combined (send to accountant)",
            data=buf.getvalue().encode("utf-8"),
            file_name=f"loeppky_bookkeeping_2026_{date.today().isoformat()}.csv",
            mime="text/csv",
            use_container_width=True,
            type="primary",
        )
