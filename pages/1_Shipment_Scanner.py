"""
Shipment Scanner — TurboLister-style rapid scan-and-price workflow.

1. Create a batch (name + SKU prefix + default cost per book)
2. Scan ISBN → book data auto-fills
3. Pick condition → see Used Buy Box price → match or set custom
4. ADD TO BATCH → field clears → scan next book
"""

import os
import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from utils.sheets import get_spreadsheet
from utils.book_lookup import lookup_isbn
from utils.auth import require_auth

st.set_page_config(
    page_title="Shipment Scanner",
    page_icon="📷",
    layout="centered",
)

require_auth("business")

TIMEZONE   = ZoneInfo("America/Edmonton")
CONDITIONS = ["Acceptable", "Good", "Very Good", "Like New"]

# ─── Load SP-API credentials from .env ────────────────────────────────────────
_here      = os.path.dirname(os.path.abspath(__file__))
_workspace = os.path.dirname(os.path.dirname(_here))
load_dotenv(os.path.join(_workspace, ".env"))

sp_credentials = {
    "refresh_token":     os.getenv("REFRESH_TOKEN"),
    "lwa_app_id":        os.getenv("CLIENT_ID"),
    "lwa_client_secret": os.getenv("CLIENT_SECRET"),
    "aws_access_key":    os.getenv("AWS_ACCESS_KEY_ID"),
    "aws_secret_key":    os.getenv("AWS_SECRET_ACCESS_KEY"),
}


# ─── Amazon pricing helpers ───────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def get_asin_from_isbn(isbn: str) -> str | None:
    """Look up ASIN for an ISBN via SP-API CatalogItems. Returns None on failure."""
    try:
        from sp_api.api import CatalogItems
        from sp_api.base import Marketplaces
        catalog = CatalogItems(credentials=sp_credentials, marketplace=Marketplaces.CA)
        # Try newer search_catalog_items first
        try:
            resp  = catalog.search_catalog_items(
                identifiers=[isbn],
                identifiersType="EAN",
                marketplaceIds=["A2EUQ1WTGCTBG2"],
                includedData=["summaries"],
            )
            items = resp.payload.get("items", [])
            if items:
                return items[0].get("asin")
        except Exception:
            pass
        # Fallback: older list_catalog_items
        resp  = catalog.list_catalog_items(MarketplaceId="A2EUQ1WTGCTBG2", EAN=isbn)
        items = resp.payload.get("Items", {}).get("Item", [])
        if items:
            return items[0].get("Identifiers", {}).get("MarketplaceASIN", {}).get("ASIN")
    except Exception:
        pass
    return None


@st.cache_data(ttl=1800, show_spinner=False)
def get_used_buy_box(asin: str) -> float | None:
    """Return current Used Buy Box landed price (CAD) for an ASIN. None if unavailable."""
    try:
        from sp_api.api import ProductPricing
        from sp_api.base import Marketplaces
        pricing = ProductPricing(credentials=sp_credentials, marketplace=Marketplaces.CA)
        resp    = pricing.get_competitive_pricing(Asins=[asin], ItemType="Asin")
        for item in resp.payload:
            for cp in (item
                       .get("Product", {})
                       .get("CompetitivePricing", {})
                       .get("CompetitivePrices", [])):
                if cp.get("condition", "").lower() == "used":
                    amount = (cp.get("Price", {})
                                .get("LandedPrice", {})
                                .get("Amount"))
                    if amount:
                        return float(amount)
    except Exception:
        pass
    return None


# ─── Sheet helpers ────────────────────────────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def get_existing_batches() -> list[str]:
    try:
        data = get_spreadsheet().worksheet("📦 Book Inventory").get_all_records()
        return sorted(
            {str(r.get("Batch", "")).strip() for r in data if r.get("Batch")},
            reverse=True,
        )
    except Exception:
        return []


@st.cache_data(ttl=30, show_spinner=False)
def get_batch_book_count(batch_name: str) -> int:
    try:
        data = get_spreadsheet().worksheet("📦 Book Inventory").get_all_records()
        return sum(1 for r in data if str(r.get("Batch", "")).strip() == batch_name)
    except Exception:
        return 0


