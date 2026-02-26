"""
User authentication for Loeppky.

Users are stored in the '👤 Users' Google Sheet with columns:
  Username | Name | Email | Password Hash | Role | Verified | Verify Token | Created At

Roles:
  admin    → all business pages + health
  business → business pages only
  personal → health only

The first user to register automatically becomes admin (Colin should register first).
Email verification is sent if SMTP is configured in .streamlit/secrets.toml [smtp].
If email isn't set up, manually set Verified = Yes in the Users sheet.
"""

import streamlit as st
import bcrypt
import secrets
import smtplib
import json
import hmac as _hmac_mod
import hashlib
import time
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from utils.sheets import get_spreadsheet
try:
    import extra_streamlit_components as stx
    _COOKIES_AVAILABLE = True
except ImportError:
    _COOKIES_AVAILABLE = False

# ── Constants ──────────────────────────────────────────────────────────────────

USERS_SHEET   = "👤 Users"
USERS_HEADERS = [
    "Username", "Name", "Email", "Password Hash",
    "Role", "Verified", "Verify Token", "Created At",
]

LOG_SHEET   = "📋 Login Log"
LOG_HEADERS = ["Timestamp", "Username", "Name", "Role", "Action"]

ROLE_ADMIN    = "admin"
ROLE_BUSINESS = "business"
ROLE_PERSONAL = "personal"

_SK_USER    = "_auth_username"
_SK_NAME    = "_auth_name"
_SK_ROLE    = "_auth_role"
_SK_HEALTH  = "_auth_health"
_SK_EXPIRES = "_auth_expires"

_SESSION_HOURS  = 6
_COOKIE_NAME    = "loeppky_auth"
_ALL_SK = (_SK_USER, _SK_NAME, _SK_ROLE, _SK_HEALTH, _SK_EXPIRES)


# ── Cookie-based session helpers ───────────────────────────────────────────────

def _session_secret() -> str:
    try:
        return str(st.secrets["session"]["secret"])
    except Exception:
        return "loeppky-session-2026-default"


