import logging

log = logging.getLogger("app.pricing")

DEFAULT_TAX = 0.18
REGION_TAX = {
    "Delhi": 0.18,
    "Mumbai": 0.18,
    "Bengaluru": 0.18,
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
