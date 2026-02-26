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
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from utils.sheets import get_spreadsheet

# ── Constants ──────────────────────────────────────────────────────────────────

USERS_SHEET   = "👤 Users"
USERS_HEADERS = [
    "Username", "Name", "Email", "Password Hash",
    "Role", "Verified", "Verify Token", "Created At",
]

ROLE_ADMIN    = "admin"
ROLE_BUSINESS = "business"
ROLE_PERSONAL = "personal"

_SK_USER   = "_auth_username"
_SK_NAME   = "_auth_name"
_SK_ROLE   = "_auth_role"
_SK_HEALTH = "_auth_health"


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
            for k in (_SK_USER, _SK_NAME, _SK_ROLE, _SK_HEALTH):
                st.session_state.pop(k, None)
            st.rerun()


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

    if username and role:
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
                        st.session_state[_SK_USER] = u["Username"]
                        st.session_state[_SK_NAME] = u["Name"]
                        st.session_state[_SK_ROLE] = r
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
