"""
Monthly Expenses
Manage business expenses for any month — add, edit, delete, recurring series.
Adding an expense automatically applies the updated total to Amazon 2026 P&L.
"""

import re
import streamlit as st
import pandas as pd
import calendar
from datetime import date, datetime
from zoneinfo import ZoneInfo
from utils.sheets import get_spreadsheet
from utils.auth import require_auth

st.set_page_config(
    page_title="Monthly Expenses",
    page_icon="💰",
    layout="centered",
)

require_auth("business")

TIMEZONE = ZoneInfo("America/Edmonton")

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
    "Loan Repayment — BDC",
    "Loan Repayment — Tesla",
    "Other Business Expense",
]

PAYMENT_METHODS = [
    "Amex Platinum",
    "Amex Bonvoy",
    "TD Visa",
    "Capital One Mastercard",
    "CIBC Costco Mastercard",
    "Canadian Tire Mastercard",
    "TD Debit",
    "Cash",
    "E-Transfer",
    "Other",
]

ZERO_GST = {
    "Inventory — Books (Pallets)",
    "Bank Fees",
    "Insurance",
    "Amazon PPC / Advertising",
    "Loan Repayment — BDC",
    "Loan Repayment — Tesla",
}

# Canadian tax rates — label → decimal rate
TAX_RATES = {
    "No tax — 0%":                    0.00,
    "GST 5% (AB / NT / NU / YT)":    0.05,
    "GST+PST 11% (SK)":              0.11,
    "GST+PST 12% (BC / MB)":         0.12,
    "HST 13% (ON)":                   0.13,
    "HST 15% (NB / NS / PE / NL)":   0.15,
    "GST+QST ~15% (QC)":             0.14975,
}
_TAX_KEYS    = list(TAX_RATES.keys())
_RATE_ZERO   = "No tax — 0%"
_RATE_DEFAULT = "GST 5% (AB / NT / NU / YT)"   # Alberta default


def _guess_rate(pretax: float, gst: float) -> str:
    """Reverse-lookup closest tax rate label from an existing gst/pretax ratio."""
    if pretax == 0 or gst == 0:
        return _RATE_ZERO
    ratio = gst / pretax
    best_key, best_diff = _RATE_ZERO, 1.0
    for k, r in TAX_RATES.items():
        if abs(r - ratio) < best_diff:
            best_key, best_diff = k, abs(r - ratio)
    return best_key if best_diff < 0.01 else _RATE_DEFAULT


def _parse_split(method: str) -> tuple[bool, str, str]:
    """Return (is_split, method1, method2) from a stored 'M1 + M2' string."""
    if " + " in method:
        parts = method.split(" + ", 1)
        return True, parts[0].strip(), parts[1].strip()
    return False, method, PAYMENT_METHODS[0]


# Business-use allocation
_BUS_OPTS = ["Business — 100%", "Mixed — set %", "Personal — 0%"]

def _pct_to_bus_opt(pct: int) -> str:
    if pct >= 100: return "Business — 100%"
    if pct <= 0:   return "Personal — 0%"
    return "Mixed — set %"

def _parse_bus_tag(raw_notes: str) -> tuple[int, str]:
    """Return (bus_pct, clean_notes) from a note that may contain [bus:N]."""
    m = re.search(r'\[bus:(\d+)\]', raw_notes)
    pct = int(m.group(1)) if m else 100
    clean = re.sub(r'\s*\[bus:\d+\]\s*', '', raw_notes).strip()
    return pct, clean

def _apply_bus_tag(bus_pct: int, notes: str) -> str:
    """Prepend [bus:N] to notes if bus_pct != 100; strip existing tag first."""
    _, clean = _parse_bus_tag(notes)
    if bus_pct == 100:
        return clean
    return f"[bus:{bus_pct}] {clean}".strip()

# Amazon 2026 column indices (0-based in the raw row list)
_COL_DATE     = 0   # A — dd/mm/yyyy
_COL_SALES    = 1   # B — SalesOrganic
_COL_PAYOUT   = 23  # X — EstimatedPayout
_COL_GROSS    = 25  # Z — GrossProfit
_COL_EXPENSES = 26  # AA
_COL_NET      = 27  # AB — NetProfit
_COL_MARGIN   = 28  # AC — Margin


# ─── Session state ────────────────────────────────────────────────────────────

