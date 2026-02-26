"""
Alert utilities for Loeppky app.

Currently supports: Telegram
Future swap: replace _send_telegram() with _send_twilio() and update send_alert().

Telegram setup (one-time, ~5 minutes):
  1. Open Telegram → search @BotFather → /newbot → follow prompts → copy the token
  2. Start a chat with your new bot (search its username, press Start)
  3. Get your chat ID: open https://api.telegram.org/bot<TOKEN>/getUpdates in a browser
     after sending the bot any message — look for "id" inside "chat"
  4. Add to .streamlit/secrets.toml:
       [telegram]
       token   = "123456:ABC-your-bot-token"
       chat_id = "123456789"

Twilio swap (future):
  1. Create Twilio account → get Account SID, Auth Token, and a phone number
  2. Add to secrets.toml:
       [twilio]
       account_sid = "ACxxxx"
       auth_token  = "xxxx"
       from_number = "+1XXXXXXXXXX"
       to_number   = "+1XXXXXXXXXX"
  3. Replace the send_alert() body with _send_twilio()
"""

import urllib.request
import urllib.parse
import json
import streamlit as st


# ── Telegram ───────────────────────────────────────────────────────────────────

def _send_telegram(message: str) -> tuple[bool, str]:
    """Send a message via Telegram bot. Returns (success, error_msg)."""
    try:
        cfg     = dict(st.secrets.get("telegram", {}))
        token   = cfg.get("token", "")
        chat_id = cfg.get("chat_id", "")

        if not token or not chat_id:
            return False, "Telegram not configured in secrets.toml"

        url  = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id":    chat_id,
            "text":       message,
            "parse_mode": "HTML",
        }).encode("utf-8")

        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if result.get("ok"):
                return True, ""
            return False, result.get("description", "Unknown error")
    except Exception as e:
        return False, str(e)


# ── Public API ─────────────────────────────────────────────────────────────────

def send_alert(message: str) -> tuple[bool, str]:
    """
    Send an alert using the configured provider.
    Currently: Telegram. Swap provider here when moving to Twilio.
    """
    return _send_telegram(message)


def alerts_configured() -> bool:
    """Return True if at least one alert provider is configured."""
    try:
        cfg = dict(st.secrets.get("telegram", {}))
        return bool(cfg.get("token") and cfg.get("chat_id"))
    except Exception:
        return False


def check_sleep_alert(person: str, sleep_score: int | float | str) -> None:
    """
    Send a Telegram alert if sleep score is below the configured threshold.
    Call this after importing Oura data.

    Configure threshold in secrets.toml:
      [alerts]
      sleep_score_threshold = 70
    """
    if not alerts_configured():
        return

    try:
        threshold = int(st.secrets.get("alerts", {}).get("sleep_score_threshold", 70))
        score     = int(float(sleep_score))
    except (ValueError, TypeError):
        return

    if score < threshold:
        msg = (
            f"😴 <b>Sleep Alert — {person}</b>\n\n"
            f"Sleep score <b>{score}</b> is below your threshold of <b>{threshold}</b>.\n\n"
            f"Check the Health page for details."
        )
        send_alert(msg)
