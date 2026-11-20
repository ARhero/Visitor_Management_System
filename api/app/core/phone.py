import phonenumbers


def normalize_phone(raw: str, default_region: str = "IN") -> str:
    """Return E.164 (``+919876543210``) or raise ValueError."""
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Phone number is required")
    try:
        num = phonenumbers.parse(raw, default_region)
    except phonenumbers.NumberParseException as exc:
        raise ValueError("Invalid phone number") from exc
    if not phonenumbers.is_valid_number(num):
        raise ValueError("Invalid phone number")
    return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