for _k, _v in [("editing_expense", None), ("delete_target", None), ("ae_key", 0)]:
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ─── Data loaders ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_bt_all() -> list[dict]:
    """
    Load ALL Business Transactions rows.

    Sheet layout:
      Row 1 — Title banner (ignored)
      Row 2 — Instructions note (ignored)
      Row 3 — Column headers  ← all_vals[2]
      Row 4+ — Data rows      ← all_vals[3:]  (sheet row 4 = _sheet_row 4)
    """
    try:
        ws       = get_spreadsheet().worksheet("📒 Business Transactions")
        all_vals = ws.get_all_values()
    except Exception as e:
        st.error(f"Could not load Business Transactions sheet: {e}")
        return []

    # Need at least title + instructions + header rows
    if len(all_vals) < 3:
        return []

    header = all_vals[2]   # Row 3 = column headers
    rows   = []

    # Data starts at all_vals[3] = sheet row 4
    for i, raw in enumerate(all_vals[3:], start=4):
        if not any(raw):
            continue

        padded = raw + [""] * max(0, len(header) - len(raw))
        d = dict(zip(header, padded))
        d["_sheet_row"] = i

        def _f(key: str) -> float:
            try:
                return float(str(d.get(key, 0)).replace(",", "").replace("$", "") or 0)
            except (ValueError, TypeError):
                return 0.0

        d["_pretax"] = _f("Pre-Tax ($)")
        d["_gst"]    = _f("GST ($)")

        # Parse business-use % from Notes (encoded as [bus:N])
        _bus_pct, _notes_clean = _parse_bus_tag(d.get("Notes", ""))
        d["_bus_pct"]     = _bus_pct
        d["_notes_clean"] = _notes_clean

        # Derive month key from Date string directly (YYYY-MM-DD → YYYY-MM)
        date_str = str(d.get("Date", "")).strip()
        d["_month_key"] = date_str[:7] if len(date_str) >= 7 else ""

        if not d["_month_key"]:
            continue

        rows.append(d)

    return rows


@st.cache_data(ttl=120)
def load_amazon_months() -> dict[str, list[dict]]:
    """Load Amazon 2026 grouped by YYYY-MM."""
    try:
        ws       = get_spreadsheet().worksheet("📊 Amazon 2026")
        all_vals = ws.get_all_values()
    except Exception as e:
        st.error(f"Could not load Amazon 2026 sheet: {e}")
        return {}

    if len(all_vals) < 2:
        return {}

    def _sf(v) -> float:
        try:
            return float(str(v).replace(",", "").replace("$", "") or 0)
        except (ValueError, TypeError):
            return 0.0

    months: dict[str, list[dict]] = {}
    for i, row in enumerate(all_vals[1:], start=2):
        date_str = row[_COL_DATE].strip() if len(row) > _COL_DATE else ""
        if not date_str:
            continue
        try:
            dt = pd.to_datetime(date_str, format="%d/%m/%Y")
            mk = dt.strftime("%Y-%m")
        except Exception:
            continue

        months.setdefault(mk, []).append({
            "row_num":      i,
            "date":         dt,
            "SalesOrganic": _sf(row[_COL_SALES]   if len(row) > _COL_SALES   else 0),
            "Payout":       _sf(row[_COL_PAYOUT]  if len(row) > _COL_PAYOUT  else 0),
            "GrossProfit":  _sf(row[_COL_GROSS]   if len(row) > _COL_GROSS   else 0),
        })

    return months


# ─── Write helpers ────────────────────────────────────────────────────────────

def _bt_ws():
    return get_spreadsheet().worksheet("📒 Business Transactions")


def _find_next_bt_row(ws, n: int = 1) -> int:
    """
    Return the first empty row number in column A after the header rows (3).
    Pass n>1 to get the row for the nth entry (e.g. n=3 returns the 3rd available row).
    """
    col_a = ws.col_values(1)  # 1-indexed column A
    # Rows 1-3 are title/instructions/header; data starts at row 4
    empty_found = 0
    for i, val in enumerate(col_a[3:], start=4):
        if not str(val).strip():
            empty_found += 1
            if empty_found == n:
                return i
    # All rows filled — append at end
    return len(col_a) + (n - empty_found)


