"""
Book metadata lookup via Open Library API.
Single API call returns title, authors, subjects — no key required.
"""

import requests
import streamlit as st


@st.cache_data(ttl=3600)
def lookup_isbn(isbn: str) -> dict | None:
    """
    Look up book data by ISBN using Open Library Books API.
    Returns dict with title, author, category, cover_url — or None if not found.
    """
    isbn = isbn.strip().replace("-", "").replace(" ", "")
    if not isbn:
        return None

    url = (
        f"https://openlibrary.org/api/books"
        f"?bibkeys=ISBN:{isbn}&format=json&jscmd=data"
    )
    try:
        r = requests.get(url, timeout=6)
        if r.status_code != 200:
            return None

        data = r.json()
        key = f"ISBN:{isbn}"
        if key not in data:
            return None

        book = data[key]
        title   = book.get("title", "Unknown Title")
        authors = [a.get("name", "") for a in book.get("authors", [])]
        subjects = [s.get("name", "") for s in book.get("subjects", [])]

        return {
            "isbn":      isbn,
            "title":     title,
            "author":    ", ".join(a for a in authors if a) or "Unknown",
            "category":  subjects[0] if subjects else "",
            "cover_url": f"https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg",
        }
    except Exception:
        return None
