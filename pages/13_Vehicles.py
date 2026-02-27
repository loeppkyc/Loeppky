"""
Vehicles
Track vehicle details, loan status, odometer, and maintenance log.
Data lives in the '🚗 Vehicles' sheet of the masterfile.
"""

import streamlit as st
import pandas as pd
from datetime import date, datetime
from utils.sheets import get_spreadsheet
from utils.auth import require_auth

st.set_page_config(
    page_title="Vehicles",
    page_icon="🚗",
    layout="centered",
)

require_auth("business")

SPREADSHEET_ID = "1arXxho2gD8IeWbQNcOt8IwZ7DRl2wz-qJzC3J4hiR4k"
SHEET_NAME = "🚗 Vehicles"
MAINTENANCE_HEADER_ROW = 28   # sheet row of the maintenance log header
MAINTENANCE_DATA_START = 29   # first data row


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _ws():
    return get_spreadsheet().worksheet(SHEET_NAME)


@st.cache_data(ttl=120)
def load_maintenance() -> list[dict]:
    ws = _ws()
    all_vals = ws.get_all_values()
    # Header is row 28 (index 27), data starts at row 29 (index 28)
    if len(all_vals) < 28:
        return []
    header = all_vals[27]   # ["Date", "Vehicle", "Km", "Service / Work Done", "Cost ($)", "Notes"]
    rows = []
    for i, raw in enumerate(all_vals[28:], start=29):
        if not any(str(v).strip() for v in raw):
            continue
        padded = raw + [""] * max(0, len(header) - len(raw))
        d = dict(zip(header, padded))
        d["_sheet_row"] = i
        try:
            d["_cost"] = float(str(d.get("Cost ($)", 0)).replace(",", "").replace("$", "") or 0)
        except (ValueError, TypeError):
            d["_cost"] = 0.0
        rows.append(d)
    return rows


def add_maintenance(log_date: str, vehicle: str, km: int, service: str,
                    cost: float, notes: str) -> None:
    ws = _ws()
    col_a = ws.col_values(1)
    # Find first empty row at or after MAINTENANCE_DATA_START
    next_row = MAINTENANCE_DATA_START
    for i, val in enumerate(col_a[MAINTENANCE_DATA_START - 1:], start=MAINTENANCE_DATA_START):
        if not str(val).strip():
            next_row = i
            break
    else:
        next_row = len(col_a) + 1

    ws.update(f"A{next_row}:F{next_row}",
              [[log_date, vehicle, km, service, cost, notes]],
              value_input_option="USER_ENTERED")


# ─── Page ─────────────────────────────────────────────────────────────────────

st.title("🚗 Vehicles")

# ── Vehicle Cards ──────────────────────────────────────────────────────────────

col1, col2 = st.columns(2)

with col1:
    st.subheader("⚡ 2022 Tesla Model Y LR AWD")
    st.caption("Business vehicle")
    st.markdown("""
| | |
|---|---|
| **Purchased** | January 2025 |
| **Purchase price** | $40,500 (used) |
| **Km at purchase** | 72,000 km |
| **Current km** | 112,800 km |
| **Km driven** | ~40,800 km (13 months) |
| **Avg pace** | ~3,138 km/month |
| **Tax** | None (First Nations — Megan) |
""")

with col2:
    st.subheader("🚘 2021 Toyota Corolla LE")
    st.caption("Personal vehicle (Megan/family)")
    st.markdown("""
| | |
|---|---|
| **Purchased** | 2021 (new) |
| **Purchase price** | $30,000 |
| **Km at purchase** | 0 km |
| **Current km** | ~194,000 km |
| **Tax** | None (First Nations — Megan) |
| **Loan** | Paid off ✅ |
""")

st.divider()

# ── Tesla Loan ─────────────────────────────────────────────────────────────────

st.subheader("💳 Tesla Loan Tracker")

BALANCE_AS_OF    = "Feb 2026"
BALANCE          = 22_108.50
BIWEEKLY_PMT     = 211.71
PAYMENTS_PER_YR  = 26
ANNUAL_TOTAL     = round(BIWEEKLY_PMT * PAYMENTS_PER_YR, 2)
MONTHLY_AVG      = round(ANNUAL_TOTAL / 12, 2)
REMAINING_PMTS   = int(BALANCE / BIWEEKLY_PMT)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Balance", f"${BALANCE:,.2f}", delta=f"as of {BALANCE_AS_OF}", delta_color="off")
c2.metric("Biweekly payment", f"${BIWEEKLY_PMT:.2f}")
c3.metric("Annual cost", f"${ANNUAL_TOTAL:,.2f}", delta="26 payments/year", delta_color="off")
c4.metric("Est. payoff", "~Early 2030", delta=f"~{REMAINING_PMTS} payments left", delta_color="off")

