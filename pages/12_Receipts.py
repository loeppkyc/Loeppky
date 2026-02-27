"""
Receipts — Hubdoc-style receipt capture, AI OCR, and transaction matching.

Workflow:
  1. Upload receipt photo (iPhone JPEG/PNG, or PDF invoice)
  2. Claude Vision auto-extracts vendor, date, amounts (needs ANTHROPIC_API_KEY)
  3. Smart-match to an existing Business Transaction
  4. Save → image stored in Google Drive, transaction marked Hubdoc = Y
  5. Bookkeeper reviews in the Bookkeeper View tab with Drive links
"""

import base64
import io
import json
import os
import re

import pandas as pd
import streamlit as st
from datetime import date, datetime
from dotenv import load_dotenv

load_dotenv()  # load .env file so os.getenv() picks up ANTHROPIC_API_KEY

from utils.auth import require_auth
from utils.drive import upload_receipt, file_id_from_url, embed_url
from utils.sheets import get_spreadsheet

# ── optional Anthropic import ─────────────────────────────────────────────────
try:
    import anthropic as _anthropic_lib
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

# ── page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Receipts",
    page_icon="📸",
    layout="wide",
)

require_auth("business")

# ── constants ─────────────────────────────────────────────────────────────────
RECEIPT_HEADERS = [
    "Upload Date", "Receipt Date", "Vendor", "Pre-Tax ($)", "GST ($)",
    "Total ($)", "Category", "Drive URL", "Match Status",
    "Matched Txn Row", "Notes",
]

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

MIME_MAP = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "pdf": "application/pdf",
}


# ── sheet helpers ─────────────────────────────────────────────────────────────

def _ws_receipts():
    ss = get_spreadsheet()
    try:
        return ss.worksheet("📸 Receipts")
    except Exception:
        ws = ss.add_worksheet(
            title="📸 Receipts",
            rows=2000,
            cols=len(RECEIPT_HEADERS) + 2,
        )
        ws.append_row(RECEIPT_HEADERS)
        return ws


@st.cache_data(ttl=30)
def load_receipts() -> list[dict]:
    try:
        ws      = get_spreadsheet().worksheet("📸 Receipts")
        records = ws.get_all_records()
        for i, r in enumerate(records, start=2):
            r["_row"] = i
        return records
    except Exception:
        return []


@st.cache_data(ttl=60)
def load_transactions() -> list[dict]:
    try:
        ws       = get_spreadsheet().worksheet("📒 Business Transactions")
        all_vals = ws.get_all_values()
    except Exception:
        return []

    if len(all_vals) < 3:
        return []

    header = all_vals[2]   # real header is row 3 (index 2)
    rows   = []
    for i, raw in enumerate(all_vals[3:], start=4):
        if not any(raw):
            continue
        padded = raw + [""] * max(0, len(header) - len(raw))
        d      = dict(zip(header, padded))
        d["_sheet_row"] = i

        def _f(key):
            try:
                return float(str(d.get(key, 0)).replace(",", "").replace("$", "") or 0)
            except (ValueError, TypeError):
                return 0.0

        d["_pretax"] = _f("Pre-Tax ($)")
        d["_gst"]    = _f("GST ($)")
        d["_total"]  = d["_pretax"] + d["_gst"]

        date_str       = str(d.get("Date", "")).strip()
        d["_month_key"] = date_str[:7] if len(date_str) >= 7 else ""
        if not d["_month_key"]:
            continue
        rows.append(d)
    return rows


# ── OCR ───────────────────────────────────────────────────────────────────────

def _api_key() -> str:
    """Return Anthropic API key from env or Streamlit secrets."""
    env_key = os.getenv("ANTHROPIC_API_KEY", "")
    if env_key:
        return env_key
    try:
        return st.secrets.get("anthropic", {}).get("api_key", "")
    except Exception:
        return ""