def do_add_expense(exp_date: str, vendor: str, category: str,
                   pretax: float, gst: float, method: str,
                   hubdoc: str, notes: str, freq: str, month_key: str) -> int:
    """
    Add expense row(s). freq is one of:
      'one-time'  — single entry only
      'monthly'   — entry for selected month + all remaining months of 2026
      'annual'    — full yearly amount divided by 12; one entry per month Jan–Dec 2026
    Returns count of rows added.
    """
    ws = _bt_ws()
    try:
        base = datetime.strptime(exp_date, "%Y-%m-%d").date()
    except ValueError:
        base = date.today()

    def _row(d: str, pt: float, gt: float) -> dict:
        return {"date": d, "vendor": vendor, "category": category,
                "pretax": pt, "gst": gt, "method": method,
                "hubdoc": hubdoc, "notes": notes}

    rows: list[dict] = []

    if freq == "annual":
        # Divide yearly amount evenly across all 12 months of 2026
        monthly_pretax = round(pretax / 12, 2)
        monthly_gst    = round(gst / 12, 2)
        for m in range(1, 13):
            last_day = calendar.monthrange(2026, m)[1]
            day = min(base.day, last_day)
            rows.append(_row(f"2026-{m:02d}-{day:02d}", monthly_pretax, monthly_gst))
    elif freq == "monthly":
        # Current month + all remaining months of 2026
        rows.append(_row(exp_date, pretax, gst))
        cur_month = int(month_key.split("-")[1])
        for m in range(cur_month + 1, 13):
            last_day = calendar.monthrange(2026, m)[1]
            day = min(base.day, last_day)
            rows.append(_row(f"2026-{m:02d}-{day:02d}", pretax, gst))
    else:  # one-time
        rows.append(_row(exp_date, pretax, gst))

    # Find starting row (one API call), then batch-write all rows at once
    start_row = _find_next_bt_row(ws)
    batch = []
    for idx, r in enumerate(rows):
        row_num = start_row + idx
        batch.extend([
            {"range": f"A{row_num}:E{row_num}",
             "values": [[r["date"], r["vendor"], r["category"], r["pretax"], r["gst"]]]},
            {"range": f"G{row_num}:I{row_num}",
             "values": [[r["method"], r["hubdoc"], r["notes"]]]},
        ])
    ws.batch_update(batch, value_input_option="USER_ENTERED")
    return len(rows)


def do_update_expense(sheet_row: int, exp_date: str, vendor: str, category: str,
                      pretax: float, gst: float, method: str, hubdoc: str, notes: str):
    ws = _bt_ws()
    ws.batch_update([
        {"range": f"A{sheet_row}", "values": [[exp_date]]},
        {"range": f"B{sheet_row}", "values": [[vendor]]},
        {"range": f"C{sheet_row}", "values": [[category]]},
        {"range": f"D{sheet_row}", "values": [[pretax]]},
        {"range": f"E{sheet_row}", "values": [[gst]]},
        {"range": f"G{sheet_row}", "values": [[method]]},
        {"range": f"H{sheet_row}", "values": [[hubdoc]]},
        {"range": f"I{sheet_row}", "values": [[notes]]},
    ], value_input_option="USER_ENTERED")


def do_delete_rows(row_indices: list[int]):
    """Delete sheet rows bottom-to-top to avoid index drift."""
    ws = _bt_ws()
    for idx in sorted(row_indices, reverse=True):
        ws.delete_rows(idx)


def apply_to_amazon(month_total: float, amz_rows: list[dict]) -> tuple[int, int]:
    """
    Distribute monthly expense total evenly across all Amazon 2026 days.
    Returns (days_updated, gross_fixes).
    """
    num_days = len(amz_rows)
    if num_days == 0 or month_total <= 0:
        return 0, 0

    daily_exp   = round(month_total / num_days, 2)
    batch       = []
    gross_fixes = 0

    for entry in amz_rows:
        gross = entry["GrossProfit"]
        orig_gross = gross
        if gross == 0 and entry["Payout"] > 0:   # auto-fix book days
            gross = entry["Payout"]
            gross_fixes += 1

        net    = round(gross - daily_exp, 2)
        sales  = entry["SalesOrganic"]
        margin = round((net / sales) * 100, 1) if sales > 0 else 0.0
        r      = entry["row_num"]

        batch.extend([
            {"range": f"AA{r}", "values": [[daily_exp]]},
            {"range": f"AB{r}", "values": [[net]]},
            {"range": f"AC{r}", "values": [[margin]]},
        ])
        if orig_gross == 0 and entry["Payout"] > 0:
            batch.append({"range": f"Z{r}", "values": [[round(entry["Payout"], 2)]]})

    if batch:
        ws = get_spreadsheet().worksheet("📊 Amazon 2026")
        ws.batch_update(batch, value_input_option="USER_ENTERED")

    return num_days, gross_fixes


