"""
Log Expense
Quick form to record a business expense into the Business Transactions sheet.
GST auto-calculates at 5% — override if different.
"""

import streamlit as st
from datetime import date
from utils.sheets import get_spreadsheet
from utils.auth import require_auth

st.set_page_config(
    page_title="Log Expense",
    page_icon="🧾",
    layout="centered",
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

ZERO_GST_CATEGORIES = {
    "Inventory — Books (Pallets)",  # Books are zero-rated
    "Bank Fees",                    # Financial services — no GST
    "Insurance",                    # Insurance — no GST
    "Amazon PPC / Advertising",     # Amazon invoices in USD, no CA GST
}


def log_expense(expense_date: str, vendor: str, category: str,
                pretax: float, gst: float, method: str,
                hubdoc: str, notes: str) -> None:
    ws = get_spreadsheet().worksheet("📒 Business Transactions")
    # Find the first empty row in column A after the 3 header rows
    # (append_row is not used because reference list columns confuse the
    #  Sheets API table-detection, causing data to land in the wrong columns)
    col_a = ws.col_values(1)
    next_row = len(col_a) + 1
    for i, val in enumerate(col_a[3:], start=4):
        if not str(val).strip():
            next_row = i
            break
    # Write cols A-E (Date, Vendor, Category, PreTax, GST) and G-I (Method, Hubdoc, Notes)
    # Cols F (Total) and J (Month-Key) are auto-calculated by ARRAYFORMULA in the sheet
    ws.batch_update([
        {"range": f"A{next_row}:E{next_row}",
         "values": [[expense_date, vendor, category, pretax, gst]]},
        {"range": f"G{next_row}:I{next_row}",
         "values": [[method, hubdoc, notes]]},
    ], value_input_option="USER_ENTERED")


# ─── Page ─────────────────────────────────────────────────────────────────────

st.title("🧾 Log Expense")
st.caption("Entries go directly into the Business Transactions sheet.")

with st.form("expense_form"):
    c1, c2 = st.columns([1, 2])
    expense_date = c1.date_input("Date", value=date.today())
    vendor       = c2.text_input("Vendor / Description",
                                 placeholder="e.g. Goodwill Edmonton, Canada Post")

    category = st.selectbox("Category", CATEGORIES)

    c1, c2, c3 = st.columns(3)
    pretax = c1.number_input("Pre-Tax Amount ($)", min_value=0.0,
                              value=0.0, step=0.01, format="%.2f")

    no_gst = st.checkbox(
        "No GST on this invoice (foreign / zero-rated)",
        value=category in ZERO_GST_CATEGORIES,
        help="Check for foreign vendors (Sellerboard, US suppliers, Amazon PPC) "
             "and zero-rated items (books, insurance, bank fees).",
    )

    default_gst = 0.0 if (no_gst or category in ZERO_GST_CATEGORIES) else round(pretax * 0.05, 2)
    gst = c2.number_input(
        "GST ($)",
        min_value=0.0,
        value=default_gst,
        step=0.01,
        format="%.2f",
        help="Auto-set to $0 when 'No GST' is checked. Override manually if needed.",
    )
    total_display = pretax + gst
    c3.metric("Total", f"${total_display:.2f}")

    c1, c2 = st.columns(2)
    method = c1.selectbox("Payment Method", PAYMENT_METHODS)
    hubdoc = c2.selectbox("Receipt in Hubdoc?", ["Y", "N"])

    notes = st.text_input("Notes (optional)")

    submitted = st.form_submit_button(
        "✅ Save Expense", type="primary", use_container_width=True
    )

if submitted:
    if not vendor:
        st.error("Please enter a vendor / description.")
    elif pretax == 0:
        st.error("Pre-Tax amount can't be zero.")
    else:
        # Enforce $0 GST if the checkbox was ticked
        final_gst = 0.0 if (no_gst or category in ZERO_GST_CATEGORIES) else float(gst)
        final_total = pretax + final_gst
        log_expense(
            expense_date.strftime("%Y-%m-%d"),
            vendor,
            category,
            pretax,
            final_gst,
            method,
            hubdoc,
            notes,
        )
        st.success(
            f"Saved: **{vendor}** · {category} · "
            f"${pretax:.2f} + ${final_gst:.2f} GST = **${final_total:.2f}**"
        )
