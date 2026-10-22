"""
Email one-time codes for signup and login.

Nothing is stored in the database: the pending code (as an HMAC, never the
plain code) lives in the visitor's session until it is verified or expires.
"""
import hashlib
import hmac
import logging
import secrets
import time

import requests
from django.conf import settings
from django.core.cache import cache
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)

SESSION_KEY = "otp_pending"
OTP_TTL = 5 * 60  # seconds the code stays valid
RESEND_COOLDOWN = 60  # seconds before another code can be requested
MAX_ATTEMPTS = 5

BREVO_URL = "https://api.brevo.com/v3/smtp/email"


def send_brevo_email(to_email, subject, html_content, text_content):
    """Send one transactional email through Brevo. Returns True on success."""
    api_key = settings.BREVO_API_KEY

    if not api_key:
        logger.error("BREVO_API_KEY is not set; email to %s not sent", to_email)
        return False
    payload = {
        "sender": {"name": "Chatly", "email": settings.DEFAULT_FROM_EMAIL},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_content,
        "textContent": text_content,
    }
    try:
        response = requests.post(
            BREVO_URL,
            headers={"accept": "application/json", "api-key": api_key, "content-type": "application/json"},
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        return True
    except requests.HTTPError as exc:
        logger.error("Brevo error %s: %s", exc.response.status_code, exc.response.text)
    except requests.RequestException:
        logger.exception("Brevo request failed")
    return False


class OtpLimitReached(Exception):
    """Raised when an email address has used up its emails for today."""


DAY = 24 * 60 * 60
_LABELS = {
    "login": "login codes",
    "signup": "signup codes",
    "verify_email": "email verification requests",
    "password_reset": "password reset emails",
}


def _limit_key(purpose, email):
    return "emaillimit:" + hashlib.sha256(f"{purpose}:{email.lower()}".encode()).hexdigest()


def check_limit(purpose, email):
    """Raise OtpLimitReached if `email` already got the daily maximum for `purpose`."""
    limit = settings.OTP_DAILY_LIMITS.get(purpose)
    if not limit:
        return
    entry = cache.get(_limit_key(purpose, email))
    if entry and entry["count"] >= limit:
        left = max(int(entry["first"] + DAY - time.time()), 60)
        hours, minutes = left // 3600, (left % 3600) // 60
        wait = f"{hours}h {minutes}m" if hours else f"{minutes} min"
        label = _LABELS.get(purpose, "emails")
        raise OtpLimitReached(f"You've used all {limit} {label} for today. Try again in {wait}.")


def record_send(purpose, email):
    """Count one successfully sent email."""
    if not settings.OTP_DAILY_LIMITS.get(purpose):
        return
    key = _limit_key(purpose, email)
    entry = cache.get(key)
    now = time.time()
    if not entry or now >= entry["first"] + DAY:
        entry = {"count": 0, "first": now}
    entry["count"] += 1
    cache.set(key, entry, timeout=max(int(entry["first"] + DAY - now), 60))


def _hash(code):
    return hmac.new(settings.SECRET_KEY.encode(), code.encode(), hashlib.sha256).hexdigest()


def _send_code(email, name, code, purpose):
    ctx = {"name": name, "code": code, "purpose": purpose, "minutes": OTP_TTL // 60}
    subject = "Your Chatly login code" if purpose == "login" else "Your Chatly verification code"
    ctx["subject"] = subject
    html = render_to_string("accounts/otp_email.html", ctx)
    text = render_to_string("accounts/otp_email.txt", ctx)
    if not settings.BREVO_API_KEY and settings.DEBUG:
        # Local development without Brevo: show the code in the server console.
        logger.warning("DEV OTP for %s: %s", email, code)
        print(f"\n[Chatly dev] OTP for {email}: {code}\n")
        return True
    return send_brevo_email(email, subject, html, text)


def start(request, *, purpose, email, name="", user_id=None, signup=None, next_url=""):
    """Create + email a fresh code and remember it in the session. Returns True if sent."""
    check_limit(purpose, email)  # may raise OtpLimitReached
    code = f"{secrets.randbelow(10**6):06d}"
    if not _send_code(email, name, code, purpose):
        return False
    record_send(purpose, email)
    request.session[SESSION_KEY] = {
        "purpose": purpose,
        "email": email,
        "name": name,
        "user_id": user_id,
        "signup": signup,
        "next": next_url,
        "hash": _hash(code),
        "expires": time.time() + OTP_TTL,
        "resend_at": time.time() + RESEND_COOLDOWN,
        "attempts": 0,
    }
    return True


def pending(request):
    return request.session.get(SESSION_KEY)


def clear(request):
    request.session.pop(SESSION_KEY, None)


def resend(request):
    """Returns (ok, message)."""
    data = pending(request)
    if not data:
        return False, "Your session expired. Please start again."
    wait = int(data["resend_at"] - time.time())
    if wait > 0:
        return False, f"Please wait {wait}s before requesting a new code."
    try:
        ok = start(
            request,
            purpose=data["purpose"],
            email=data["email"],
            name=data["name"],
            user_id=data["user_id"],
            signup=data["signup"],
            next_url=data["next"],
        )
    except OtpLimitReached as exc:
        return False, str(exc)
    return (True, "A new code is on its way.") if ok else (False, "We couldn't send the email. Please try again.")


def check(request, code):
    """Returns (ok, error_message). Counts failed attempts and expires the code."""
    data = pending(request)
    if not data:
        return False, "Your session expired. Please start again."
    if time.time() > data["expires"]:
        clear(request)
        return False, "That code has expired. Please start again."
    if data["attempts"] >= MAX_ATTEMPTS:
        clear(request)
        return False, "Too many wrong attempts. Please start again."
    if not hmac.compare_digest(_hash((code or "").strip()), data["hash"]):
        data["attempts"] += 1
        request.session[SESSION_KEY] = data
        left = MAX_ATTEMPTS - data["attempts"]
        return False, f"Incorrect code. {left} attempt{'s' if left != 1 else ''} left."
    return True, ""
