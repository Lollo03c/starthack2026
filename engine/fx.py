"""Live FX rate fetching with hardcoded fallback."""
from __future__ import annotations

import logging
import urllib.request
import json

logger = logging.getLogger(__name__)

# Hardcoded fallback rates (vs EUR base)
FALLBACK_RATES = {"EUR": 1.0, "CHF": 0.93, "USD": 1.08}

# Per-run cache: (from, to) → (rate, source)
_cache: dict[tuple[str, str], tuple[float, str]] = {}


def get_fx_rate(from_currency: str, to_currency: str) -> tuple[float, str]:
    """Return (rate, source) such that 1 from_currency = rate * to_currency.

    source is "live (frankfurter.app)" or "fallback (hardcoded)".
    """
    if from_currency == to_currency:
        return 1.0, "identity"

    key = (from_currency, to_currency)
    if key in _cache:
        return _cache[key]

    # Try live rate
    try:
        url = f"https://api.frankfurter.app/latest?from={from_currency}&to={to_currency}"
        req = urllib.request.Request(url, headers={"User-Agent": "ChainIQ/1.0"})
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode())
            rate = float(data["rates"][to_currency])
            source = "live (frankfurter.app)"
            logger.info("FX live rate: 1 %s = %.6f %s", from_currency, rate, to_currency)
            _cache[key] = (rate, source)
            return rate, source
    except Exception as exc:
        logger.warning("FX live rate fetch failed (%s), using fallback", exc)

    # Fallback: convert via EUR base
    from_eur = FALLBACK_RATES.get(from_currency)
    to_eur = FALLBACK_RATES.get(to_currency)
    if from_eur is not None and to_eur is not None and from_eur > 0:
        rate = to_eur / from_eur
    else:
        rate = 1.0
        logger.warning("No fallback rate for %s→%s, using 1.0", from_currency, to_currency)

    source = "fallback (hardcoded)"
    logger.info("FX fallback rate: 1 %s = %.6f %s", from_currency, rate, to_currency)
    _cache[key] = (rate, source)
    return rate, source


def convert(amount: float, from_currency: str, to_currency: str) -> tuple[float, float, str]:
    """Return (converted_amount, rate_used, source)."""
    rate, source = get_fx_rate(from_currency, to_currency)
    return round(amount * rate, 2), rate, source


def clear_cache() -> None:
    """Clear the FX rate cache (useful between test runs)."""
    _cache.clear()
