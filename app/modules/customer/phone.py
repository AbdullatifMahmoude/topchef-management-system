"""Normalize Egyptian phone numbers for consistent lookup/storage."""
from __future__ import annotations

import re

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def normalize_egyptian_phone(phone: str | None) -> str:
    """Return an 11-digit local Egyptian mobile when possible (e.g. 01xxxxxxxxx)."""
    raw = (phone or "").translate(_ARABIC_DIGITS)
    digits = re.sub(r"\D", "", raw)

    if digits.startswith("20") and len(digits) >= 12:
        digits = "0" + digits[2:]
    elif len(digits) == 10 and digits.startswith("1"):
        digits = "0" + digits

    if len(digits) > 11:
        digits = digits[:11]
    return digits


def phone_lookup_candidates(phone: str | None) -> list[str]:
    """Unique phone forms to try when matching legacy / mixed-format rows."""
    normalized = normalize_egyptian_phone(phone)
    raw = (phone or "").strip()
    candidates: list[str] = []
    for value in (
        raw,
        normalized,
        normalized[1:] if normalized.startswith("0") and len(normalized) == 11 else None,
        f"0{normalized}" if len(normalized) == 10 and normalized.startswith("1") else None,
        f"20{normalized[1:]}" if normalized.startswith("0") and len(normalized) == 11 else None,
        f"+20{normalized[1:]}" if normalized.startswith("0") and len(normalized) == 11 else None,
    ):
        if value and value not in candidates:
            candidates.append(value)
    return candidates