# ─── Page ─────────────────────────────────────────────────────────────────────

st.title("💰 Monthly Expenses")

if st.button("🔄 Refresh"):
    st.cache_data.clear()
    st.rerun()

months_data = load_amazon_months()
available   = sorted(months_data.keys(), reverse=True) if months_data else []

if not available:
    st.warning("No data in Amazon 2026 sheet yet.")
    st.stop()

selected = st.selectbox("Month", available, key="month_sel")

# Load all data needed for both sections
all_bt         = load_bt_all()
month_expenses = [r for r in all_bt if r["_month_key"] == selected]
amz_rows       = months_data.get(selected, [])
# month_logged = full pre-tax logged; month_total = business portion only (used for P&L)
month_logged = round(sum(r["_pretax"] for r in month_expenses), 2)
month_total  = round(sum(r["_pretax"] * r.get("_bus_pct", 100) / 100 for r in month_expenses), 2)

st.divider()

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1 — MANAGE EXPENSES
# ─────────────────────────────────────────────────────────────────────────────

st.subheader("📋 Expenses")

# ── Add expense ───────────────────────────────────────────────────────────────

# Key suffix — incremented on submit so all field widgets get fresh keys (clears form)
_k = st.session_state["ae_key"]

with st.expander("➕ Add Expense"):
    c1, c2 = st.columns(2)
    new_date   = c1.date_input("Date", value=date.today(), key=f"ae_date_{_k}")
    new_vendor = c2.text_input("Vendor / Description",
                               placeholder="e.g. Goodwill Edmonton",
                               key=f"ae_vendor_{_k}")

    new_cat = st.selectbox("Category", CATEGORIES, key=f"ae_cat_{_k}")

    c3, c4, c5 = st.columns(3)
    new_pretax = c3.number_input("Pre-Tax ($)", min_value=0.0,
                                  value=None, placeholder="e.g. 28.00",
                                  step=1.0, format="%.2f", key=f"ae_pretax_{_k}")
    pretax_for_calc = float(new_pretax) if new_pretax is not None else 0.0

    _rate_default = _RATE_ZERO if new_cat in ZERO_GST else _RATE_DEFAULT
    tax_rate_sel = st.selectbox(
        "Tax Rate",
        options=_TAX_KEYS,
        index=_TAX_KEYS.index(st.session_state.get(f"ae_tax_{_k}", _rate_default)),
        key=f"ae_tax_{_k}",
        help="GST-only: AB, NT, NU, YT (5%)  ·  GST+PST: SK 11%, BC/MB 12%  ·  "
             "HST: ON 13%, NB/NS/PE/NL 15%  ·  GST+QST: QC ~15%  ·  "
             "No tax: foreign vendors, books, bank fees, insurance",
    )
    computed_gst = round(pretax_for_calc * TAX_RATES[tax_rate_sel], 2)
    st.session_state[f"ae_gst_{_k}"] = computed_gst
    new_gst = c4.number_input("Tax ($)", min_value=0.0,
                               step=0.01, format="%.2f", key=f"ae_gst_{_k}")
    gst_for_calc = computed_gst
    c5.metric("Total", f"${pretax_for_calc + gst_for_calc:.2f}")

    new_hubdoc = st.selectbox("Receipt in Hubdoc?", ["N", "Y"], key=f"ae_hubdoc_{_k}")
    new_notes  = st.text_input("Notes (optional)", key=f"ae_notes_{_k}")

    # Business use allocation
    ae_bus_type = st.radio(
        "Business Use",
        _BUS_OPTS,
        horizontal=True,
        key=f"ae_bus_{_k}",
        help="Business — 100%: fully deductible.  "
             "Mixed: enter the % used for business (e.g. 33% for home office power).  "
             "Personal — 0%: tracked here but excluded from Amazon P&L.",
    )
    if ae_bus_type == "Mixed — set %":
        ae_bus_pct = st.number_input(
            "Business % (e.g. 33 for one-third)",
            min_value=1, max_value=99, value=33, step=1,
            key=f"ae_buspct_{_k}",
        )
        if pretax_for_calc > 0:
            _biz_amt = pretax_for_calc * ae_bus_pct / 100
            st.caption(f"Business portion: **${_biz_amt:.2f}** of ${pretax_for_calc:.2f}")
    elif ae_bus_type == "Personal — 0%":
        ae_bus_pct = 0
        st.caption("This expense will be tracked but **not** applied to Amazon P&L.")
    else:
        ae_bus_pct = 100

    split_pay = st.checkbox("Split payment — paid with two methods", key=f"ae_split_{_k}")
    if split_pay:
        sa1, sb1, sa2, sb2 = st.columns([2.5, 1.2, 2.5, 1.2])
        split_m1 = sa1.selectbox("Method 1", PAYMENT_METHODS, key=f"ae_sm1_{_k}")
        split_a1 = sb1.number_input("$", min_value=0.0, step=1.0, format="%.2f",
                                     value=None, placeholder="0.00", key=f"ae_sa1_{_k}")
        split_m2 = sa2.selectbox("Method 2", PAYMENT_METHODS, key=f"ae_sm2_{_k}",
                                  index=min(1, len(PAYMENT_METHODS) - 1))
        split_a2 = sb2.number_input("$", min_value=0.0, step=1.0, format="%.2f",
                                     value=None, placeholder="0.00", key=f"ae_sa2_{_k}")
    else:
        new_method = st.selectbox("Payment Method", PAYMENT_METHODS, key=f"ae_method_{_k}")

    # Frequency selector — updates live as pretax changes (no form wrapper)
    if pretax_for_calc > 0:
        _mo_note = f"  —  ${pretax_for_calc:.2f}/mo  (${pretax_for_calc * 12:.2f}/yr)"
        _yr_note = f"  —  ${pretax_for_calc:.2f}/yr  (${round(pretax_for_calc / 12, 2):.2f}/mo)"
    else:
        _mo_note = _yr_note = ""
    _freq_labels = [
        "One-time",
        f"Monthly (rest of 2026){_mo_note}",
        f"Annual (÷12, all 12 months){_yr_note}",
    ]
    new_freq_idx = st.radio(
        "Frequency",
        options=range(3),
        format_func=lambda i: _freq_labels[i],
        help="One-time: single entry.  Monthly: adds for every remaining month of 2026.  "
             "Annual: divides yearly total by 12 and adds one entry per month Jan–Dec 2026.",
        key=f"ae_freq_{_k}",
    )

    if st.button("✅ Add Expense", type="primary",
                 use_container_width=True, key=f"ae_btn_{_k}"):
        if not new_vendor:
            st.error("Enter a vendor / description.")
        elif not new_pretax or new_pretax == 0:
            st.error("Pre-Tax amount cannot be $0.")
        else:
            freq = ["one-time", "monthly", "annual"][new_freq_idx]
            if split_pay:
                _sa1 = float(split_a1) if split_a1 else 0.0
                _sa2 = float(split_a2) if split_a2 else 0.0
                _final_method = f"{split_m1} + {split_m2}"
                _split_note   = f"Split: {split_m1} ${_sa1:.2f} / {split_m2} ${_sa2:.2f}"
                _base_notes   = f"{_split_note} | {new_notes}" if new_notes else _split_note
            else:
                _final_method = new_method
                _base_notes   = new_notes
            _final_notes = _apply_bus_tag(ae_bus_pct, _base_notes)
            count = do_add_expense(
                new_date.strftime("%Y-%m-%d"), new_vendor, new_cat,
                float(new_pretax), computed_gst,
                _final_method, new_hubdoc, _final_notes,
                freq, selected,
            )

            # Auto-apply updated total to Amazon 2026 (business portion only)
            days, fixes, apply_err = 0, 0, None
            try:
                biz_pretax = float(new_pretax) * ae_bus_pct / 100
                if freq == "annual":
                    month_contribution = round(biz_pretax / 12, 2)
                else:
                    month_contribution = round(biz_pretax, 2)
                new_total = month_total + month_contribution
                days, fixes = apply_to_amazon(new_total, amz_rows)
            except Exception as _e:
                apply_err = str(_e)

            st.cache_data.clear()
            st.session_state["ae_key"] += 1  # increment to clear all form fields
            if apply_err:
                st.warning(f"Expense saved, but could not update Amazon 2026: {apply_err}")
            st.rerun()

