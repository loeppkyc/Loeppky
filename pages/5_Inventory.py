"""
Inventory
View and manage all books in the Book Inventory sheet.
Filter by status, search by title/author, edit COGS inline and save.
"""

import streamlit as st
import pandas as pd
from utils.sheets import get_spreadsheet
from utils.auth import require_auth

st.set_page_config(
    page_title="Inventory",
    page_icon="📋",
    layout="wide",
)

require_auth("business")

STATUSES  = ["All", "Unlisted", "Listed", "Sold"]
FEE_RATE  = 0.40   # Amazon ~40% of list price (fees + referral)


@st.cache_data(ttl=60)
def load_inventory() -> pd.DataFrame:
    ws   = get_spreadsheet().worksheet("📦 Book Inventory")
    data = ws.get_all_records()
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    for col in ["Cost ($)", "List Price ($)"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    if "List Price ($)" in df.columns and "Cost ($)" in df.columns:
        df["Profit/Unit"] = (
            df["List Price ($)"] * (1 - FEE_RATE) - df["Cost ($)"]
        ).round(2)
    return df


# ─── Page ─────────────────────────────────────────────────────────────────────

st.title("📋 Inventory")

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

# ─── Editable table ───────────────────────────────────────────────────────────

show_cols = [c for c in [
    "SKU", "Title", "Author", "ASIN", "Condition",
    "Cost ($)", "List Price ($)", "Profit/Unit",
    "Status", "Date Added", "Notes",
] if c in df.columns]

# Build original cost lookup (SKU → cost) from the FULL unfiltered df
# so we can detect changes even when view is filtered
orig_costs: dict[str, float] = {}
if "SKU" in df.columns and "Cost ($)" in df.columns:
    orig_costs = dict(zip(df["SKU"], df["Cost ($)"]))

# Column config — only Cost ($) is editable
col_cfg: dict = {}
for col in show_cols:
    if col == "Cost ($)":
        col_cfg[col] = st.column_config.NumberColumn(
            "Cost ($)", min_value=0.0, step=0.25, format="$%.2f"
        )
    elif col == "List Price ($)":
        col_cfg[col] = st.column_config.NumberColumn(
            "List Price ($)", format="$%.2f", disabled=True
        )
    elif col == "Profit/Unit":
        col_cfg[col] = st.column_config.NumberColumn(
            "Profit/Unit", format="$%.2f", disabled=True
        )
    else:
        col_cfg[col] = st.column_config.Column(col, disabled=True)

edited_df = st.data_editor(
    df[show_cols].reset_index(drop=True),
    column_config=col_cfg,
    use_container_width=True,
    hide_index=True,
    key="inventory_editor",
)

st.caption("Edit the **Cost ($)** column, then click Save to update the sheet.")

# ─── Save button ──────────────────────────────────────────────────────────────

if st.button("💾 Save COGS Changes", type="primary"):
    if "SKU" not in df.columns or not orig_costs:
        st.error("Cannot save — SKU column not found.")
        st.stop()

    # Find rows where Cost ($) changed
    changes: list[tuple[str, float]] = []
    for _, row in edited_df.iterrows():
        sku      = str(row.get("SKU", "")).strip()
        new_cost = float(row.get("Cost ($)", 0))
        old_cost = float(orig_costs.get(sku, new_cost))
        if sku and abs(new_cost - old_cost) > 0.001:
            changes.append((sku, new_cost))

    if not changes:
        st.info("No changes detected.")
    else:
        ws       = get_spreadsheet().worksheet("📦 Book Inventory")
        all_vals = ws.get_all_values()
        header   = all_vals[0]
        try:
            sku_col_idx  = header.index("SKU") + 1       # 1-indexed for gspread
            cost_col_idx = header.index("Cost ($)") + 1
        except ValueError:
            st.error("Could not find SKU or Cost ($) column in the sheet header.")
            st.stop()

        saved = 0
        for sku, new_cost in changes:
            for i, sheet_row in enumerate(all_vals[1:], start=2):
                if len(sheet_row) >= sku_col_idx and sheet_row[sku_col_idx - 1] == sku:
                    ws.update_cell(i, cost_col_idx, new_cost)
                    saved += 1
                    break

        st.success(f"Saved {saved} change(s) to Book Inventory.")
        st.cache_data.clear()
        st.rerun()