def _compress_image(image_bytes: bytes) -> tuple[bytes, str]:
    """Resize image to max 1200px and compress as JPEG. Returns (bytes, mime_type)."""
    from PIL import Image
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    if max(img.size) > 2000:
        img.thumbnail((2000, 2000), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue(), "image/jpeg"


def ocr_receipt(image_bytes: bytes, mime_type: str) -> tuple[dict, str]:
    """
    Use Claude Haiku Vision to extract receipt fields.
    Returns (data_dict, error_message). On success error_message is "".
    """
    key = _api_key()
    if not key or not _ANTHROPIC_AVAILABLE:
        return {}, "API key not found."

    # Compress before sending — phone photos are often 4-8MB (API limit is 5MB)
    try:
        image_bytes, mime_type = _compress_image(image_bytes)
    except Exception as e:
        return {}, f"Image resize failed: {e}"

    b64 = base64.b64encode(image_bytes).decode()
    client = _anthropic_lib.Anthropic(api_key=key)

    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "Extract from this receipt. Return ONLY valid JSON with these exact keys:\n"
                            "- vendor: store or business name\n"
                            "- date: purchase date in YYYY-MM-DD format\n"
                            "- total_paid: the FINAL grand total the customer actually paid. "
                            "Look for a line labeled TOTAL, GRAND TOTAL, AMOUNT DUE, BALANCE DUE, "
                            "VISA, DEBIT, or MASTERCARD near the very bottom of the receipt. "
                            "This is usually the largest dollar amount on the receipt. "
                            "Do NOT return a subtotal, tax amount, or line-item amount — "
                            "return only the single final number the customer was charged.\n"
                            "Use null for any value you cannot find. "
                            "No markdown, no explanation — just the JSON object."
                        ),
                    },
                ],
            }],
        )
        text = resp.content[0].text.strip()
        m    = re.search(r"\{[^}]+\}", text, re.DOTALL)
        if m:
            return json.loads(m.group()), ""
        return {}, f"Claude responded but no JSON found. Raw response: {text[:200]}"
    except Exception as e:
        return {}, str(e)


# ── matching helpers ──────────────────────────────────────────────────────────

def find_matches(
    txns: list[dict],
    total_amount: float,
    receipt_date: str,
    vendor: str = "",
) -> list[dict]:
    """
    Return up to 5 Business Transactions that could match this receipt.
    Criteria: amount within ±$1.50 AND date within ±10 days.
    Already-matched (Hubdoc=Y) rows are excluded.
    """
    if not receipt_date or total_amount <= 0:
        return []
    try:
        rdate = datetime.strptime(receipt_date, "%Y-%m-%d")
    except ValueError:
        return []

    candidates = []
    for txn in txns:
        if str(txn.get("Hubdoc (Y/N)", "N")).strip().upper() == "Y":
            continue
        if abs(txn["_total"] - total_amount) > 1.50:
            continue
        try:
            tdate = datetime.strptime(txn.get("Date", ""), "%Y-%m-%d")
        except ValueError:
            continue
        if abs((rdate - tdate).days) > 10:
            continue

        # Lower score = better match
        score = abs(txn["_total"] - total_amount) * 10 + abs((rdate - tdate).days)

        if vendor:
            v1 = vendor.lower()
            v2 = txn.get("Vendor / Description", "").lower()
            # Word overlap bonus
            if any(w in v2 for w in v1.split() if len(w) > 3) or v1[:6] in v2:
                score -= 5

        copy       = dict(txn)
        copy["_match_score"] = round(score, 2)
        candidates.append(copy)

    return sorted(candidates, key=lambda x: x["_match_score"])[:5]


def mark_txn_matched(txn_row: int, drive_url: str) -> None:
    """Set Hubdoc = Y and append receipt URL to Notes in Business Transactions."""
    ss       = get_spreadsheet()
    t_ws     = ss.worksheet("📒 Business Transactions")
    t_headers = t_ws.row_values(3)  # header is on row 3

    def _col(name, fallback):
        return (t_headers.index(name) + 1) if name in t_headers else fallback

    hubdoc_col = _col("Hubdoc (Y/N)", 8)
    notes_col  = _col("Notes", 9)

    t_ws.update_cell(txn_row, hubdoc_col, "Y")

    existing = t_ws.cell(txn_row, notes_col).value or ""
    note     = f"Receipt: {drive_url}"
    new_notes = f"{existing} | {note}".strip(" | ") if existing else note
    t_ws.update_cell(txn_row, notes_col, new_notes)