def _make_token(username: str, name: str, role: str) -> str:
    exp = int(time.time()) + _SESSION_HOURS * 3600
    payload = json.dumps({"u": username, "n": name, "r": role, "exp": exp}, separators=(",", ":"))
    sig = _hmac_mod.new(_session_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.b64encode(f"{payload}|{sig}".encode()).decode()


def _verify_token(token: str) -> dict | None:
    try:
        raw = base64.b64decode(token.encode()).decode()
        payload_str, sig = raw.rsplit("|", 1)
        expected = _hmac_mod.new(_session_secret().encode(), payload_str.encode(), hashlib.sha256).hexdigest()
        if not _hmac_mod.compare_digest(sig, expected):
            return None
        payload = json.loads(payload_str)
        if time.time() > payload["exp"]:
            return None
        return payload
    except Exception:
        return None


def _cm():
    if not _COOKIES_AVAILABLE:
        return None
    return stx.CookieManager(key="loeppky_cm")


# ── Sheet helpers ──────────────────────────────────────────────────────────────

def _users_ws():
    ss = get_spreadsheet()
    try:
        return ss.worksheet(USERS_SHEET)
    except Exception:
        ws = ss.add_worksheet(title=USERS_SHEET, rows=200, cols=len(USERS_HEADERS))
        ws.append_row(USERS_HEADERS)
        return ws


def _load_users() -> list[dict]:
    try:
        return _users_ws().get_all_records()
    except Exception:
        return []


def _append_user(username, name, email, pw_hash, role, verified, token, created):
    _users_ws().append_row([username, name, email, pw_hash, role, verified, token, created])


def _update_user(row_idx: int, **kwargs):
    """Update specific columns in a user row (kwargs keys must match USERS_HEADERS)."""
    ws = _users_ws()
    for col_name, value in kwargs.items():
        col_idx = USERS_HEADERS.index(col_name) + 1
        ws.update_cell(row_idx, col_idx, value)


def _find_user(username: str) -> dict | None:
    for i, u in enumerate(_load_users(), start=2):
        if u.get("Username", "").lower() == username.lower():
            return {**u, "_row": i}
    return None


def _log_event(username: str, name: str, role: str, action: str):
    """Append a login/logout event to the Login Log sheet."""
    try:
        ss = get_spreadsheet()
        try:
            ws = ss.worksheet(LOG_SHEET)
        except Exception:
            ws = ss.add_worksheet(title=LOG_SHEET, rows=2000, cols=len(LOG_HEADERS))
            ws.append_row(LOG_HEADERS)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ws.append_row([ts, username, name, role, action])
    except Exception:
        pass  # Never block login/logout due to logging failure


def _find_by_token(token: str) -> dict | None:
    if not token:
        return None
    for i, u in enumerate(_load_users(), start=2):
        if u.get("Verify Token") == token:
            return {**u, "_row": i}
    return None


# ── Password hashing ───────────────────────────────────────────────────────────

def _hash_pw(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _check_pw(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False


# ── Email ──────────────────────────────────────────────────────────────────────

def _send_verify_email(name: str, email: str, token: str) -> tuple[bool, str]:
    try:
        cfg      = dict(st.secrets.get("smtp", {}))
        sender   = cfg.get("username", "")
        password = cfg.get("password", "")
        host     = cfg.get("server", "smtp.gmail.com")
        port     = int(cfg.get("port", 587))
        app_url  = cfg.get("app_url", "http://localhost:8501").rstrip("/")

        if not sender or not password:
            return False, "SMTP not configured"

        link = f"{app_url}/?verify={token}"

        msg            = MIMEMultipart("alternative")
        msg["Subject"] = "Verify your Loeppky account"
        msg["From"]    = sender
        msg["To"]      = email

        text = f"Hi {name},\n\nVerify your Loeppky account:\n{link}\n"
        html = f"""
<p>Hi {name},</p>
<p>Click below to verify your Loeppky account:</p>
<p>
  <a href="{link}"
     style="background:#2d6a9f;color:white;padding:10px 22px;
            text-decoration:none;border-radius:5px;display:inline-block">
    Verify Account
  </a>
</p>
<p style="color:#999;font-size:12px">Or copy this link:<br>{link}</p>
"""
        msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(host, port) as srv:
            srv.starttls()
            srv.login(sender, password)
            srv.sendmail(sender, email, msg.as_string())

        return True, ""
    except Exception as e:
        return False, str(e)


# ── Registration / verification ────────────────────────────────────────────────

def _register(username: str, name: str, email: str, password: str) -> tuple[bool, str]:
    users = _load_users()

    for u in users:
        if u.get("Username", "").lower() == username.lower():
            return False, "Username already taken."
        if u.get("Email", "").lower() == email.lower():
            return False, "Email already registered."

    # First user on an empty sheet becomes admin
    role    = ROLE_ADMIN if not users else ROLE_PERSONAL
    pw_hash = _hash_pw(password)
    token   = secrets.token_urlsafe(32)
    created = datetime.now().strftime("%Y-%m-%d %H:%M")

    _append_user(username, name, email, pw_hash, role, "No", token, created)

    ok, err = _send_verify_email(name, email, token)
    if ok:
        return True, (
            f"Account created! A verification email has been sent to **{email}**. "
            f"Click the link in the email to activate your account."
        )
    else:
        admin_note = " You are the first user and will be **admin** (access to everything)." if role == ROLE_ADMIN else ""
        return True, (
            f"Account created.{admin_note} "
            f"Email could not be sent ({err or 'SMTP not configured'}). "
            f"To activate: open the **👤 Users** sheet in Google Sheets and "
            f"set your **Verified** column to **Yes**."
        )


def _verify(token: str) -> tuple[bool, str]:
    u = _find_by_token(token)
    if not u:
        return False, "Invalid or expired verification link."
    if u.get("Verified") == "Yes":
        return True, "Account already verified — you can sign in."
    _update_user(u["_row"], **{"Verified": "Yes", "Verify Token": ""})
    return True, "Email verified! You can now sign in."


# ── Health password ────────────────────────────────────────────────────────────

def _get_health_password() -> str:
    try:
        return str(st.secrets["passwords"]["health"])
    except Exception:
        return "family2026"


def _health_lock_prompt():
    """Show the health password prompt. Calls st.stop() until unlocked."""
    _, card, _ = st.columns([1, 1.6, 1])
    with card:
        st.markdown("## 🏥 Family Health")
        st.markdown("---")
        st.caption("Enter the health password to access this section.")
        hw = st.text_input("Health password", type="password",
                           placeholder="Enter health password", key="_hp_pw")
        if st.button("Unlock", type="primary",
                     use_container_width=True, key="_hp_btn"):
            if hw == _get_health_password():
                st.session_state[_SK_HEALTH] = True
                st.rerun()
            else:
                st.error("Incorrect health password.")
    st.stop()


# ── Sidebar ────────────────────────────────────────────────────────────────────

def _sidebar():
    name = st.session_state.get(_SK_NAME) or st.session_state.get(_SK_USER, "")
    role = st.session_state.get(_SK_ROLE, "")
    with st.sidebar:
        st.caption(f"👤 {name}  ·  {role}")
        if st.button("Logout", key="_sb_logout"):
            _log_event(
                st.session_state.get(_SK_USER, ""),
                st.session_state.get(_SK_NAME, ""),
                st.session_state.get(_SK_ROLE, ""),
                "Logout",
            )
            try:
                cm = _cm()
                if cm is not None:
                    cm.delete(_COOKIE_NAME)
            except Exception:
                pass
            for k in _ALL_SK:
                st.session_state.pop(k, None)
            st.rerun()


# ── Profile helpers ────────────────────────────────────────────────────────────

def get_current_user() -> dict | None:
    """Return the logged-in user's record from the sheet, or None."""
    username = st.session_state.get(_SK_USER)
    if not username:
        return None
    return _find_user(username)


def change_password(username: str, current_pw: str, new_pw: str) -> tuple[bool, str]:
    """Verify current password then update hash in sheet."""
    u = _find_user(username)
    if not u:
        return False, "User not found."
    if not _check_pw(current_pw, u.get("Password Hash", "")):
        return False, "Current password is incorrect."
    _update_user(u["_row"], **{"Password Hash": _hash_pw(new_pw)})
    return True, "Password updated successfully."


def update_display_name(username: str, new_name: str) -> tuple[bool, str]:
    """Update the display name for a user."""
    u = _find_user(username)
    if not u:
        return False, "User not found."
    _update_user(u["_row"], **{"Name": new_name.strip()})
    st.session_state[_SK_NAME] = new_name.strip()
    return True, "Name updated."


# ── Public API ─────────────────────────────────────────────────────────────────

def require_auth(level: str = "business"):
    """
    Enforce authentication and role-based access.
    Shows login/register form and calls st.stop() if not authenticated.

    level: "business" | "personal"

    Role access matrix:
      admin    → business ✓  personal ✓
      business → business ✓  personal ✗
      personal → business ✗  personal ✓
    """
    username = st.session_state.get(_SK_USER)
    role     = st.session_state.get(_SK_ROLE)

    # Expire session after _SESSION_HOURS of inactivity
    expires = st.session_state.get(_SK_EXPIRES)
    if username and expires and datetime.now() > expires:
        for k in _ALL_SK:
            st.session_state.pop(k, None)
        username = None
        role = None

    # Try to restore session from browser cookie (survives server restarts/deploys)
    if not username:
        try:
            cm  = _cm()
            raw = cm.get(_COOKIE_NAME) if cm is not None else None
            if raw:
                payload = _verify_token(str(raw))
                if payload:
                    st.session_state[_SK_USER]    = payload["u"]
                    st.session_state[_SK_NAME]    = payload["n"]
                    st.session_state[_SK_ROLE]    = payload["r"]
                    st.session_state[_SK_EXPIRES] = datetime.now() + timedelta(hours=_SESSION_HOURS)
                    username = payload["u"]
                    role     = payload["r"]
        except Exception:
            pass  # Cookie component not yet loaded — will retry on next rerun

    if username and role:
        # Refresh expiry on each active page load
        st.session_state[_SK_EXPIRES] = datetime.now() + timedelta(hours=_SESSION_HOURS)
        if level == "business" and role not in (ROLE_BUSINESS, ROLE_ADMIN):
            st.error("🔒 This section requires a business account. Contact Colin to upgrade your access.")
            st.stop()
        if level == "personal" and role not in (ROLE_PERSONAL, ROLE_ADMIN):
            st.error("🔒 This section requires a Health account. Contact Colin to get access.")
            st.stop()
        # Health section always requires the separate health password, even for admins
        if level == "personal" and not st.session_state.get(_SK_HEALTH):
            _sidebar()
            _health_lock_prompt()
        _sidebar()
        return

    # ── Check for email verification token in URL ──────────────────────────
    v_token = st.query_params.get("verify")
    if v_token:
        ok, msg = _verify(v_token)
        st.query_params.clear()
        if ok:
            st.success(msg)
        else:
            st.error(msg)

    # ── Login / Register form ──────────────────────────────────────────────
    _, card, _ = st.columns([1, 1.8, 1])
    with card:
        st.markdown("## 📚 Loeppky")
        st.markdown("---")

        tab_in, tab_reg = st.tabs(["Sign In", "Create Account"])

        # ── Sign In ───────────────────────────────────────────────────────
        with tab_in:
            u_in = st.text_input("Username", key="_li_user")
            p_in = st.text_input("Password", type="password",
                                 placeholder="Enter password", key="_li_pw")

            if st.button("Sign In", type="primary",
                         use_container_width=True, key="_li_btn"):
                u = _find_user(u_in.strip())
                if not u:
                    st.error("Incorrect username or password.")
                elif u.get("Verified") != "Yes":
                    st.warning(
                        "Please verify your email before signing in. "
                        "Check your inbox for the verification link."
                    )
                elif not _check_pw(p_in, u.get("Password Hash", "")):
                    st.error("Incorrect username or password.")
                else:
                    r = u.get("Role", ROLE_PERSONAL)
                    if level == "business" and r not in (ROLE_BUSINESS, ROLE_ADMIN):
                        st.error(
                            "Your account only has access to the Health section. "
                            "Contact Colin for business access."
                        )
                    else:
                        st.session_state[_SK_USER]    = u["Username"]
                        st.session_state[_SK_NAME]    = u["Name"]
                        st.session_state[_SK_ROLE]    = r
                        st.session_state[_SK_EXPIRES] = datetime.now() + timedelta(hours=_SESSION_HOURS)
                        try:
                            cm = _cm()
                            if cm is not None:
                                cm.set(
                                    _COOKIE_NAME,
                                    _make_token(u["Username"], u["Name"], r),
                                    expires_at=datetime.now() + timedelta(hours=_SESSION_HOURS),
                                )
                        except Exception:
                            pass
                        _log_event(u["Username"], u["Name"], r, "Login")
                        st.rerun()

        # ── Create Account ────────────────────────────────────────────────
        with tab_reg:
            st.caption("New here? Create your account below.")
            r_user  = st.text_input("Username",               key="_rg_user")
            r_name  = st.text_input("Your name",              key="_rg_name")
            r_email = st.text_input("Email address",          key="_rg_email")
            r_pw    = st.text_input("Password (min 8 chars)", type="password", key="_rg_pw")
            r_pw2   = st.text_input("Confirm password",       type="password", key="_rg_pw2")

            if st.button("Create Account", type="primary",
                         use_container_width=True, key="_rg_btn"):
                if not all([r_user, r_name, r_email, r_pw, r_pw2]):
                    st.error("All fields are required.")
                elif r_pw != r_pw2:
                    st.error("Passwords don't match.")
                elif len(r_pw) < 8:
                    st.error("Password must be at least 8 characters.")
                else:
                    ok, msg = _register(
                        r_user.strip(), r_name.strip(),
                        r_email.strip(), r_pw,
                    )
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)

    st.stop()