# ── Expense table with inline actions ─────────────────────────────────────────

if not month_expenses:
    st.info("No expenses logged for this month — use the form above to add some.")
else:
    _caption = f"{len(month_expenses)} expense(s)  ·  Total logged: **${month_logged:,.2f}**"
    if month_total != month_logged:
        _caption += f"  ·  Business portion: **${month_total:,.2f}**"
    else:
        _caption += f"  (pre-tax)"
    st.caption(_caption)

    # Header row
    hcols = st.columns([1.3, 2.8, 2.5, 1.0, 1.0, 0.4, 0.4])
    for col, label in zip(hcols, ["Date", "Vendor", "Category", "Pre-Tax", "Total", "", ""]):
        col.markdown(f"**{label}**")

    st.divider()

    for r in month_expenses:
        row_id  = r["_sheet_row"]
        bus_pct = r.get("_bus_pct", 100)
        # Category badge for non-100% rows
        cat_display = r.get("Category", "")
        if bus_pct == 0:
            cat_display += " 👤"
        elif bus_pct < 100:
            cat_display += f" 🏠{bus_pct}%"

        cols = st.columns([1.3, 2.8, 2.5, 1.0, 1.0, 0.4, 0.4])
        cols[0].write(r.get("Date", ""))
        cols[1].write(r.get("Vendor / Description", ""))
        cols[2].write(cat_display)
        cols[3].write(f"${r['_pretax']:.2f}")
        cols[4].write(f"${r['_pretax'] + r['_gst']:.2f}")
        if cols[5].button("✏️", key=f"edit_btn_{row_id}", help="Edit this expense"):
            st.session_state.editing_expense = r
            st.session_state.delete_target   = None
            st.rerun()
        if cols[6].button("🗑️", key=f"del_btn_{row_id}", help="Delete this expense"):
            st.session_state.delete_target   = {"expense": r}
            st.session_state.editing_expense = None
            st.rerun()

    # ── Delete confirmation ───────────────────────────────────────────────────

    if st.session_state.delete_target is not None:
        e        = st.session_state.delete_target["expense"]
        vendor   = e.get("Vendor / Description", "")
        cat      = e.get("Category", "")
        sel_date = e.get("Date", "")

        st.divider()
        st.warning(
            f"🗑️  **{vendor}** · {cat} · ${e['_pretax']:.2f} ({sel_date})\n\n"
            "How many entries do you want to delete?"
        )
        d1, d2, d3, d4 = st.columns(4)

        if d1.button("This one", type="primary", use_container_width=True):
            do_delete_rows([e["_sheet_row"]])
            st.session_state.delete_target = None
            st.cache_data.clear()
            st.rerun()

        following_rows = [
            r["_sheet_row"] for r in all_bt
            if r.get("Vendor / Description", "") == vendor
            and r.get("Category", "") == cat
            and r.get("Date", "") >= sel_date
        ]
        if d2.button(f"This + following ({len(following_rows)})",
                     use_container_width=True):
            do_delete_rows(following_rows)
            st.session_state.delete_target = None
            st.cache_data.clear()
            st.rerun()

        all_series_rows = [
            r["_sheet_row"] for r in all_bt
            if r.get("Vendor / Description", "") == vendor
            and r.get("Category", "") == cat
        ]
        if d3.button(f"Entire series ({len(all_series_rows)})",
                     use_container_width=True):
            do_delete_rows(all_series_rows)
            st.session_state.delete_target = None
            st.cache_data.clear()
            st.rerun()

        if d4.button("Cancel", use_container_width=True):
            st.session_state.delete_target = None
            st.rerun()

    # ── Edit form (no form wrapper — enables live GST auto-calc) ─────────────────

    if st.session_state.editing_expense is not None:
        e        = st.session_state.editing_expense
        _erow    = e["_sheet_row"]
        _ikey    = f"_edit_init_{_erow}"

        # Pre-populate fields in session state only on first render of this edit session
        if _ikey not in st.session_state:
            try:
                _edate = datetime.strptime(e.get("Date", ""), "%Y-%m-%d").date()
            except ValueError:
                _edate = date.today()
            st.session_state[f"ed_date_{_erow}"]   = _edate
            st.session_state[f"ed_vendor_{_erow}"] = e.get("Vendor / Description", "")
            st.session_state[f"ed_cat_{_erow}"]    = e.get("Category", CATEGORIES[0])
            st.session_state[f"ed_pretax_{_erow}"] = e["_pretax"]
            st.session_state[f"ed_tax_{_erow}"]   = _guess_rate(e["_pretax"], e["_gst"])
            _is_split, _em1, _em2 = _parse_split(e.get("Payment Method", ""))
            st.session_state[f"ed_split_{_erow}"] = _is_split
            st.session_state[f"ed_method_{_erow}"] = _em1 if not _is_split else PAYMENT_METHODS[0]
            st.session_state[f"ed_sm1_{_erow}"]   = _em1 if _em1 in PAYMENT_METHODS else PAYMENT_METHODS[0]
            st.session_state[f"ed_sm2_{_erow}"]   = _em2 if _em2 in PAYMENT_METHODS else PAYMENT_METHODS[0]
            st.session_state[f"ed_hubdoc_{_erow}"] = e.get("Hubdoc (Y/N)", "N")
            st.session_state[f"ed_notes_{_erow}"]  = e.get("_notes_clean", e.get("Notes", ""))
            _init_bus_pct = e.get("_bus_pct", 100)
            st.session_state[f"ed_bus_{_erow}"]    = _pct_to_bus_opt(_init_bus_pct)
            st.session_state[f"ed_buspct_{_erow}"] = _init_bus_pct if 0 < _init_bus_pct < 100 else 33
            st.session_state[_ikey] = True

        st.divider()
        st.markdown("**✏️ Edit Expense**")

        c1, c2 = st.columns(2)
        ed_date   = c1.date_input("Date",                    key=f"ed_date_{_erow}")
        ed_vendor = c2.text_input("Vendor / Description",    key=f"ed_vendor_{_erow}")
        ed_cat    = st.selectbox("Category", CATEGORIES,     key=f"ed_cat_{_erow}")

        c3, c4 = st.columns(2)
        ed_pretax = c3.number_input("Pre-Tax ($)", min_value=0.0, step=1.0, format="%.2f",
                                     key=f"ed_pretax_{_erow}")
        ed_tax_sel = st.selectbox(
            "Tax Rate",
            options=_TAX_KEYS,
            key=f"ed_tax_{_erow}",
            help="GST-only: AB, NT, NU, YT (5%)  ·  GST+PST: SK 11%, BC/MB 12%  ·  "
                 "HST: ON 13%, NB/NS/PE/NL 15%  ·  GST+QST: QC ~15%  ·  "
                 "No tax: foreign vendors, books, bank fees, insurance",
        )
        _ed_pretax_val = float(ed_pretax) if ed_pretax else 0.0
        _ed_computed_gst = round(_ed_pretax_val * TAX_RATES[ed_tax_sel], 2)
        st.session_state[f"ed_gst_{_erow}"] = _ed_computed_gst
        ed_gst = c4.number_input("Tax ($)", min_value=0.0, step=0.01, format="%.2f",
                                  key=f"ed_gst_{_erow}")

        ed_split = st.checkbox("Split payment — paid with two methods",
                               key=f"ed_split_{_erow}")
        if ed_split:
            es1, es2 = st.columns(2)
            ed_m1     = es1.selectbox("Method 1", PAYMENT_METHODS, key=f"ed_sm1_{_erow}")
            ed_m2     = es2.selectbox("Method 2", PAYMENT_METHODS, key=f"ed_sm2_{_erow}")
            ed_method = f"{ed_m1} + {ed_m2}"
            ed_hubdoc = st.selectbox("Receipt in Hubdoc?", ["N", "Y"], key=f"ed_hubdoc_{_erow}")
        else:
            ec1, ec2  = st.columns(2)
            ed_method = ec1.selectbox("Payment Method", PAYMENT_METHODS, key=f"ed_method_{_erow}")
            ed_hubdoc = ec2.selectbox("Receipt in Hubdoc?", ["N", "Y"], key=f"ed_hubdoc_{_erow}")
        ed_notes  = st.text_input("Notes",                           key=f"ed_notes_{_erow}")

        ed_bus_type = st.radio(
            "Business Use",
            _BUS_OPTS,
            horizontal=True,
            key=f"ed_bus_{_erow}",
            help="Business — 100%: fully deductible.  "
                 "Mixed: enter the % used for business.  "
                 "Personal — 0%: tracked but excluded from Amazon P&L.",
        )
        if ed_bus_type == "Mixed — set %":
            ed_bus_pct = st.number_input(
                "Business %",
                min_value=1, max_value=99, step=1,
                key=f"ed_buspct_{_erow}",
            )
            if _ed_pretax_val > 0:
                st.caption(f"Business portion: **${_ed_pretax_val * ed_bus_pct / 100:.2f}** of ${_ed_pretax_val:.2f}")
        elif ed_bus_type == "Personal — 0%":
            ed_bus_pct = 0
        else:
            ed_bus_pct = 100

        s1, s2 = st.columns(2)
        if s1.button("💾 Save Changes", type="primary", key=f"ed_save_{_erow}"):
            _ed_final_notes = _apply_bus_tag(ed_bus_pct, ed_notes)
            do_update_expense(
                _erow, ed_date.strftime("%Y-%m-%d"),
                ed_vendor, ed_cat, _ed_pretax_val, _ed_computed_gst,
                ed_method, ed_hubdoc, _ed_final_notes,
            )
            st.session_state.editing_expense = None
            st.session_state.pop(_ikey, None)
            st.cache_data.clear()
            st.rerun()
        if s2.button("Cancel", key=f"ed_cancel_{_erow}"):
            st.session_state.editing_expense = None
            st.session_state.pop(_ikey, None)
            st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2 — AMAZON 2026 P&L PREVIEW + MANUAL RE-APPLY
