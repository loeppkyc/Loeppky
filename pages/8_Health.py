"""
Family Health Records
Track vitals, symptoms, medications, doctor visits, and Oura Ring data
for Colin, Megan, Cora, and Sharon.
"""

import re
import streamlit as st
import pandas as pd
import calendar
from datetime import date, datetime
from io import StringIO
from utils.sheets import get_spreadsheet
from utils.auth import require_auth
from utils.alerts import check_sleep_alert, alerts_configured

st.set_page_config(
    page_title="Health Records",
    page_icon="🏥",
    layout="wide",
)

require_auth("personal")

# ─── Constants ────────────────────────────────────────────────────────────────

PEOPLE = ["Colin", "Megan", "Cora", "Sharon"]

SH_VITALS   = "🏥 Vitals"
SH_SYMPTOMS = "🤒 Symptoms"
SH_MEDS     = "💊 Medications"
SH_VISITS   = "🩺 Doctor Visits"
SH_OURA     = "📊 Oura Daily"

HEADERS = {
    SH_VITALS: [
        "Date", "Person", "Type", "Value", "Unit", "Notes",
    ],
    SH_SYMPTOMS: [
        "Date", "Person", "Symptom", "Severity (1-10)", "Duration", "Resolved Date", "Notes",
    ],
    SH_MEDS: [
        "Person", "Medication", "Dosage", "Frequency", "Start Date", "End Date",
        "Prescribing Doctor", "Pharmacy", "Active (Y/N)", "Notes",
    ],
    SH_VISITS: [
        "Date", "Person", "Doctor Name", "Specialty", "Clinic / Hospital",
        "Reason", "Diagnosis", "Outcome", "Follow-up Date", "Notes",
    ],
    SH_OURA: [
        "Date", "Person", "Sleep Score", "Sleep Total (min)", "Sleep Efficiency (%)",
        "REM (min)", "Deep (min)", "Light (min)", "HRV Avg", "HR Avg", "HR Lowest",
        "Steps", "Calories Active", "Activity Score", "Readiness Score", "Notes",
    ],
}

VITAL_TYPES = [
    "Blood Pressure Systolic (mmHg)",
    "Blood Pressure Diastolic (mmHg)",
    "Weight (lbs)",
    "Weight (kg)",
    "Temperature (°C)",
    "Temperature (°F)",
    "Heart Rate (bpm)",
    "Blood Sugar (mmol/L)",
    "Blood Sugar (mg/dL)",
    "Oxygen Saturation (%)",
    "Other",
]

FREQUENCIES  = ["Daily", "Twice daily", "Three times daily", "Weekly", "As needed", "Other"]
SPECIALTIES  = ["Family Doctor / GP", "Specialist", "Emergency / Walk-in", "Dentist", "Optometrist", "Other"]

# Auto-fill unit from vital type
_UNIT_MAP = {
    "Systolic":  "mmHg",
    "Diastolic": "mmHg",
    "lbs":       "lbs",
    "(kg)":      "kg",
    "°C":        "°C",
    "°F":        "°F",
    "bpm":       "bpm",
    "mmol/L":    "mmol/L",
    "mg/dL":     "mg/dL",
    "(%)":       "%",
}


# ─── Sheet helpers ─────────────────────────────────────────────────────────────

def _ws(name: str):
    """Get or create a worksheet, adding header row if brand new."""
    ss = get_spreadsheet()
    try:
        return ss.worksheet(name)
    except Exception:
        ws = ss.add_worksheet(title=name, rows=1000, cols=len(HEADERS[name]) + 2)
        ws.append_row(HEADERS[name])
        return ws


@st.cache_data(ttl=60)
def load_health(ws_name: str) -> list[dict]:
    """Load all records from a health sheet; returns [] if sheet not created yet."""
    try:
        ws      = get_spreadsheet().worksheet(ws_name)
        records = ws.get_all_records()
        for i, r in enumerate(records, start=2):
            r["_row"] = i
        return records
    except Exception:
        return []


def _append(ws_name: str, values: list):
    _ws(ws_name).append_row(values, value_input_option="USER_ENTERED")


def _delete(ws_name: str, row_idx: int):
    _ws(ws_name).delete_rows(row_idx)


# ─── Oura CSV parser ───────────────────────────────────────────────────────────