st.caption(
    f"Monthly average: **${MONTHLY_AVG:.2f}**  ·  "
    "Business use: **66%**  ·  "
    "Lender: CIBC  ·  "
    "Payment method: TD Debit"
)

# 2026 payment schedule
with st.expander("📅 2026 Biweekly Payment Schedule"):
    schedule_2026 = [
        "2026-01-14", "2026-01-28",
        "2026-02-11", "2026-02-25",
        "2026-03-11", "2026-03-25",
        "2026-04-08", "2026-04-22",
        "2026-05-06", "2026-05-20",
        "2026-06-03", "2026-06-17",
        "2026-07-01", "2026-07-15", "2026-07-29",
        "2026-08-12", "2026-08-26",
        "2026-09-09", "2026-09-23",
        "2026-10-07", "2026-10-21",
        "2026-11-04", "2026-11-18",
        "2026-12-02", "2026-12-16", "2026-12-30",
    ]
    today = date.today()
    rows = []
    running_balance = BALANCE
    # Approximate: each payment reduces balance by $211.71
    # (simplified — doesn't split principal/interest)
    for d in schedule_2026:
        dt = datetime.strptime(d, "%Y-%m-%d").date()
        status = "✅ Paid" if dt <= today else "⏳ Upcoming"
        running_balance = max(0, running_balance - BIWEEKLY_PMT)
        rows.append({
            "Date": d,
            "Amount": f"${BIWEEKLY_PMT:.2f}",
            "Est. Balance After": f"${running_balance:,.2f}",
            "Status": status,
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(
        "⚠️ Balance shown is a simplified estimate (full payment = balance reduction). "
        "Actual principal/interest split depends on your loan agreement."
    )

st.divider()

# ── Maintenance Log ────────────────────────────────────────────────────────────

st.subheader("🔧 Maintenance Log")

if st.button("🔄 Refresh"):
    st.cache_data.clear()
    st.rerun()

maintenance = load_maintenance()

with st.expander("➕ Add Maintenance Entry"):
    c1, c2 = st.columns(2)
    m_date    = c1.date_input("Date", value=date.today(), key="m_date")
    m_vehicle = c2.selectbox("Vehicle", ["Tesla Model Y", "Corolla LE"], key="m_veh")
    m_km      = st.number_input("Odometer (km)", min_value=0, step=100, key="m_km")
    m_service = st.text_input("Service / Work Done",
                               placeholder="e.g. Tire rotation, Brake inspection",
                               key="m_svc")
    c3, c4 = st.columns(2)
    m_cost  = c3.number_input("Cost ($)", min_value=0.0, step=1.0, format="%.2f", key="m_cost")
    m_notes = c4.text_input("Notes (optional)", key="m_notes")

    if st.button("✅ Save Entry", type="primary", use_container_width=True):
        if not m_service:
            st.error("Enter a service description.")
        else:
            add_maintenance(
                m_date.strftime("%Y-%m-%d"),
                m_vehicle,
                int(m_km),
                m_service,
                m_cost,
                m_notes,
            )
            st.success(f"Saved: {m_vehicle} — {m_service} on {m_date}")
            st.cache_data.clear()
            st.rerun()

if not maintenance:
    st.info("No maintenance entries yet — use the form above to add the first one.")
else:
    total_cost = sum(r["_cost"] for r in maintenance)
    st.caption(f"{len(maintenance)} entries  ·  Total maintenance cost: **${total_cost:,.2f}**")

    hcols = st.columns([1.3, 1.8, 1.0, 3.5, 1.0, 2.0])
    for col, label in zip(hcols, ["Date", "Vehicle", "Km", "Service", "Cost", "Notes"]):
        col.markdown(f"**{label}**")
    st.divider()

    for r in maintenance:
        cols = st.columns([1.3, 1.8, 1.0, 3.5, 1.0, 2.0])
        cols[0].write(r.get("Date", ""))
        cols[1].write(r.get("Vehicle", ""))
        cols[2].write(r.get("Km", ""))
        cols[3].write(r.get("Service / Work Done", ""))
        cols[4].write(f"${r['_cost']:.2f}" if r["_cost"] else "—")
        cols[5].write(r.get("Notes", ""))
