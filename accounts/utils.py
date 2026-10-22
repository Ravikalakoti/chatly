import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email


def normalize_phone(raw):
    """
    Turn whatever the user typed into a canonical "+<country><number>" string.

    "98765 43210", "09876543210", "+91 98765-43210" -> "+919876543210"
    Returns None if it doesn't look like a phone number.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    has_plus = raw.startswith("+")
    digits = re.sub(r"\D", "", raw)
    if not has_plus and digits.startswith("00"):  # 0091... style international prefix
        digits = digits[2:]
        has_plus = True
    if not has_plus:
        digits = digits.lstrip("0")  # national trunk prefix, e.g. 09876543210
        if len(digits) == 10:  # national number without country code
            digits = f"{settings.DEFAULT_COUNTRY_CODE}{digits}"
    if not 8 <= len(digits) <= 15:
        return None
    return f"+{digits}"


def parse_identifier(value):
    """
    Decide whether the user typed an email or a phone number.
    Returns ("email", normalized) / ("phone", normalized) / (None, None).
    """
    value = (value or "").strip()
    if not value:
        return None, None
    if "@" in value:
        try:
            validate_email(value)
        except ValidationError:
            return None, None
        return "email", value.lower()
    phone = normalize_phone(value)
    if phone:
        return "phone", phone
    return None, None


_EMAIL_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")


def normalize_email(raw):
    """
    Return the cleaned, lower-case email, or None if it isn't a real-looking address.
    Stricter than Django's validate_email: the domain must have a dot and a letters-only
    ending (so "me@localhost" or "me@gmail" are rejected), and no spaces are allowed.
    """
    value = (raw or "").strip().lower()
    if not value or len(value) > 254 or " " in value or value.count("@") != 1:
        return None
    try:
        validate_email(value)
    except ValidationError:
        return None
    local, domain = value.split("@")
    if len(local) > 64 or ".." in local or local.startswith(".") or local.endswith("."):
        return None
    if not _EMAIL_DOMAIN_RE.match(domain):
        return None
    return value
