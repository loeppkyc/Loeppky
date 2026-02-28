"""
Inventory
View and manage all books in the Book Inventory sheet.
Book investment tracked at the pallet level (not per-book).
"""

import streamlit as st
import pandas as pd
from datetime import date
from utils.sheets import get_spreadsheet
from utils.auth import require_auth

st.set_page_config(
    page_title="Inventory",
    page_icon="📋",
    layout="wide",
)

require_auth("business")

STATUSES = ["All", "Unlisted", "Listed", "Sold"]


# ─── Data loaders ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_sellerboard_snapshot() -> dict:
    """FBA units + potential sales/profit from the manually-updated snapshot."""
    try:
        ws   = get_spreadsheet().worksheet("📊 Sellerboard Snapshot")
        rows = ws.get_all_records()
        if not rows:
            return {}
        latest = rows[-1]
        return {
            "date":       latest.get("Date", ""),
            "units":      int(float(str(latest.get("Units", 0)).replace(",", "") or 0)),
            "pot_sales":  float(str(latest.get("Potential Sales ($)", 0)).replace(",", "") or 0),
            "pot_profit": float(str(latest.get("Potential Profit ($)", 0)).replace(",", "") or 0),
        }
    except Exception:
        return {}


@st.cache_data(ttl=300)
def load_pallet_data() -> dict:
    """
    Read pallet purchase history from '📦 Colin - Pallet Sales'.
    Row 1 = title, Row 2 = headers, Row 3+ = data.
    Columns: Date | #Pallets | Price | Total | Paid | Owed
    Total may be blank — compute as #Pallets × Price when missing.
    """
    try:
        ws   = get_spreadsheet().worksheet("📦 Colin - Pallet Sales")
        rows = ws.get_all_values()
        # row index 0 = title "Book Pallet Sales", index 1 = headers, index 2+ = data
        data_rows = rows[2:] if len(rows) > 2 else []

        total_pallets = 0
        total_cost    = 0.0
        rows_detail   = []

        for row in data_rows:
            if not row or not row[0]:
                continue
            try:
                date_str = str(row[0]).strip()
                n_pal    = int(float(str(row[1]).strip() or 0))
                price    = float(str(row[2]).strip() or 0)
                # Use Total col if present, otherwise calculate
                raw_total = str(row[3]).strip() if len(row) > 3 else ""
                cost = float(raw_total) if raw_total else n_pal * price
                total_pallets += n_pal
                total_cost    += cost
                rows_detail.append({
                    "Period":   date_str,
                    "Pallets":  n_pal,
                    "$/Pallet": price,
                    "Cost":     cost,
                })
            except (ValueError, IndexError):
                continue

        return {
            "total_pallets": total_pallets,
            "total_cost":    round(total_cost, 2),
            "detail":        rows_detail,
        }
    except Exception:
        return {"total_pallets": 0, "total_cost": 0.0, "detail": []}


@st.cache_data(ttl=300)
def load_book_sales_ytd() -> float:
    """Sum SalesOrganic (col B) from the Amazon 2026 sheet — all 2026 sales."""
    try:
        ws   = get_spreadsheet().worksheet("📊 Amazon 2026")
        vals = ws.get_all_values()
        total = 0.0
        for row in vals[1:]:   # skip header
            if row and row[1]:
                try:
                    total += float(str(row[1]).replace(",", ""))
                except ValueError:
                    pass
        return round(total, 2)
    except Exception:
        return 0.0


@st.cache_data(ttl=60)
def load_inventory() -> pd.DataFrame:
    ws   = get_spreadsheet().worksheet("📦 Book Inventory")
    data = ws.get_all_records()
    if not data:
        return pd.DataFrame()
    return pd.DataFrame(data)


# ─── Page ─────────────────────────────────────────────────────────────────────

st.title("📋 Inventory")

# ─── Book Investment Overview ─────────────────────────────────────────────────

pallets   = load_pallet_data()
sales_ytd = load_book_sales_ytd()
snap      = load_sellerboard_snapshot()

net = round(sales_ytd - pallets["total_cost"], 2)

st.markdown('<div class="section-label">Book Business Overview</div>',
            unsafe_allow_html=True)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total Pallets Bought",  f"{pallets['total_pallets']}")
