"""
Reconciliation — Amazon payout register, CC/bank statement matching, AR aging.
"""

import io
import streamlit as st
import pandas as pd
from datetime import date, datetime
from utils.sheets import get_spreadsheet
from utils.auth import require_auth

st.set_page_config(page_title="Reconciliation", page_icon="🔍", layout="wide")
require_auth("business")

# ── Constants ──────────────────────────────────────────────────────────────────

PAYOUT_SHEET   = "💰 Payout Register"
STATEMENT_SHEET = "🏦 Statement Lines"

PAYOUT_HEADERS = [
    "Date Received", "Period Label", "Amount Expected ($)",
    "Amount Received ($)", "Difference ($)", "Account", "Status", "Notes",
]
STATEMENT_HEADERS = [
    "Date", "Description", "Amount ($)", "Account", "Matched", "Notes",
]

ACCOUNTS     = ["Amex Platinum", "RBC Chequing", "Other"]
MONTHS       = [f"2026-{m:02d}" for m in range(1, 13)]
MONTH_LABELS = {
    "2026-01": "Jan", "2026-02": "Feb", "2026-03": "Mar",
    "2026-04": "Apr", "2026-05": "May", "2026-06": "Jun",
    "2026-07": "Jul", "2026-08": "Aug", "2026-09": "Sep",
    "2026-10": "Oct", "2026-11": "Nov", "2026-12": "Dec",
}
today_mk    = date.today().strftime("%Y-%m")
past_months = [m for m in MONTHS if m <= today_mk]


# ── Data loaders ───────────────────────────────────────────────────────────────

def _ws(title, headers):
    ss = get_spreadsheet()
    try:
        return ss.worksheet(title)
    except Exception:
        ws = ss.add_worksheet(title=title, rows=500, cols=len(headers))
        ws.append_row(headers)
        return ws


@st.cache_data(ttl=30)
def load_payouts() -> list[dict]:
    try:
        data = _ws(PAYOUT_SHEET, PAYOUT_HEADERS).get_all_records()
    except Exception:
        return []
    rows = []
    for i, r in enumerate(data, start=2):
        if not any(str(v).strip() for v in r.values()):
            continue
        def _f(k):
            try:
                return float(str(r.get(k, 0)).replace(",", "").replace("$", "") or 0)
            except (ValueError, TypeError):
                return 0.0
        r["_expected"] = _f("Amount Expected ($)")
        r["_received"] = _f("Amount Received ($)")
        r["_diff"]     = _f("Difference ($)")
        r["_row"]      = i
        r["_date"]     = str(r.get("Date Received", "")).strip()
        rows.append(r)
    return rows


@st.cache_data(ttl=30)
def load_statement_lines() -> list[dict]:
    try:
        data = _ws(STATEMENT_SHEET, STATEMENT_HEADERS).get_all_records()
    except Exception:
        return []
    rows = []
    for i, r in enumerate(data, start=2):
        if not any(str(v).strip() for v in r.values()):
            continue
        try:
            r["_amount"] = float(str(r.get("Amount ($)", 0)).replace(",", "").replace("$", "") or 0)
        except (ValueError, TypeError):
            r["_amount"] = 0.0
        r["_row"]       = i
        r["_month_key"] = str(r.get("Date", ""))[:7]
        rows.append(r)
    return rows


@st.cache_data(ttl=30)
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
        d["_row"] = i
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


# ── Page ───────────────────────────────────────────────────────────────────────

st.title("🔍 Reconciliation")

hc1, hc2 = st.columns([6, 1])
with hc2:
    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

st.divider()

payouts    = load_payouts()
stmt_lines = load_statement_lines()
txns       = load_transactions()