def update_receipt_match(receipt_row: int, txn_row: int) -> None:
    """Write Match Status = Matched and Matched Txn Row into the Receipts sheet."""
    r_ws    = get_spreadsheet().worksheet("📸 Receipts")
    headers = r_ws.row_values(1)

    def _col(name, fallback):
        return (headers.index(name) + 1) if name in headers else fallback

    status_col = _col("Match Status", 9)
    txn_col    = _col("Matched Txn Row", 10)

    r_ws.update_cell(receipt_row, status_col, "Matched")
    r_ws.update_cell(receipt_row, txn_col, txn_row)


# ── page ──────────────────────────────────────────────────────────────────────

st.title("📸 Receipts")
st.caption(
    "Upload receipt photos → AI extracts vendor/amounts → "
    "auto-match to Business Transactions → bookkeeper-ready with Drive links."
)

hc1, hc2 = st.columns([6, 1])
with hc2:
    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

receipts = load_receipts()
txns     = load_transactions()

# Header summary metrics
unmatched_r = [r for r in receipts if str(r.get("Match Status", "")).strip() != "Matched"]
matched_r   = [r for r in receipts if str(r.get("Match Status", "")).strip() == "Matched"]
no_rcpt     = [t for t in txns if str(t.get("Hubdoc (Y/N)", "N")).strip().upper() != "Y"]

hm1, hm2, hm3, hm4 = st.columns(4)
hm1.metric("Receipts Uploaded",        len(receipts))
hm2.metric("Matched to Transaction",   len(matched_r))
hm3.metric("Pending Match",            len(unmatched_r))
hm4.metric("Transactions w/o Receipt", len(no_rcpt))

st.divider()

