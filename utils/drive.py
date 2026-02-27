"""
Google Drive helper — uploads receipt images to a shared folder.
Uses the same service account credentials as Google Sheets.
Upload uses google.auth.transport.requests (AuthorizedSession) to avoid
httplib2/WinError 10053 on Windows.
"""

import io
import json
import os
import re

import streamlit as st
from google.oauth2.service_account import Credentials
from google.auth.transport.requests import AuthorizedSession

RECEIPTS_FOLDER_NAME = "Loeppky Receipts 2026"

_DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive",
]


def _get_creds() -> Credentials:
    """Return service account credentials with Drive scope."""
    try:
        creds_info = dict(st.secrets["gcp_service_account"])
        return Credentials.from_service_account_info(creds_info, scopes=_DRIVE_SCOPES)
    except Exception:
        here          = os.path.dirname(os.path.abspath(__file__))
        app_dir       = os.path.dirname(here)
        workspace_dir = os.path.dirname(app_dir)
        creds_path    = os.path.join(workspace_dir, "sheets-credentials.json")
        return Credentials.from_service_account_file(creds_path, scopes=_DRIVE_SCOPES)


def _session() -> AuthorizedSession:
    """Return an AuthorizedSession for Drive API calls."""
    return AuthorizedSession(_get_creds())


def get_receipts_folder_id() -> str:
    """Return the Drive folder ID from env var (required)."""
    env_id = os.getenv("RECEIPTS_FOLDER_ID", "").strip()
    if env_id:
        return env_id
    raise RuntimeError(
        "RECEIPTS_FOLDER_ID not set in .env. "
        "Create a folder in your personal Google Drive, share it with "
        "claude-sheets@claude-assistant-488103.iam.gserviceaccount.com (Editor), "
        "then add RECEIPTS_FOLDER_ID=<folder_id> to your .env file."
    )


def upload_receipt(file_bytes: bytes, filename: str, mime_type: str) -> tuple[str, str]:
    """
    Upload a receipt image/PDF to the Receipts folder.
    Returns (shareable_view_url, file_id).
    """
    session   = _session()
    folder_id = get_receipts_folder_id()

    # Multipart upload: metadata + file body
    metadata = json.dumps({"name": filename, "parents": [folder_id]})
    resp = session.post(
        "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id",
        files={
            "metadata": ("metadata", metadata.encode(), "application/json; charset=UTF-8"),
            "file":     ("file",     file_bytes,         mime_type),
        },
        timeout=60,
    )
    resp.raise_for_status()
    file_id = resp.json()["id"]

    # Make it viewable by anyone with the link
    perm_resp = session.post(
        f"https://www.googleapis.com/drive/v3/files/{file_id}/permissions",
        json={"type": "anyone", "role": "reader"},
        timeout=30,
    )
    perm_resp.raise_for_status()

    view_url = f"https://drive.google.com/file/d/{file_id}/view"
    return view_url, file_id


def file_id_from_url(drive_url: str) -> str:
    """Extract the Google Drive file ID from a /file/d/FILE_ID/view URL."""
    m = re.search(r"/d/([\w-]+)", drive_url)
    return m.group(1) if m else ""


def embed_url(file_id: str) -> str:
    """Return a direct-display URL usable with st.image()."""
    return f"https://drive.google.com/uc?export=view&id={file_id}"