def _try_col(row: dict, *keys, default=None):
    """Try multiple possible column name aliases."""
    for k in keys:
        val = row.get(k)
        if val is not None and str(val).strip() not in ("", "nan", "None"):
            return val
    return default


def _to_min(val) -> str:
    """
    Convert a sleep/activity duration to minutes.
    Oura sometimes stores in seconds — if value > 1440 (>24h in minutes) it's seconds.
    Returns string or "" on failure.
    """
    try:
        v = int(float(val))
        if v > 1440:
            return str(v // 60)
        return str(v) if v > 0 else ""
    except (ValueError, TypeError):
        return ""


def parse_oura_csv(content: str, filename: str, person: str) -> list[list]:
    """
    Parse an Oura Ring CSV export file.
    Handles: sleep/daily_sleep, activity/daily_activity, readiness/daily_readiness,
    and combined exports.
    Returns list-of-lists matching HEADERS[SH_OURA].
    """
    try:
        df = pd.read_csv(StringIO(content))
    except Exception:
        return []

    if df.empty:
        return []

    # Normalize column names to lowercase
    df.columns = [c.lower().strip() for c in df.columns]
    cols = set(df.columns)

    is_sleep     = bool(cols & {"total_sleep_duration", "efficiency", "rem_sleep_duration",
                                 "deep_sleep_duration", "light_sleep_duration"})
    is_activity  = bool(cols & {"steps", "total_steps", "cal_active", "active_calories"})
    is_readiness = bool(cols & {"temperature_deviation", "recovery_index", "readiness_score",
                                 "score_readiness"})
    is_sleep    |= "sleep_score" in cols or "score_sleep" in cols
    is_activity |= "activity_score" in cols or "score_activity" in cols

    rows_out = []

    for _, row in df.iterrows():
        # ── Date ──
        dt_raw = str(_try_col(row, "day", "summary_date", "date", default="")).strip()
        if not dt_raw or dt_raw in ("", "nan", "None"):
            continue
        dt = ""
        for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"]:
            try:
                dt = datetime.strptime(dt_raw[:10], fmt).strftime("%Y-%m-%d")
                break
            except ValueError:
                continue
        if not dt:
            continue

        # Build 16-element row: [Date, Person, + 14 metric slots]
        r = [dt, person, "", "", "", "", "", "", "", "", "", "", "", "", "", ""]
        # indices:  0    1   2   3   4   5   6   7   8   9  10  11  12  13  14  15
        #         Date Per SScr STot SEff REM Deep Light HRV HRa HRl Steps CalA AScr RScr Notes

        if is_sleep:
            r[2]  = str(_try_col(row, "sleep_score", "score_sleep") or "")
            r[3]  = _to_min(_try_col(row, "total_sleep_duration", "total"))
            r[4]  = str(_try_col(row, "efficiency", "sleep_efficiency") or "")
            r[5]  = _to_min(_try_col(row, "rem_sleep_duration", "rem"))
            r[6]  = _to_min(_try_col(row, "deep_sleep_duration", "deep"))
            r[7]  = _to_min(_try_col(row, "light_sleep_duration", "light"))
            r[8]  = str(_try_col(row, "average_hrv", "hrv_average", "hrv_avg") or "")
            r[9]  = str(_try_col(row, "average_heart_rate", "hr_average", "hr_avg") or "")
            r[10] = str(_try_col(row, "lowest_heart_rate", "hr_lowest") or "")

        if is_activity:
            r[11] = str(_try_col(row, "steps", "total_steps") or "")
            r[12] = str(_try_col(row, "active_calories", "cal_active") or "")
            r[13] = str(_try_col(row, "activity_score", "score_activity") or "")

        if is_readiness:
            r[14] = str(_try_col(row, "readiness_score", "score_readiness") or "")

        # Skip rows with no useful data
        if all(v.strip() in ("", "None") for v in r[2:15]):
            continue

        rows_out.append(r)

    return rows_out


def import_oura_rows(parsed: list[list], person: str) -> tuple[int, int]:
    """
    Upsert Oura rows — skip (Date, Person) pairs already in the sheet.
    Returns (added, skipped).
    """
    if not parsed:
        return 0, 0

    existing      = load_health(SH_OURA)
    existing_keys = {(r.get("Date", ""), r.get("Person", "")) for r in existing}

    new_rows = []
    skipped  = 0
    for r in parsed:
        if (r[0], r[1]) in existing_keys:
            skipped += 1
        else:
            new_rows.append(r)

    if new_rows:
        _ws(SH_OURA).append_rows(new_rows, value_input_option="USER_ENTERED")

    return len(new_rows), skipped


# ─── Session state ─────────────────────────────────────────────────────────────

for _sk, _sv in [("health_del_target", None), ("health_del_ws", None)]:
    if _sk not in st.session_state:
        st.session_state[_sk] = _sv


# ─── Page ──────────────────────────────────────────────────────────────────────

st.title("🏥 Family Health Records")

_hdr1, _hdr2 = st.columns([5, 1])
person = _hdr1.radio("Viewing records for:", PEOPLE, horizontal=True, key="health_person")
with _hdr2:
    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

st.divider()

(tab_dash, tab_oura, tab_vitals,
 tab_symptoms, tab_meds, tab_visits, tab_export) = st.tabs([
    "📊 Dashboard", "⭕ Oura", "📈 Vitals",
    "🤒 Symptoms", "💊 Medications", "🩺 Doctor Visits", "📤 Export",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

with tab_dash:
    st.subheader(f"Health Overview — {person}")

    vitals_all   = load_health(SH_VITALS)
    symptoms_all = load_health(SH_SYMPTOMS)
    meds_all     = load_health(SH_MEDS)
    visits_all   = load_health(SH_VISITS)
    oura_all     = load_health(SH_OURA)

    p_vitals   = [r for r in vitals_all   if r.get("Person") == person]
    p_symptoms = [r for r in symptoms_all if r.get("Person") == person]
    p_meds     = [r for r in meds_all     if r.get("Person") == person]
    p_visits   = [r for r in visits_all   if r.get("Person") == person]
    p_oura     = [r for r in oura_all     if r.get("Person") == person]

    active_meds     = [m for m in p_meds     if str(m.get("Active (Y/N)", "Y")).upper() == "Y"]
    active_symptoms = [s for s in p_symptoms if not str(s.get("Resolved Date", "")).strip()]
    upcoming_visits = [v for v in p_visits
                       if v.get("Follow-up Date", "").strip() >= date.today().isoformat()]

    dc1, dc2, dc3, dc4 = st.columns(4)
    dc1.metric("Active Meds",     len(active_meds))
    dc2.metric("Active Symptoms", len(active_symptoms))
    dc3.metric("Doctor Visits",   len(p_visits))
    dc4.metric("Oura Days",       len(p_oura))

    # Latest Oura scores
    if p_oura:
        st.markdown("---")
        st.markdown("**Latest Oura Scores**")
        try:
            oura_df = pd.DataFrame(p_oura)
            oura_df["Date"] = pd.to_datetime(oura_df["Date"], errors="coerce")
            oura_df = oura_df.dropna(subset=["Date"]).sort_values("Date")
            last = oura_df.iloc[-1]
            oc1, oc2, oc3 = st.columns(3)
            oc1.metric("Sleep Score",     last.get("Sleep Score", "—") or "—")
            oc2.metric("Activity Score",  last.get("Activity Score", "—") or "—")
            oc3.metric("Readiness Score", last.get("Readiness Score", "—") or "—")
            st.caption(f"Last recorded: {last['Date'].strftime('%b %d, %Y')}")
        except Exception:
            pass

    # Active medications summary
    if active_meds:
        st.markdown("---")
        st.markdown(f"**Current Medications ({len(active_meds)})**")
        med_rows = [{"Medication": m.get("Medication", ""),
                     "Dosage":     m.get("Dosage", ""),
                     "Frequency":  m.get("Frequency", "")} for m in active_meds]
        st.dataframe(pd.DataFrame(med_rows), hide_index=True, use_container_width=True)

    # Active symptoms summary
    if active_symptoms:
        st.markdown("---")
        st.markdown(f"**Active Symptoms ({len(active_symptoms)})**")
        sym_rows = [{"Date":     s.get("Date", ""),
                     "Symptom":  s.get("Symptom", ""),
                     "Severity": s.get("Severity (1-10)", ""),
                     "Notes":    s.get("Notes", "")} for s in
                    sorted(active_symptoms, key=lambda x: x.get("Date", ""), reverse=True)]
        st.dataframe(pd.DataFrame(sym_rows), hide_index=True, use_container_width=True)

    if not p_meds and not p_symptoms and not p_oura and not p_visits and not p_vitals:
        st.info(f"No health records yet for {person}. Use the tabs above to start logging.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — OURA DATA
# ══════════════════════════════════════════════════════════════════════════════

with tab_oura:
    st.subheader(f"⭕ Oura Ring Data — {person}")

    oura_all = load_health(SH_OURA)
    p_oura   = [r for r in oura_all if r.get("Person") == person]

    # ── Import ────────────────────────────────────────────────────────────────
    with st.expander("📥 Import Oura CSV Files"):
        st.info(
            "**How to export:** Oura app → Profile → Account → Privacy → "
            "Download My Data. Upload each CSV (sleep.csv, daily_activity.csv, "
            "readiness.csv, etc.). You can upload multiple files at once."
        )
        uploaded = st.file_uploader(
            "Choose Oura CSV file(s)",
            type=["csv"],
            accept_multiple_files=True,
            key="oura_upload",
        )
        if uploaded:
            if st.button("📥 Import Selected Files", type="primary", key="oura_import_btn"):
                total_added = total_skipped = 0
                errors = []
                for f in uploaded:
                    try:
                        content = f.read().decode("utf-8", errors="replace")
                        parsed  = parse_oura_csv(content, f.name, person)
                        added, skipped = import_oura_rows(parsed, person)
                        total_added   += added
                        total_skipped += skipped
                    except Exception as e:
                        errors.append(f"{f.name}: {e}")
                st.cache_data.clear()
                if errors:
                    st.warning("Some files had errors:\n" + "\n".join(errors))
                st.success(
                    f"Imported **{total_added}** new day(s). "
                    f"Skipped **{total_skipped}** already-existing."
                )
                # Check sleep score alerts for newly imported rows
                if total_added > 0:
                    fresh = load_health(SH_OURA)
                    fresh_person = sorted(
                        [r for r in fresh if r.get("Person") == person],
                        key=lambda x: x.get("Date", ""), reverse=True,
                    )
                    for r in fresh_person[:total_added]:
                        score = r.get("Sleep Score", "")
                        if score:
                            check_sleep_alert(person, score)
                st.rerun()

    # ── Charts ────────────────────────────────────────────────────────────────
    if not p_oura:
        st.info("No Oura data yet. Import CSV files above.")
    else:
        try:
            oura_df = pd.DataFrame(p_oura)
            oura_df["Date"] = pd.to_datetime(oura_df["Date"], errors="coerce")
            oura_df = oura_df.dropna(subset=["Date"]).sort_values("Date").set_index("Date")

            def _num(df, col):
                if col in df.columns:
                    return pd.to_numeric(df[col], errors="coerce")
                return None

            # Date range filter
            min_d = oura_df.index.min().date()
            max_d = oura_df.index.max().date()
            fr1, fr2 = st.columns(2)
            from_d = fr1.date_input("From", value=min_d, min_value=min_d, max_value=max_d, key="oura_from")
            to_d   = fr2.date_input("To",   value=max_d, min_value=min_d, max_value=max_d, key="oura_to")
            mask = (oura_df.index.date >= from_d) & (oura_df.index.date <= to_d)
            oura_df = oura_df[mask]

            if oura_df.empty:
                st.warning("No data in selected date range.")
            else:
                st.markdown("---")

                # Scores
                score_data = {}
                for col, label in [("Sleep Score", "Sleep"), ("Activity Score", "Activity"),
                                    ("Readiness Score", "Readiness")]:
                    s = _num(oura_df, col)
                    if s is not None and s.notna().any():
                        score_data[label] = s
                if score_data:
                    st.markdown("**Daily Scores (0–100)**")
                    st.line_chart(pd.DataFrame(score_data), y_label="Score")

                # Sleep breakdown
                sleep_data = {}
                for col, label in [("Deep (min)", "Deep"), ("REM (min)", "REM"),
                                    ("Light (min)", "Light")]:
                    s = _num(oura_df, col)
                    if s is not None and s.notna().any():
                        sleep_data[label] = s
                if sleep_data:
                    st.markdown("**Sleep Breakdown (minutes per night)**")
                    st.bar_chart(pd.DataFrame(sleep_data), y_label="Minutes")

                # HRV + HR
                hr_data = {}
                for col, label in [("HRV Avg", "HRV (ms)"), ("HR Avg", "HR Avg (bpm)"),
                                    ("HR Lowest", "HR Lowest (bpm)")]:
                    s = _num(oura_df, col)
                    if s is not None and s.notna().any():
                        hr_data[label] = s
                if hr_data:
                    st.markdown("**Heart Rate & HRV**")
                    st.line_chart(pd.DataFrame(hr_data), y_label="Value")

                # Steps
                steps = _num(oura_df, "Steps")
                if steps is not None and steps.notna().any():
                    st.markdown("**Daily Steps**")
                    st.bar_chart(steps.rename("Steps"), y_label="Steps")

                # Raw table
                with st.expander("View raw data table"):
                    show_cols = [c for c in oura_df.columns if not c.startswith("_")]
                    st.dataframe(
                        oura_df[show_cols].reset_index(),
                        hide_index=True,
                        use_container_width=True,
                    )

        except Exception as e:
            st.error(f"Could not render charts: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — VITALS
# ══════════════════════════════════════════════════════════════════════════════

with tab_vitals:
    st.subheader(f"📈 Vitals — {person}")

    vitals_all = load_health(SH_VITALS)
    p_vitals   = [r for r in vitals_all if r.get("Person") == person]

    # ── Add vital ─────────────────────────────────────────────────────────────
    with st.expander("➕ Log Vital"):
        vc1, vc2 = st.columns(2)
        vit_date = vc1.date_input("Date", value=date.today(), key="vit_date")
        vit_type = vc2.selectbox("Type", VITAL_TYPES, key="vit_type")

        _auto_unit = next((v for k, v in _UNIT_MAP.items() if k in vit_type), "")
        vc3, vc4  = st.columns(2)
        vit_value = vc3.text_input("Value", placeholder="e.g. 120/80 or 72", key="vit_val")
        vit_unit  = vc4.text_input("Unit", value=_auto_unit, key="vit_unit")
        vit_notes = st.text_input("Notes (optional)", key="vit_notes")

        if st.button("✅ Log Vital", type="primary", key="vit_btn"):
            if not vit_value.strip():
                st.error("Enter a value.")
            else:
                _append(SH_VITALS, [
                    vit_date.strftime("%Y-%m-%d"), person,
                    vit_type, vit_value, vit_unit, vit_notes,
                ])
                st.cache_data.clear()
                st.rerun()

    # ── Chart + table ─────────────────────────────────────────────────────────
    if not p_vitals:
        st.info("No vitals logged yet.")
    else:
        # Chart for a selected vital type
        type_options = sorted({r.get("Type", "") for r in p_vitals if r.get("Type")})
        if type_options:
            vit_sel = st.selectbox("Chart vital type", type_options, key="vit_chart_type")
            chart_rows = [r for r in p_vitals if r.get("Type") == vit_sel]
            try:
                cdf = pd.DataFrame(chart_rows)
                cdf["Date"]  = pd.to_datetime(cdf["Date"], errors="coerce")
                cdf["Value"] = pd.to_numeric(
                    cdf["Value"].astype(str).str.extract(r"([\d.]+)")[0], errors="coerce"
                )
                cdf = cdf.dropna(subset=["Date", "Value"]).sort_values("Date").set_index("Date")
                if not cdf.empty:
                    st.line_chart(cdf["Value"].rename(vit_sel), y_label=vit_sel)
            except Exception:
                pass

        display = [{
            "Date":  r.get("Date", ""),
            "Type":  r.get("Type", ""),
            "Value": r.get("Value", ""),
            "Unit":  r.get("Unit", ""),
            "Notes": r.get("Notes", ""),
        } for r in sorted(p_vitals, key=lambda x: x.get("Date", ""), reverse=True)]
        st.dataframe(pd.DataFrame(display), hide_index=True, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — SYMPTOMS
# ══════════════════════════════════════════════════════════════════════════════

with tab_symptoms:
    st.subheader(f"🤒 Symptoms & Health Events — {person}")

    symptoms_all = load_health(SH_SYMPTOMS)
    p_symptoms   = [r for r in symptoms_all if r.get("Person") == person]

    # ── Add symptom ───────────────────────────────────────────────────────────
    with st.expander("➕ Log Symptom / Health Event"):
        sc1, sc2 = st.columns(2)
        sym_date    = sc1.date_input("Date", value=date.today(), key="sym_date")
        sym_symptom = sc2.text_input(
            "Symptom / Event",
            placeholder="e.g. Headache, Fatigue, Chest pain",
            key="sym_sym",
        )
        sc3, sc4, sc5 = st.columns(3)
        sym_severity = sc3.slider("Severity (1–10)", 1, 10, 5, key="sym_sev")
        sym_duration = sc4.text_input("Duration", placeholder="e.g. 2 hrs, ongoing", key="sym_dur")
        sym_resolved = sc5.date_input("Resolved (if known)", value=None, key="sym_res")
        sym_notes    = st.text_input(
            "Notes",
            placeholder="e.g. triggered by, body location, associated symptoms",
            key="sym_notes",
        )

        if st.button("✅ Log Symptom", type="primary", key="sym_btn"):
            if not sym_symptom.strip():
                st.error("Enter a symptom or event description.")
            else:
                resolved_str = sym_resolved.strftime("%Y-%m-%d") if sym_resolved else ""
                _append(SH_SYMPTOMS, [
                    sym_date.strftime("%Y-%m-%d"), person,
                    sym_symptom, sym_severity, sym_duration, resolved_str, sym_notes,
                ])
                st.cache_data.clear()
                st.rerun()

    # ── Active + resolved ─────────────────────────────────────────────────────
    if not p_symptoms:
        st.info("No symptoms logged yet.")
    else:
        active   = [s for s in p_symptoms if not str(s.get("Resolved Date", "")).strip()]
        resolved = [s for s in p_symptoms if     str(s.get("Resolved Date", "")).strip()]

        if active:
            st.markdown(f"**Active ({len(active)})**")
            # Header
            ahdr = st.columns([1.2, 2.5, 0.8, 1.5, 2.5, 0.8])
            for col, lbl in zip(ahdr, ["Date", "Symptom", "Severity", "Duration", "Notes", ""]):
                col.markdown(f"**{lbl}**")
            st.divider()
            for s in sorted(active, key=lambda x: x.get("Date", ""), reverse=True):
                row_id = s["_row"]
                ac = st.columns([1.2, 2.5, 0.8, 1.5, 2.5, 0.8])
                ac[0].write(s.get("Date", ""))
                ac[1].write(s.get("Symptom", ""))
                ac[2].write(f"**{s.get('Severity (1-10)', '')}**/10")
                ac[3].write(s.get("Duration", ""))
                ac[4].write(s.get("Notes", ""))
                if ac[5].button("✓ Resolved", key=f"sym_resolve_{row_id}", help="Mark as resolved today"):
                    _ws(SH_SYMPTOMS).update_cell(row_id, 6, date.today().strftime("%Y-%m-%d"))
                    st.cache_data.clear()
                    st.rerun()

        if resolved:
            with st.expander(f"Resolved symptoms ({len(resolved)})"):
                res_display = [{
                    "Date":     r.get("Date", ""),
                    "Symptom":  r.get("Symptom", ""),
                    "Severity": r.get("Severity (1-10)", ""),
                    "Duration": r.get("Duration", ""),
                    "Resolved": r.get("Resolved Date", ""),
                    "Notes":    r.get("Notes", ""),
                } for r in sorted(resolved, key=lambda x: x.get("Date", ""), reverse=True)]
                st.dataframe(pd.DataFrame(res_display), hide_index=True, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — MEDICATIONS
# ══════════════════════════════════════════════════════════════════════════════

with tab_meds:
    st.subheader(f"💊 Medications & Supplements — {person}")

    meds_all = load_health(SH_MEDS)
    p_meds   = [r for r in meds_all if r.get("Person") == person]

    # ── Add medication ────────────────────────────────────────────────────────
    with st.expander("➕ Add Medication / Supplement"):
        mc1, mc2 = st.columns(2)
        med_name   = mc1.text_input(
            "Medication / Supplement",
            placeholder="e.g. Metformin, Vitamin D3",
            key="med_name",
        )
        med_dosage = mc2.text_input("Dosage", placeholder="e.g. 500mg, 2000 IU", key="med_dosage")

        mc3, mc4 = st.columns(2)
        med_freq   = mc3.selectbox("Frequency", FREQUENCIES, key="med_freq")
        med_doctor = mc4.text_input(
            "Prescribing Doctor (optional)",
            placeholder="e.g. Dr. Smith",
            key="med_doc",
        )

        mc5, mc6, mc7 = st.columns(3)
        med_start = mc5.date_input("Start Date", value=date.today(), key="med_start")
        med_end   = mc6.date_input("End Date (if known)", value=None, key="med_end")
        med_pharm = mc7.text_input("Pharmacy (optional)", key="med_pharm")
        med_notes = st.text_input(
            "Notes",
            placeholder="e.g. reason for taking, side effects, food interactions",
            key="med_notes",
        )

        if st.button("✅ Add Medication", type="primary", key="med_btn"):
            if not med_name.strip():
                st.error("Enter a medication or supplement name.")
            else:
                end_str = med_end.strftime("%Y-%m-%d") if med_end else ""
                _append(SH_MEDS, [
                    person, med_name, med_dosage, med_freq,
                    med_start.strftime("%Y-%m-%d"), end_str,
                    med_doctor, med_pharm, "Y", med_notes,
                ])
                st.cache_data.clear()
                st.rerun()

    # ── Render ────────────────────────────────────────────────────────────────
    if not p_meds:
        st.info("No medications logged yet.")
    else:
        active_meds   = [m for m in p_meds if str(m.get("Active (Y/N)", "Y")).upper() == "Y"]
        inactive_meds = [m for m in p_meds if str(m.get("Active (Y/N)", "Y")).upper() != "Y"]

        def _med_row(m):
            row_id = m["_row"]
            mc = st.columns([2.2, 1.2, 1.5, 1.3, 1.8, 0.8, 0.6])
            mc[0].write(f"**{m.get('Medication', '')}**")
            mc[1].write(m.get("Dosage", ""))
            mc[2].write(m.get("Frequency", ""))
            mc[3].write(m.get("Start Date", ""))
            mc[4].write(m.get("Prescribing Doctor", ""))
            if str(m.get("Active (Y/N)", "Y")).upper() == "Y":
                if mc[5].button("⏹ Stop", key=f"med_stop_{row_id}", help="Mark as no longer taking"):
                    ws = _ws(SH_MEDS)
                    ws.update_cell(row_id, 9, "N")  # Active (Y/N) = column I
                    ws.update_cell(row_id, 6, date.today().strftime("%Y-%m-%d"))  # End Date = col F
                    st.cache_data.clear()
                    st.rerun()
            if mc[6].button("🗑️", key=f"med_del_{row_id}", help="Delete"):
                _delete(SH_MEDS, row_id)
                st.cache_data.clear()
                st.rerun()

        if active_meds:
            st.markdown(f"**Current ({len(active_meds)})**")
            mhdr = st.columns([2.2, 1.2, 1.5, 1.3, 1.8, 0.8, 0.6])
            for col, lbl in zip(mhdr, ["Medication", "Dosage", "Frequency", "Start", "Doctor", "", ""]):
                col.markdown(f"**{lbl}**")
            st.divider()
            for m in active_meds:
                _med_row(m)

        if inactive_meds:
            with st.expander(f"Past medications ({len(inactive_meds)})"):
                mhdr2 = st.columns([2.2, 1.2, 1.5, 1.3, 1.8, 0.8, 0.6])
                for col, lbl in zip(mhdr2, ["Medication", "Dosage", "Frequency", "Start", "Doctor", "", ""]):
                    col.markdown(f"**{lbl}**")
                st.divider()
                for m in inactive_meds:
                    _med_row(m)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — DOCTOR VISITS
# ══════════════════════════════════════════════════════════════════════════════

with tab_visits:
    st.subheader(f"🩺 Doctor Visits — {person}")

    visits_all = load_health(SH_VISITS)
    p_visits   = [r for r in visits_all if r.get("Person") == person]

    # ── Add visit ─────────────────────────────────────────────────────────────
    with st.expander("➕ Log Doctor Visit / Appointment"):
        vsc1, vsc2 = st.columns(2)
        vis_date   = vsc1.date_input("Date", value=date.today(), key="vis_date")
        vis_doctor = vsc2.text_input("Doctor Name", placeholder="e.g. Dr. Singh", key="vis_doc")

        vsc3, vsc4 = st.columns(2)
        vis_spec   = vsc3.selectbox("Specialty / Type", SPECIALTIES, key="vis_spec")
        vis_clinic = vsc4.text_input(
            "Clinic / Hospital",
            placeholder="e.g. Grey Nuns Hospital, Misericordia",
            key="vis_clinic",
        )

        vis_reason  = st.text_input(
            "Reason for Visit",
            placeholder="e.g. Annual checkup, persistent chest pain, follow-up on bloodwork",
            key="vis_reason",
        )
        vis_diag    = st.text_area(
            "Diagnosis / Findings",
            height=80,
            placeholder="What was found, diagnosed, or noted by the doctor",
            key="vis_diag",
        )
        vis_outcome = st.text_area(
            "Outcome / Treatment",
            height=80,
            placeholder="Prescriptions given, referred to specialist, lifestyle advice, etc.",
            key="vis_outcome",
        )

        vsc5, vsc6 = st.columns(2)
        vis_followup = vsc5.date_input("Follow-up Date (if any)", value=None, key="vis_followup")
        vis_notes    = vsc6.text_input("Additional Notes", key="vis_notes")

        if st.button("✅ Log Visit", type="primary", key="vis_btn"):
            if not vis_doctor.strip():
                st.error("Enter a doctor name.")
            else:
                followup_str = vis_followup.strftime("%Y-%m-%d") if vis_followup else ""
                _append(SH_VISITS, [
                    vis_date.strftime("%Y-%m-%d"), person,
                    vis_doctor, vis_spec, vis_clinic,
                    vis_reason, vis_diag, vis_outcome,
                    followup_str, vis_notes,
                ])
                st.cache_data.clear()
                st.rerun()

    # ── Visit list ────────────────────────────────────────────────────────────
    if not p_visits:
        st.info("No doctor visits logged yet.")
    else:
        for v in sorted(p_visits, key=lambda x: x.get("Date", ""), reverse=True):
            row_id = v["_row"]
            header_text = (
                f"**{v.get('Date', '')}** — {v.get('Doctor Name', '')} "
                f"({v.get('Specialty', '')}) · {v.get('Reason', '')[:60]}"
            )
            with st.expander(header_text):
                vc = st.columns(2)
                vc[0].markdown(f"**Clinic / Hospital:** {v.get('Clinic / Hospital', '') or '—'}")
                vc[1].markdown(f"**Follow-up Date:** {v.get('Follow-up Date', '') or '—'}")

                st.markdown(f"**Diagnosis / Findings:**")
                st.write(v.get("Diagnosis", "") or "—")

                st.markdown(f"**Outcome / Treatment:**")
                st.write(v.get("Outcome", "") or "—")

                if v.get("Notes"):
                    st.caption(f"Notes: {v['Notes']}")

                if st.button("🗑️ Delete this visit", key=f"vis_del_{row_id}"):
                    _delete(SH_VISITS, row_id)
                    st.cache_data.clear()
                    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 7 — EXPORT
# ══════════════════════════════════════════════════════════════════════════════

with tab_export:
    st.subheader(f"📤 Export — {person}")
    st.info(
        "Download any section as a CSV to print, email to a doctor, "
        "or keep as a backup. All records are filtered to the selected person."
    )

    export_map = {
        "Vitals":        load_health(SH_VITALS),
        "Symptoms":      load_health(SH_SYMPTOMS),
        "Medications":   load_health(SH_MEDS),
        "Doctor Visits": load_health(SH_VISITS),
        "Oura Daily":    load_health(SH_OURA),
    }

    any_data = False
    for label, records in export_map.items():
        p_records = [r for r in records if r.get("Person") == person]
        if not p_records:
            continue
        any_data = True
        clean     = [{k: v for k, v in r.items() if not k.startswith("_")} for r in p_records]
        csv_bytes = pd.DataFrame(clean).to_csv(index=False).encode("utf-8")
        st.download_button(
            label=f"⬇️  {label}  ({len(p_records)} row{'s' if len(p_records) != 1 else ''})",
            data=csv_bytes,
            file_name=f"{person.lower()}_{label.lower().replace(' ', '_')}.csv",
            mime="text/csv",
            key=f"export_{label}",
            use_container_width=True,
        )

    if any_data:
        st.divider()
        # Combined export
        all_rows = []
        for label, records in export_map.items():
            for r in records:
                if r.get("Person") != person:
                    continue
                row = {"Section": label}
                row.update({k: v for k, v in r.items() if not k.startswith("_")})
                all_rows.append(row)
        combined_csv = pd.DataFrame(all_rows).to_csv(index=False).encode("utf-8")
        st.download_button(
            label=f"⬇️  All Records Combined — {person}  ({len(all_rows)} rows)",
            data=combined_csv,
            file_name=f"{person.lower()}_health_records_{date.today().isoformat()}.csv",
            mime="text/csv",
            key="export_all",
            use_container_width=True,
            type="primary",
        )
    else:
        st.info(f"No records found for {person}. Start logging using the tabs above.")