tab_payouts, tab_recon, tab_ar = st.tabs([
    "💰 Amazon Payouts", "🔍 Statement Reconciliation", "📊 AR Aging"
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — AMAZON PAYOUT REGISTER
# ══════════════════════════════════════════════════════════════════════════════

with tab_payouts:
    st.subheader("💰 Amazon Payout Register")
    st.caption(
        "Amazon pays out every ~14 days. Log each deposit and compare expected vs. actual. "
        "Differences over $1.00 are flagged as discrepancies."
    )

    # ── YTD metrics ───────────────────────────────────────────────────────────
    total_expected = sum(p["_expected"] for p in payouts)
    total_received = sum(p["_received"] for p in payouts)
    outstanding_ar = total_expected - total_received
    discrepancies  = [p for p in payouts if p.get("Status") == "Discrepancy"]

    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("Expected YTD",   f"${total_expected:,.0f}",
               help="Sum of all expected payouts logged.")
    mc2.metric("Received YTD",   f"${total_received:,.0f}",
               help="Sum of all actual deposits confirmed.")
    mc3.metric("Outstanding AR", f"${outstanding_ar:,.0f}",
               delta_color="inverse" if outstanding_ar > 500 else "normal",
               help="Expected minus received — money Amazon owes you.")
    mc4.metric("Discrepancies",  len(discrepancies),
               delta_color="inverse" if discrepancies else "normal",
               help="Payouts where received differs from expected by more than $1.00.")

    st.divider()

    # ── Log a payout ──────────────────────────────────────────────────────────
    with st.expander("➕ Log a payout received", expanded=not payouts):
        with st.form("add_payout_form", clear_on_submit=True):
            fc1, fc2 = st.columns(2)
            with fc1:
                p_period   = st.text_input("Period label (e.g. Feb 1–14, 2026)")
                p_expected = st.number_input("Amount Expected ($)", min_value=0.0, step=0.01,
                                             help="From Amazon Seller Central → Payments")
                p_account  = st.selectbox("Deposited to", ACCOUNTS, key="payout_account")
            with fc2:
                p_date     = st.date_input("Date deposit received", value=date.today())
                p_received = st.number_input("Amount Actually Received ($)", min_value=0.0, step=0.01)
                p_notes    = st.text_input("Notes", key="payout_notes")

            if st.form_submit_button("Save Payout", type="primary", use_container_width=True):
                if not p_period:
                    st.error("Period label is required.")
                else:
                    diff   = round(p_received - p_expected, 2)
                    status = (
                        "Pending"      if p_received == 0 else
                        "Matched"      if abs(diff) <= 1.00 else
                        "Discrepancy"
                    )
                    try:
                        _ws(PAYOUT_SHEET, PAYOUT_HEADERS).append_row([
                            p_date.isoformat(), p_period,
                            round(p_expected, 2), round(p_received, 2),
                            diff, p_account, status, p_notes,
                        ])
                        st.cache_data.clear()
                        st.success(f"Saved — status: **{status}**")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to save: {e}")

    # ── Payout table ──────────────────────────────────────────────────────────
    if payouts:
        st.markdown("**All Payouts**")
        display = []
        for p in sorted(payouts, key=lambda x: x["_date"], reverse=True):
            status = p.get("Status", "")
            flag   = "🔴" if status == "Discrepancy" else ("🟡" if status == "Pending" else "✅")
            display.append({
                "Date Received":  p.get("Date Received", ""),
                "Period":         p.get("Period Label", ""),
                "Expected ($)":   f"${p['_expected']:,.2f}",
                "Received ($)":   f"${p['_received']:,.2f}",
                "Difference":     f"${p['_diff']:+.2f}",
                "Account":        p.get("Account", ""),
                "Status":         f"{flag} {status}",
                "Notes":          p.get("Notes", ""),
            })
        st.dataframe(pd.DataFrame(display), hide_index=True, use_container_width=True)
        if discrepancies:
            st.warning(
                f"⚠️ {len(discrepancies)} payout(s) have a discrepancy > $1.00. "
                "Check Amazon Seller Central → Payments for the detailed breakdown."
            )
    else:
        st.info("No payouts logged yet. Add your first one above.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — STATEMENT RECONCILIATION
# ══════════════════════════════════════════════════════════════════════════════

with tab_recon:
    st.subheader("🔍 CC / Bank Statement Reconciliation")
    st.caption(
        "Enter line items from your Amex or bank statement, then compare against "
        "what's logged in Business Transactions. Spot missing entries or duplicates instantly."
    )

    # ── Add statement line ────────────────────────────────────────────────────
    with st.expander("➕ Add a statement line", expanded=False):
        with st.form("add_stmt_form", clear_on_submit=True):
            sc1, sc2 = st.columns(2)
            with sc1:
                s_date    = st.date_input("Date (on statement)", value=date.today())
                s_desc    = st.text_input("Description (as shown on statement)")
                s_amount  = st.number_input("Amount ($)", min_value=0.0, step=0.01,
                                            help="Positive = charge/debit")
            with sc2:
                s_account = st.selectbox("Account", ACCOUNTS, key="stmt_acct")
                s_matched = st.selectbox("Matched to logged expense?", ["No", "Yes", "N/A"],
                                         help="Mark Yes once you find the matching entry in Business Transactions.")
                s_notes   = st.text_input("Notes", key="stmt_notes_2")

            if st.form_submit_button("Add Line", type="primary", use_container_width=True):
                if not s_desc:
                    st.error("Description is required.")
                else:
                    try:
                        _ws(STATEMENT_SHEET, STATEMENT_HEADERS).append_row([
                            s_date.isoformat(), s_desc, round(s_amount, 2),
                            s_account, s_matched, s_notes,
                        ])
                        st.cache_data.clear()
                        st.success("Statement line added.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to save: {e}")

    st.divider()

    # ── Reconciliation filters ────────────────────────────────────────────────
    rf1, rf2 = st.columns(2)
    with rf1:
        recon_month = st.selectbox(
            "Month", list(reversed(past_months)),
            format_func=lambda m: f"{MONTH_LABELS.get(m, m)} 2026",
            key="recon_month",
        )
    with rf2:
        recon_account = st.selectbox("Account", ACCOUNTS, key="recon_account")

    # Statement lines for this month + account
    mo_stmt = [s for s in stmt_lines
               if s.get("_month_key") == recon_month
               and s.get("Account") == recon_account]

    # Transactions for this month + matching payment method
    pm_map  = {"Amex Platinum": "amex", "RBC Chequing": "cheq", "Other": "other"}
    pm_key  = pm_map.get(recon_account, "")
    mo_txns = [t for t in txns
               if t.get("_month_key") == recon_month
               and pm_key in str(t.get("Payment Method", "")).lower()]

    stmt_total = round(sum(s["_amount"] for s in mo_stmt), 2)
    txn_total  = round(sum(t["_total"]  for t in mo_txns), 2)
    diff       = round(stmt_total - txn_total, 2)

    # ── Summary metrics ───────────────────────────────────────────────────────
    rm1, rm2, rm3, rm4 = st.columns(4)
    rm1.metric("Statement Total",  f"${stmt_total:,.2f}",
               help="Total of statement lines entered for this month/account.")
    rm2.metric("Logged Expenses",  f"${txn_total:,.2f}",
               help="Total from Business Transactions for this month/payment method.")
    rm3.metric("Difference",       f"${diff:+.2f}",
               delta_color="inverse" if abs(diff) > 1 else "normal",
               help="Statement − Logged. Near zero = reconciled. Positive = charges not logged. Negative = logged but not on statement.")
    rm4.metric("Statement Lines",  len(mo_stmt))

    if not mo_stmt and not mo_txns:
        st.info("No statement lines or expenses for this selection. Add statement lines above, or select a different month/account.")
    elif abs(diff) <= 1.00:
        st.success("✅ Reconciled — statement and logged expenses match within $1.00.")
    elif diff > 0:
        st.warning(f"⚠️ Statement is **${diff:,.2f} MORE** than logged — you likely have unrecorded expenses.")
    else:
        st.warning(f"⚠️ Logged expenses are **${abs(diff):,.2f} MORE** than statement — check for duplicates.")

    st.divider()

    # ── Side-by-side view ─────────────────────────────────────────────────────
    left, right = st.columns(2)

    with left:
        st.markdown(f"**📄 Statement — {MONTH_LABELS.get(recon_month, recon_month)} ({recon_account})**")
        if mo_stmt:
            df_stmt = pd.DataFrame([{
                "Date":        s.get("Date", ""),
                "Description": s.get("Description", ""),
                "Amount ($)":  f"${s['_amount']:.2f}",
                "Matched":     s.get("Matched", "No"),
                "Notes":       s.get("Notes", ""),
            } for s in sorted(mo_stmt, key=lambda x: x.get("Date", ""))])
            st.dataframe(df_stmt, hide_index=True, use_container_width=True)
            unmatched = [s for s in mo_stmt if s.get("Matched", "No").strip().lower() == "no"]
            if unmatched:
                st.caption(f"⚠️ {len(unmatched)} line(s) not yet matched to an expense.")
        else:
            st.info("No statement lines yet.")

    with right:
        st.markdown(f"**📒 Logged — {MONTH_LABELS.get(recon_month, recon_month)} ({recon_account})**")
        if mo_txns:
            df_txns = pd.DataFrame([{
                "Date":      t.get("Date", ""),
                "Vendor":    t.get("Vendor / Description", ""),
                "Total ($)": f"${t['_total']:.2f}",
                "Category":  t.get("Category", ""),
                "Receipt":   t.get("Hubdoc (Y/N)", "N"),
            } for t in sorted(mo_txns, key=lambda x: x.get("Date", ""))])
            st.dataframe(df_txns, hide_index=True, use_container_width=True)
        else:
            st.info("No expenses logged for this account/month.")

    # ── Download reconciliation report ────────────────────────────────────────
    if mo_stmt or mo_txns:
        st.divider()
        buf = io.StringIO()
        buf.write(f"RECONCILIATION — {MONTH_LABELS.get(recon_month, recon_month)} 2026 — {recon_account}\n")
        buf.write(f"Generated: {date.today().isoformat()}\n\n")
        buf.write(f"Statement Total:  ${stmt_total:,.2f}\n")
        buf.write(f"Logged Total:     ${txn_total:,.2f}\n")
        buf.write(f"Difference:       ${diff:+.2f}\n\n")
        buf.write("--- STATEMENT LINES ---\n")
        if mo_stmt:
            pd.DataFrame([{
                "Date": s.get("Date"), "Description": s.get("Description"),
                "Amount ($)": s["_amount"], "Matched": s.get("Matched"),
            } for s in mo_stmt]).to_csv(buf, index=False)
        buf.write("\n--- LOGGED EXPENSES ---\n")
        if mo_txns:
            pd.DataFrame([{
                "Date": t.get("Date"), "Vendor": t.get("Vendor / Description"),
                "Total ($)": t["_total"], "Category": t.get("Category"),
            } for t in mo_txns]).to_csv(buf, index=False)

        st.download_button(
            "⬇️ Download Reconciliation Report",
            data=buf.getvalue().encode("utf-8"),
            file_name=f"recon_{recon_month}_{recon_account.replace(' ', '_')}.csv",
            mime="text/csv",
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — AR AGING
# ══════════════════════════════════════════════════════════════════════════════

with tab_ar:
    st.subheader("📊 Accounts Receivable — Aging")
    st.caption(
        "Outstanding Amazon payouts — money expected but not yet received, "
        "grouped by how long they've been waiting."
    )

    pending = [p for p in payouts if p.get("Status") in ("Pending", "Discrepancy")]

    if not pending:
        if payouts:
            st.success("✅ No outstanding receivables — all logged payouts have been received.")
        else:
            st.info("No payouts logged yet. Add them in the Amazon Payouts tab.")
    else:
        today = date.today()

        def _age_days(p) -> int:
            raw = p.get("Date Received", "")
            try:
                return (today - date.fromisoformat(str(raw))).days if raw else 30
            except Exception:
                return 30

        buckets = {
            "Current (0–14 days)": [],
            "15–30 days":          [],
            "31–60 days":          [],
            "60+ days":            [],
        }
        for p in pending:
            age = _age_days(p)
            if age <= 14:
                buckets["Current (0–14 days)"].append(p)
            elif age <= 30:
                buckets["15–30 days"].append(p)
            elif age <= 60:
                buckets["31–60 days"].append(p)
            else:
                buckets["60+ days"].append(p)

        ac1, ac2, ac3, ac4 = st.columns(4)
        for col, (label, items) in zip([ac1, ac2, ac3, ac4], buckets.items()):
            total = sum(p["_expected"] - p["_received"] for p in items)
            col.metric(label, f"${total:,.0f}", help=f"{len(items)} payout(s)")

        st.divider()

        ar_rows = []
        for p in sorted(pending, key=lambda x: x["_date"]):
            outstanding = p["_expected"] - p["_received"]
            age         = _age_days(p)
            bucket      = (
                "Current (0–14d)"  if age <= 14 else
                "15–30 days"       if age <= 30 else
                "31–60 days"       if age <= 60 else
                "60+ days ⚠️"
            )
            ar_rows.append({
                "Period":      p.get("Period Label", ""),
                "Expected":    f"${p['_expected']:,.2f}",
                "Received":    f"${p['_received']:,.2f}",
                "Outstanding": f"${outstanding:,.2f}",
                "Age":         f"{age}d",
                "Bucket":      bucket,
                "Account":     p.get("Account", ""),
                "Status":      p.get("Status", ""),
            })

        st.dataframe(pd.DataFrame(ar_rows), hide_index=True, use_container_width=True)

        total_ar = sum(p["_expected"] - p["_received"] for p in pending)
        st.markdown(f"**Total Outstanding AR: ${total_ar:,.2f}**")
        st.caption(
            "💡 Amazon FBA payouts typically clear within 3–5 business days of the period end. "
            "Anything over 14 days warrants checking Seller Central → Payments."
        )
