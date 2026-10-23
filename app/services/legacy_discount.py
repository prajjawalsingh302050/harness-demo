"""Festive discount engine from the 2024 sale. No longer wired into any route."""

FESTIVE_CODES = {"DIWALI24": 0.15, "HOLI24": 0.10, "NEWYEAR24": 0.20}


def apply_festive_discount(amount, code):
    rate = FESTIVE_CODES.get(code.upper(), 0)
    return round(amount * (1 - rate), 2)


def is_festive_code(code):
    return code.upper() in FESTIVE_CODES