# ─────────────────────────────────────────────────────────────────────────────

st.divider()
st.subheader("📊 Amazon 2026 P&L")

num_days  = len(amz_rows)
daily_exp = round(month_total / num_days, 2) if num_days else 0.0

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Logged", f"${month_logged:,.2f}")
c2.metric("Business Portion", f"${month_total:,.2f}",
          delta=f"-${month_logged - month_total:.2f} personal" if month_logged != month_total else None,
          delta_color="off")
c3.metric("Amazon days", num_days)
c4.metric("Daily share", f"${daily_exp:.2f}" if num_days else "$0.00")

if month_total == 0:
    st.info("No expenses logged yet — add some above and they'll apply automatically.")

if amz_rows:
    preview_rows: list[dict] = []
    gross_fixes = 0

    for entry in sorted(amz_rows, key=lambda x: x["date"]):
        gross = entry["GrossProfit"]
        if gross == 0 and entry["Payout"] > 0:
            gross = entry["Payout"]
            gross_fixes += 1

        net    = round(gross - daily_exp, 2)
        sales  = entry["SalesOrganic"]
        margin = round((net / sales) * 100, 1) if sales > 0 else 0.0

        preview_rows.append({
            "Date":         entry["date"].strftime("%b %d"),
            "Gross Profit": f"${gross:.2f}",
            "Daily Exp":    f"${daily_exp:.2f}",
            "Net Profit":   f"${net:.2f}",
            "Margin %":     f"{margin:.1f}%",
        })

    st.dataframe(
        pd.DataFrame(preview_rows),
        use_container_width=True,
        hide_index=True,
    )

    if gross_fixes:
        st.caption(
            f"⚠️  {gross_fixes} day(s) with GrossProfit = $0 will be auto-fixed "
            "to EstimatedPayout (books have $0 COGS)."
        )

    st.caption(
        "Expenses are applied automatically when you add one above. "
        "Use the button below if you need to re-apply after an edit or delete."
    )

    if month_total == 0:
        st.button("↩️ Re-apply to Amazon 2026", disabled=True,
                  help="Add expenses above first.")
    else:
        if st.button("↩️ Re-apply to Amazon 2026", use_container_width=True):
            days, fixes = apply_to_amazon(month_total, amz_rows)
            st.success(
                f"Updated {days} day(s) in Amazon 2026 for {selected}."
                + (f" Fixed GrossProfit for {fixes} day(s)." if fixes else "")
            )
            st.cache_data.clear()
            st.rerun()