def save_book(book: dict, condition: str, price: float, cost: float,
              batch_name: str, sku_prefix: str, seq: int) -> str:
    sku = f"{sku_prefix}-{seq:03d}"
    get_spreadsheet().worksheet("📦 Book Inventory").append_row([
        book["isbn"],
        book.get("asin", ""),
        book["title"],
        book["author"],
        book["category"],
        condition,
        cost,
        price,
        "Unlisted",
        datetime.now(TIMEZONE).strftime("%Y-%m-%d"),
        "",   # Date Listed
        "",   # Notes
        sku,
        batch_name,
    ], value_input_option="USER_ENTERED")
    return sku


# ─── Session state init ───────────────────────────────────────────────────────

for key, default in [
    ("batch_name",        None),
    ("sku_prefix",        None),
    ("default_cost",      0.25),
    ("session_books",     []),
    ("batch_seq_start",   0),
    ("scan_key",          0),
    ("condition",         "Very Good"),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ─── Page title ───────────────────────────────────────────────────────────────

st.title("📷 Shipment Scanner")


# ─── Step 1: Batch setup ──────────────────────────────────────────────────────

no_batch = st.session_state.batch_name is None
header   = (
    f"📋  {st.session_state.batch_name}  ·  SKU: {st.session_state.sku_prefix}"
    if not no_batch else "⚠️  No batch selected — set one up to start scanning"
)

with st.expander(header, expanded=no_batch):
    tab_new, tab_existing = st.tabs(["➕ New Batch", "📂 Load Existing"])

    with tab_new:
        c1, c2 = st.columns(2)
        b_name   = c1.text_input("Batch Name",   placeholder="e.g.  Feb Week 1")
        b_prefix = c2.text_input("SKU Prefix",   placeholder="e.g.  FW1",
                                  max_chars=8,
                                  help="Short code for SKUs: FW1-001, FW1-002 …")
        b_cost   = st.number_input("Default cost per book ($)",
                                   min_value=0.0, value=0.25,
                                   step=0.25, format="%.2f",
                                   help="Typical cost at Goodwill etc. — can override per book")
        if st.button("✅  Create Batch", type="primary"):
            if b_name and b_prefix:
                st.session_state.batch_name      = b_name.strip()
                st.session_state.sku_prefix      = b_prefix.strip().upper().replace(" ", "")
                st.session_state.default_cost    = float(b_cost)
                st.session_state.session_books   = []
                st.session_state.batch_seq_start = get_batch_book_count(b_name.strip())
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("Enter both a batch name and SKU prefix.")

    with tab_existing:
        existing = get_existing_batches()
        if existing:
            sel = st.selectbox("Batch", existing)
            if st.button("Load"):
                st.session_state.batch_name      = sel
                st.session_state.sku_prefix      = sel.replace(" ", "")[:8].upper()
                st.session_state.session_books   = []
                st.session_state.batch_seq_start = get_batch_book_count(sel)
                st.cache_data.clear()
                st.rerun()
        else:
            st.info("No existing batches yet. Create one above.")

if not st.session_state.batch_name:
    st.stop()


# ─── Batch status bar ─────────────────────────────────────────────────────────

session_count = len(st.session_state.session_books)
total_count   = st.session_state.batch_seq_start + session_count

c1, c2, c3 = st.columns([4, 1, 1])
c1.markdown(f"**Batch:** {st.session_state.batch_name} &nbsp;·&nbsp; "
            f"**Prefix:** `{st.session_state.sku_prefix}`")
c2.metric("Session",  session_count)
c3.metric("Total",    total_count)

st.divider()


# ─── Step 2: ISBN scan ────────────────────────────────────────────────────────

isbn_raw = st.text_input(
    "📷  ISBN — scan or type",
    placeholder="Focus here, then scan barcode...",
    key=f"isbn_{st.session_state.scan_key}",
)

if not isbn_raw:
    st.caption("Scan a barcode or type an ISBN to begin.")
    if st.session_state.session_books:
        st.divider()
        _render_session_list = True
    else:
        st.stop()
        _render_session_list = False
else:
    _render_session_list = True

    isbn = isbn_raw.strip().replace("-", "").replace(" ", "")

    # ── Book lookup ────────────────────────────────────────────────────────────
    with st.spinner("Looking up…"):
        book = lookup_isbn(isbn)

    manual_mode = False
    if not book:
        st.warning(f"Not found in Open Library for **{isbn}** — fill in manually.")
        manual_title  = st.text_input("Title")
        manual_author = st.text_input("Author")
        if not manual_title:
            st.stop()
        book = {"isbn": isbn, "title": manual_title, "author": manual_author,
                "category": "", "cover_url": "", "asin": ""}
        manual_mode = True

    # ── Amazon ASIN + price ────────────────────────────────────────────────────
    if not manual_mode:
        with st.spinner("Checking Amazon price…"):
            asin          = get_asin_from_isbn(isbn) or ""
            book["asin"]  = asin
            buy_box_price = get_used_buy_box(asin) if asin else None
    else:
        asin = ""
        buy_box_price = None

    # ── Book info display ──────────────────────────────────────────────────────
    col_img, col_info = st.columns([1, 5])
    with col_img:
        if book.get("cover_url"):
            st.image(book["cover_url"], width=75)
    with col_info:
        st.markdown(f"### {book['title']}")
        if book["author"]:
            st.caption(book["author"])
        if asin:
            st.caption(f"ASIN: `{asin}`")

    st.divider()

    # ── Condition ──────────────────────────────────────────────────────────────
    st.markdown("**Condition**")
    cond_cols = st.columns(4)
    for i, cond in enumerate(CONDITIONS):
        selected = st.session_state.condition == cond
        if cond_cols[i].button(
            f"✓  {cond}" if selected else cond,
            key=f"cond_{cond}_{st.session_state.scan_key}",
            use_container_width=True,
            type="primary" if selected else "secondary",
        ):
            st.session_state.condition = cond
            st.rerun()

    condition = st.session_state.condition

    # ── Price ──────────────────────────────────────────────────────────────────
    st.markdown("**Price**")

    if buy_box_price:
        price_choice = st.radio(
            "price_radio",
            [f"Match Used Buy Box  —  ${buy_box_price:.2f}",
             "Custom price"],
            label_visibility="collapsed",
        )
        if "Buy Box" in price_choice:
            final_price = buy_box_price
        else:
            final_price = st.number_input(
                "Custom ($)", min_value=0.01,
                value=float(round(buy_box_price, 2)),
                step=0.50, format="%.2f",
            )
    else:
        if not asin:
            st.caption("⚠️  No Amazon listing found for this ISBN — enter price manually.")
        else:
            st.caption("⚠️  No used Buy Box price available — enter manually.")
        final_price = st.number_input(
            "Price ($)", min_value=0.01, value=5.00, step=0.50, format="%.2f"
        )

    # ── Cost ───────────────────────────────────────────────────────────────────
    with st.expander(f"Cost  (default: ${st.session_state.default_cost:.2f})"):
        cost = st.number_input(
            "Cost paid ($)",
            min_value=0.0,
            value=float(st.session_state.default_cost),
            step=0.25, format="%.2f",
        )
    if "cost" not in dir():
        cost = st.session_state.default_cost

    # ── SKU preview ────────────────────────────────────────────────────────────
    next_seq = st.session_state.batch_seq_start + session_count + 1
    next_sku = f"{st.session_state.sku_prefix}-{next_seq:03d}"
    st.caption(f"SKU: `{next_sku}`  ·  Profit est: "
               f"${max(0, final_price * 0.60 - cost):.2f}")

    st.markdown("")

    # ── ADD button ─────────────────────────────────────────────────────────────
    if st.button("✅   ADD TO BATCH", type="primary", use_container_width=True):
        sku = save_book(book, condition, final_price, cost,
                        st.session_state.batch_name,
                        st.session_state.sku_prefix,
                        next_seq)
        st.session_state.session_books.append({
            "SKU":       sku,
            "Title":     book["title"][:40],
            "Condition": condition,
            "Price":     f"${final_price:.2f}",
            "Est. Profit": f"${max(0, final_price * 0.60 - cost):.2f}",
        })
        st.session_state.scan_key += 1   # clears the ISBN field on rerun
        st.cache_data.clear()
        st.rerun()


# ─── Session list (always shown when books exist) ─────────────────────────────

if _render_session_list and st.session_state.session_books:
    st.divider()
    st.subheader(f"Added this session  ({session_count} books)")
    df = pd.DataFrame(st.session_state.session_books[::-1])   # newest first
    st.dataframe(df, use_container_width=True, hide_index=True)
