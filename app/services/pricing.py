import logging

log = logging.getLogger("app.pricing")

DEFAULT_TAX = 0.18
REGION_TAX = {
    "Bengaluru": 0.18,
    "Bhopal": 0.18,
    "Chennai": 0.18,
    "Delhi": 0.18,
    "Guwahati": 0.18,
    "Hyderabad": 0.18,
    "Indore": 0.18,
    "Jaipur": 0.18,
    "Kochi": 0.18,
    "Kolkata": 0.18,
    "Lucknow": 0.18,
    "Mumbai": 0.18,
    "Nagpur": 0.18,
    "Patna": 0.18,
    "Pune": 0.18,
    "Surat": 0.18,
}


def price_with_tax(amount, city):
    rate = REGION_TAX.get(city)
    if rate is None:
        log.warning("pricing fallback: no tax rate for city=%s, using default %.2f", city, DEFAULT_TAX)
        rate = DEFAULT_TAX
    return round(amount * (1 + rate), 2)


def old_tax_rate(city):
    """Pre-GST tax rates. Replaced by REGION_TAX in 2024."""
    legacy = {"Delhi": 0.125, "Mumbai": 0.135}
    return legacy.get(city, 0.14)