c2.metric("Total Pallet Cost",     f"${pallets['total_cost']:,.2f}")
c3.metric("2026 Book Sales",       f"${sales_ytd:,.2f}")
c4.metric("Net (Sales − Pallets)", f"${net:,.2f}",
          delta="profitable" if net >= 0 else "in the hole",
          delta_color="normal" if net >= 0 else "inverse")
if snap:
    c5.metric("FBA Units (Sellerboard)", f"{snap['units']:,}")

# Pallet detail expander
with st.expander("📦 Pallet purchase history"):
    if pallets["detail"]:
        det_df = pd.DataFrame(pallets["detail"])
        det_df["Cost"] = det_df["Cost"].apply(lambda x: f"${x:,.2f}")
        det_df["$/Pallet"] = det_df["$/Pallet"].apply(lambda x: f"${x:.2f}")
        st.dataframe(det_df, use_container_width=True, hide_index=True)
    else:
        st.info("No pallet data found.")

# Sellerboard potential (updated Mondays)
if snap and snap.get("pot_sales", 0) > 0:
    margin = snap["pot_profit"] / snap["pot_sales"] * 100
    st.caption(
        f"Sellerboard (as of **{snap['date']}**):  "
        f"Potential Sales **${snap['pot_sales']:,.2f}**  ·  "
        f"Potential Profit **${snap['pot_profit']:,.2f}**  ·  "
        f"Margin **{margin:.1f}%**  ·  Updates Mondays"
    )

# Log new pallet purchase
with st.expander("➕ Log new pallet purchase"):
    with st.form("pallet_form", clear_on_submit=True):
        fc1, fc2, fc3 = st.columns(3)
        p_date   = fc1.text_input("Period (YYYY-MM)", value=date.today().strftime("%Y-%m"))
        p_count  = fc2.number_input("# Pallets", min_value=1, step=1, value=1)
        p_price  = fc3.number_input("$ per pallet", min_value=0.0, step=1.0, value=86.0)
        if st.form_submit_button("Save Pallet Purchase", type="primary"):
            total_val = p_count * p_price
            ws = get_spreadsheet().worksheet("📦 Colin - Pallet Sales")
            ws.append_row([p_date, p_count, p_price, total_val, 0, total_val])
            st.success(f"Logged {p_count} pallet(s) × ${p_price:.2f} = ${total_val:.2f} for {p_date}")
            st.cache_data.clear()
            st.rerun()

st.divider()

# ─── Inventory filters ────────────────────────────────────────────────────────

c1, c2, c3 = st.columns([2, 2, 1])
search        = c1.text_input("Search title / author", placeholder="Search...")
status_filter = c2.selectbox("Status", STATUSES)
if c3.button("🔄 Refresh"):
    st.cache_data.clear()
    st.rerun()

df = load_inventory()

if df.empty:
    st.info("No books in inventory yet. Use Scan & Add to add your first book.")
    st.stop()

# ─── Filters ──────────────────────────────────────────────────────────────────

full_df = df.copy()

if status_filter != "All" and "Status" in df.columns:
    df = df[df["Status"] == status_filter]

if search:
    mask = (
        df.get("Title",  pd.Series([""] * len(df))).str.contains(search, case=False, na=False) |
        df.get("Author", pd.Series([""] * len(df))).str.contains(search, case=False, na=False)
    )
    df = df[mask]

# ─── Summary ──────────────────────────────────────────────────────────────────

c1, c2, c3, c4 = st.columns(4)
c1.metric("Showing", len(df))
if "Status" in full_df.columns:
    c2.metric("Unlisted", int((full_df["Status"] == "Unlisted").sum()))
    c3.metric("Listed",   int((full_df["Status"] == "Listed").sum()))
    c4.metric("Sold",     int((full_df["Status"] == "Sold").sum()))

st.divider()

# ─── Inventory table (read-only — no per-book cost tracking) ──────────────────

show_cols = [c for c in [
    "SKU", "Title", "Author", "ASIN", "Condition",
    "List Price ($)", "Status", "Date Added", "Notes",
] if c in df.columns]

col_cfg: dict = {}
for col in show_cols:
    if col == "List Price ($)":
        col_cfg[col] = st.column_config.NumberColumn(
            "List Price ($)", format="$%.2f", disabled=True
        )
    else:
        col_cfg[col] = st.column_config.Column(col, disabled=True)

st.dataframe(
    df[show_cols].reset_index(drop=True),
    column_config=col_cfg,
    use_container_width=True,
    hide_index=True,
)
st.caption("Book cost tracked at the pallet level above — no per-book COGS.")