tab_upload, tab_queue, tab_all, tab_bookkeeper = st.tabs([
    "📸 Upload Receipt",
    "🔍 Review Queue",
    "📋 All Receipts",
    "👁️ Bookkeeper View",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — UPLOAD
# ══════════════════════════════════════════════════════════════════════════════

with tab_upload:

    st.subheader("Upload a Receipt")

    key_present = bool(_api_key()) and _ANTHROPIC_AVAILABLE
    if key_present:
        st.success(
            "🤖 Claude OCR enabled — amounts and vendor will be extracted automatically."
        )
    else:
        st.info(
            "💡 Add `ANTHROPIC_API_KEY` to your `.env` or Streamlit secrets to enable "
            "auto-extraction. You can still fill in details manually."
        )

    uploaded = st.file_uploader(
        "Choose a receipt photo or PDF invoice",
        type=["jpg", "jpeg", "png", "pdf"],
        help="Take a photo with your phone → AirDrop/email to yourself → upload here.",
    )

    if uploaded:
        raw_bytes = uploaded.read()
        ext       = uploaded.name.rsplit(".", 1)[-1].lower()
        mime_type = MIME_MAP.get(ext, "image/jpeg")
        is_image  = ext in ("jpg", "jpeg", "png")

        col_img, col_form = st.columns([1, 1])

        # ── Left: preview ──────────────────────────────────────────────────────
        with col_img:
            st.markdown("**Preview**")
            if is_image:
                st.image(raw_bytes, use_container_width=True)
            else:
                st.info("📄 PDF — stored in Drive. No inline preview.")

        # ── Right: form ────────────────────────────────────────────────────────
        with col_form:
            st.markdown("**Receipt Details**")

            # OCR button (only for images)
            ocr_data: dict = {}
            if is_image and key_present:
                if st.button("🤖 Auto-Extract Data", use_container_width=True, key="ocr_btn"):
                    with st.spinner("Reading receipt with Claude Vision…"):
                        ocr_data, ocr_err = ocr_receipt(raw_bytes, mime_type)
                    if ocr_data:
                        st.session_state["_ocr_cache"] = ocr_data
                        # Push values directly into widget state so fields populate
                        def _sv(k):
                            v = ocr_data.get(k)
                            return str(v) if v is not None and str(v).lower() not in ("null", "none", "") else ""
                        def _fv(k):
                            try:
                                return float(str(ocr_data.get(k, "") or "").replace("$","").replace(",","").strip())
                            except (ValueError, TypeError):
                                return None
                        if _sv("vendor"):
                            st.session_state["r_vendor"] = _sv("vendor")
                        # Use total_paid (grand total) then back-calculate at Alberta 5% GST
                        total_paid = _fv("total_paid")
                        if total_paid is not None and total_paid > 0:
                            GST_RATE = 0.05
                            pretax = round(total_paid / (1 + GST_RATE), 2)
                            gst    = round(total_paid - pretax, 2)
                            st.session_state["r_total_paid"] = total_paid
                            st.session_state["r_pretax"]     = pretax
                            st.session_state["r_gst"]        = gst
                        if _sv("date") and len(_sv("date")) == 10:
                            try:
                                st.session_state["r_date"] = datetime.strptime(_sv("date"), "%Y-%m-%d").date()
                            except ValueError:
                                pass
                        st.session_state["_ocr_debug"] = ocr_data
                        st.rerun()  # rerender widgets with OCR values
                    else:
                        st.warning(f"Could not extract data — fill in manually.\n\n**Error:** {ocr_err}")

            # Pull from session cache if user already ran OCR this rerun
            if not ocr_data and st.session_state.get("_ocr_cache"):
                ocr_data = st.session_state["_ocr_cache"]
            elif not isinstance(ocr_data, dict):
                ocr_data = {}

            def _s(key, fallback=""):
                v = ocr_data.get(key)
                return str(v) if v and str(v).lower() != "null" else fallback

            # Initialise widget state defaults on first render (no OCR yet)
            if "r_date"       not in st.session_state: st.session_state["r_date"]       = date.today()
            if "r_vendor"     not in st.session_state: st.session_state["r_vendor"]     = ""
            if "r_total_paid" not in st.session_state: st.session_state["r_total_paid"] = 0.0
            if "r_pretax"     not in st.session_state: st.session_state["r_pretax"]     = 0.0
            if "r_gst"        not in st.session_state: st.session_state["r_gst"]        = 0.0

            # Callback: when user edits Total Paid, auto-recalc pretax + GST at 5%
            def _recalc_from_total():
                tp = st.session_state.get("r_total_paid", 0.0) or 0.0
                if tp > 0:
                    st.session_state["r_pretax"] = round(tp / 1.05, 2)
                    st.session_state["r_gst"]    = round(tp - st.session_state["r_pretax"], 2)

            # Widgets driven entirely by session state — no value= arg to avoid conflicts
            r_date   = st.date_input("Receipt Date", key="r_date")
            r_vendor = st.text_input("Vendor / Store", key="r_vendor")

            r_total_paid = st.number_input(
                "Total Paid ($)",
                min_value=0.0, step=0.01, format="%.2f",
                key="r_total_paid",
                on_change=_recalc_from_total,
                help="The grand total charged — edit this and Pre-Tax/GST auto-update.",
            )
            st.caption("If the total looks wrong, just type the correct amount — Pre-Tax and GST will recalculate automatically.")

            c1, c2 = st.columns(2)
            with c1:
                r_pretax = st.number_input(
                    "Pre-Tax ($)", min_value=0.0, step=0.01, format="%.2f", key="r_pretax",
                )
            with c2:
                r_gst = st.number_input(
                    "GST ($)", min_value=0.0, step=0.01, format="%.2f", key="r_gst",
                )

            r_total = r_pretax + r_gst

            r_category = st.selectbox("Category", CATEGORIES, key="r_category")
            r_notes    = st.text_input("Notes (optional)", key="r_notes")

        # ── Smart matching ─────────────────────────────────────────────────────
        st.divider()
        st.subheader("🔍 Match to a Business Transaction")

        date_str = r_date.strftime("%Y-%m-%d")
        matches  = find_matches(txns, r_total, date_str, r_vendor) if r_total > 0 else []

        selected_txn = None
        if matches:
            st.markdown(
                f"Found **{len(matches)}** candidate(s) for "
                f"**${r_total:.2f}** around **{date_str}**:"
            )
            for i, m in enumerate(matches):
                score = m["_match_score"]
                conf  = "🟢" if score < 3 else ("🟡" if score < 8 else "🔴")
                label = (
                    f"{conf} {m.get('Date', '')} · "
                    f"{m.get('Vendor / Description', '')[:45]} · "
                    f"${m['_total']:.2f} · "
                    f"{m.get('Payment Method', '')} · "
                    f"Row {m['_sheet_row']}"
                )
                if st.checkbox(label, key=f"match_chk_{i}"):
                    selected_txn = m
        elif r_total > 0:
            st.info(
                "No matching transactions found — receipt will save as **Unmatched**. "
                "You can link it later from the Review Queue tab."
            )
        else:
            st.caption("Enter an amount above to search for matching transactions.")

        # ── Save ───────────────────────────────────────────────────────────────
        st.divider()
        save_col, status_col = st.columns([1, 3])

        with save_col:
            save_clicked = st.button("💾 Save Receipt", type="primary",
                                     use_container_width=True, key="save_btn")
        with status_col:
            if selected_txn:
                st.success(
                    f"Will match to: **{selected_txn.get('Date')}** — "
                    f"{selected_txn.get('Vendor / Description', '')}"
                )
            else:
                st.caption("Saving without a match. Link later in Review Queue.")

        if save_clicked:
            if not r_vendor.strip():
                st.error("Please enter a vendor name.")
            else:
                timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_vendor = re.sub(r"[^\w\-]", "_", r_vendor.strip())[:30]
                filename    = f"{date_str}_{safe_vendor}_{timestamp}.{ext}"

                # ── Save receipt data to Sheets ─────────────────────────────────
                with st.spinner("Saving receipt record…"):
                    try:
                        status  = "Matched" if selected_txn else "Unmatched"
                        txn_row = selected_txn["_sheet_row"] if selected_txn else ""

                        ws = _ws_receipts()
                        ws.append_row([
                            datetime.now().strftime("%Y-%m-%d %H:%M"),
                            date_str,
                            r_vendor.strip(),
                            round(r_pretax, 2),
                            round(r_gst, 2),
                            round(r_total, 2),
                            r_category,
                            "",   # Drive URL — fill in manually if needed
                            status,
                            txn_row,
                            r_notes,
                        ])

                        if selected_txn:
                            mark_txn_matched(selected_txn["_sheet_row"], "")

                        st.cache_data.clear()
                        st.session_state.pop("_ocr_cache", None)

                        st.success("✅ Receipt saved!")
                        if selected_txn:
                            st.success("✅ Transaction marked Hubdoc = Y.")

                    except Exception as e:
                        st.error(f"Save failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — REVIEW QUEUE
# ══════════════════════════════════════════════════════════════════════════════

with tab_queue:

    st.subheader("🔍 Receipts Needing a Match")

    pending = [
        r for r in receipts
        if str(r.get("Match Status", "")).strip() != "Matched"
    ]

    if not pending:
        st.success("All uploaded receipts are matched to transactions. Nothing to do!")
    else:
        st.caption(
            f"**{len(pending)}** receipt(s) not yet linked to a Business Transaction."
        )

        for rec in sorted(pending, key=lambda x: x.get("Receipt Date", ""), reverse=True):

            drive_url = rec.get("Drive URL", "")
            file_id   = file_id_from_url(drive_url)
            rec_total = float(rec.get("Total ($)", 0) or 0)

            with st.expander(
                f"{rec.get('Receipt Date', '?')} — "
                f"{rec.get('Vendor', '?')} — "
                f"${rec_total:.2f}",
                expanded=False,
            ):
                eq1, eq2 = st.columns([1, 1])

                with eq1:
                    if file_id:
                        try:
                            st.image(embed_url(file_id), use_container_width=True)
                        except Exception:
                            st.markdown(f"[🔗 View in Drive]({drive_url})")
                    elif drive_url:
                        st.markdown(f"[🔗 Open receipt]({drive_url})")
                    else:
                        st.info("No image stored.")

                with eq2:
                    st.markdown(f"**Date:** {rec.get('Receipt Date', '—')}")
                    st.markdown(f"**Vendor:** {rec.get('Vendor', '—')}")
                    st.markdown(
                        f"**Pre-Tax:** ${float(rec.get('Pre-Tax ($)', 0) or 0):.2f}  ·  "
                        f"**GST:** ${float(rec.get('GST ($)', 0) or 0):.2f}  ·  "
                        f"**Total:** ${rec_total:.2f}"
                    )
                    st.markdown(f"**Category:** {rec.get('Category', '—')}")
                    if rec.get("Notes"):
                        st.markdown(f"**Notes:** {rec['Notes']}")

                    st.divider()

                    # Candidate matches
                    r_date_str = rec.get("Receipt Date", "")
                    r_vendor   = rec.get("Vendor", "")
                    candidates = find_matches(txns, rec_total, r_date_str, r_vendor)

                    if candidates:
                        st.markdown("**Suggested matches from Business Transactions:**")
                        options = {
                            (
                                f"{c.get('Date')} · "
                                f"{c.get('Vendor / Description', '')[:40]} · "
                                f"${c['_total']:.2f} · "
                                f"{c.get('Payment Method', '')} · "
                                f"Row {c['_sheet_row']}"
                            ): c
                            for c in candidates
                        }
                        sel = st.selectbox(
                            "Select transaction to link",
                            ["— skip —"] + list(options.keys()),
                            key=f"q_sel_{rec['_row']}",
                        )
                        if sel != "— skip —":
                            sel_txn = options[sel]
                            if st.button(
                                "✅ Confirm Match",
                                key=f"q_confirm_{rec['_row']}",
                                type="primary",
                            ):
                                with st.spinner("Saving…"):
                                    try:
                                        update_receipt_match(
                                            rec["_row"], sel_txn["_sheet_row"]
                                        )
                                        mark_txn_matched(
                                            sel_txn["_sheet_row"], drive_url
                                        )
                                        st.cache_data.clear()
                                        st.success("Matched!")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Error: {e}")
                    else:
                        st.caption(
                            "No candidate transactions found. "
                            "Log the expense in Business Transactions first, "
                            "then come back here to match."
                        )

                    # Option to delete the receipt record
                    if st.button(
                        "🗑️ Delete this receipt record",
                        key=f"q_del_{rec['_row']}",
                        help="Removes from the Receipts sheet (does not delete the Drive file).",
                    ):
                        try:
                            ws = get_spreadsheet().worksheet("📸 Receipts")
                            ws.delete_rows(rec["_row"])
                            st.cache_data.clear()
                            st.success("Deleted.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — ALL RECEIPTS
# ══════════════════════════════════════════════════════════════════════════════

with tab_all:

    st.subheader("📋 All Receipts")

    if not receipts:
        st.info("No receipts uploaded yet.")
    else:
        fc1, fc2 = st.columns(2)
        with fc1:
            months_avail = sorted(
                {str(r.get("Receipt Date", ""))[:7]
                 for r in receipts if r.get("Receipt Date")},
                reverse=True,
            )
            month_filter = st.selectbox(
                "Filter by month", ["All"] + months_avail, key="all_month"
            )
        with fc2:
            status_filter = st.selectbox(
                "Filter by status", ["All", "Matched", "Unmatched"], key="all_status"
            )

        filtered = receipts
        if month_filter != "All":
            filtered = [
                r for r in filtered
                if str(r.get("Receipt Date", "")).startswith(month_filter)
            ]
        if status_filter != "All":
            filtered = [
                r for r in filtered
                if str(r.get("Match Status", "")) == status_filter
            ]

        ac1, ac2, ac3, ac4 = st.columns(4)
        ac1.metric("Showing",       len(filtered))
        ac2.metric("Total Spend",   f"${sum(float(r.get('Total ($)', 0) or 0) for r in filtered):,.2f}")
        ac3.metric("GST (ITCs)",    f"${sum(float(r.get('GST ($)', 0) or 0) for r in filtered):,.2f}")
        ac4.metric("Matched",       sum(1 for r in filtered if r.get("Match Status") == "Matched"))

        st.divider()

        display = []
        for r in sorted(filtered, key=lambda x: x.get("Receipt Date", ""), reverse=True):
            display.append({
                "Date":        r.get("Receipt Date", ""),
                "Vendor":      r.get("Vendor", ""),
                "Pre-Tax ($)": f"${float(r.get('Pre-Tax ($)', 0) or 0):.2f}",
                "GST ($)":     f"${float(r.get('GST ($)', 0) or 0):.2f}",
                "Total ($)":   f"${float(r.get('Total ($)', 0) or 0):.2f}",
                "Category":    r.get("Category", ""),
                "Status":      r.get("Match Status", ""),
                "Receipt":     r.get("Drive URL", ""),
                "Notes":       r.get("Notes", ""),
            })

        st.dataframe(
            pd.DataFrame(display),
            hide_index=True,
            use_container_width=True,
            column_config={
                "Receipt": st.column_config.LinkColumn(
                    "Receipt", display_text="📎 View"
                ),
            },
        )

        csv = pd.DataFrame(display).to_csv(index=False).encode("utf-8")
        st.download_button(
            f"⬇️ Export ({len(filtered)} rows)",
            data=csv,
            file_name=f"receipts_{date.today().isoformat()}.csv",
            mime="text/csv",
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — BOOKKEEPER VIEW
# ══════════════════════════════════════════════════════════════════════════════

with tab_bookkeeper:

    st.subheader("👁️ Bookkeeper View")
    st.caption(
        "Monthly summary with clickable Drive links. "
        "Share this URL with your bookkeeper — they can open each receipt image directly."
    )

    if not receipts:
        st.info("No receipts uploaded yet.")
    else:
        months_bk = sorted(
            {str(r.get("Receipt Date", ""))[:7]
             for r in receipts if r.get("Receipt Date")},
            reverse=True,
        )

        # YTD summary at top
        bk1, bk2, bk3, bk4 = st.columns(4)
        bk1.metric("Total Receipts",  len(receipts))
        bk2.metric("Total Spend",     f"${sum(float(r.get('Total ($)', 0) or 0) for r in receipts):,.2f}")
        bk3.metric("Total GST Paid",  f"${sum(float(r.get('GST ($)', 0) or 0) for r in receipts):,.2f}")
        bk4.metric("Unmatched",       len(unmatched_r),
                   delta_color="off" if not unmatched_r else "inverse")

        st.divider()

        for mk in months_bk:
            mo_recs     = [r for r in receipts if str(r.get("Receipt Date", "")).startswith(mk)]
            mo_matched  = sum(1 for r in mo_recs if r.get("Match Status") == "Matched")
            mo_total    = sum(float(r.get("Total ($)", 0) or 0) for r in mo_recs)
            mo_gst      = sum(float(r.get("GST ($)", 0) or 0) for r in mo_recs)
            match_icon  = "✅" if mo_matched == len(mo_recs) else "⚠️"

            with st.expander(
                f"{match_icon} **{mk}** — {len(mo_recs)} receipts — "
                f"${mo_total:,.2f} spend — {mo_matched}/{len(mo_recs)} matched",
                expanded=(mk == months_bk[0]),
            ):
                bc1, bc2, bc3 = st.columns(3)
                bc1.metric("Receipts",     len(mo_recs))
                bc2.metric("Total Spend",  f"${mo_total:,.2f}")
                bc3.metric("GST (ITCs)",   f"${mo_gst:,.2f}")

                st.divider()

                # Receipt list with Drive links
                for r in sorted(mo_recs, key=lambda x: x.get("Receipt Date", "")):
                    status_icon = "✅" if r.get("Match Status") == "Matched" else "⚠️"
                    drive_url   = r.get("Drive URL", "")
                    link_str    = f"[📎 Receipt]({drive_url})" if drive_url else "—"
                    vendor_str  = r.get("Vendor", "—")[:40]
                    total_str   = f"${float(r.get('Total ($)', 0) or 0):.2f}"
                    cat_str     = r.get("Category", "")

                    st.markdown(
                        f"{status_icon} **{r.get('Receipt Date', '')}** · "
                        f"{vendor_str} · "
                        f"{total_str} · "
                        f"_{cat_str}_ · "
                        f"{link_str}"
                    )

                st.divider()

                # Spend by category for this month
                cats = {}
                for r in mo_recs:
                    c = r.get("Category", "Other")
                    cats[c] = cats.get(c, 0) + float(r.get("Total ($)", 0) or 0)

                if cats:
                    st.markdown("**By Category**")
                    cat_df = pd.DataFrame([
                        {"Category": k, "Spend ($)": round(v, 2)}
                        for k, v in sorted(cats.items(), key=lambda x: x[1], reverse=True)
                    ])
                    st.dataframe(cat_df, hide_index=True, use_container_width=True)

                # Unmatched warning
                unmatched_mo = [r for r in mo_recs if r.get("Match Status") != "Matched"]
                if unmatched_mo:
                    st.warning(
                        f"{len(unmatched_mo)} receipt(s) not yet matched to a transaction. "
                        "Go to **Review Queue** tab to link them."
                    )
