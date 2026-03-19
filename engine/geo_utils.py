"""
Country → region and country → currency helpers.
All lookups are O(1) dict operations on module-level constants.
"""
from __future__ import annotations

COUNTRY_TO_REGION: dict[str, str] = {
    "DE": "EU", "FR": "EU", "NL": "EU", "BE": "EU", "AT": "EU",
    "IT": "EU", "ES": "EU", "PL": "EU", "UK": "EU",
    "IE": "EU",   # Ireland — in suppliers' service_regions, treat as EU
    "CH": "CH",
    "US": "Americas", "CA": "Americas", "BR": "Americas", "MX": "Americas",
    "SG": "APAC", "AU": "APAC", "IN": "APAC", "JP": "APAC",
    "UAE": "MEA", "ZA": "MEA",
}

REGION_TO_CURRENCY: dict[str, str] = {
    "EU": "EUR",
    "CH": "CHF",
    "Americas": "USD",
    "APAC": "USD",
    "MEA": "USD",
}


def country_to_region(country: str) -> str:
    """Return the pricing region for a delivery country.
    Unknown countries default to 'EU' (safe fallback; logs no exception)."""
    return COUNTRY_TO_REGION.get(country, "EU")


def country_to_currency(country: str) -> str:
    """Return the expected transaction currency for a delivery country."""
    region = country_to_region(country)
    return REGION_TO_CURRENCY.get(region, "EUR")


def get_pricing_regions_for_country(country: str) -> list[str]:
    """Return an ordered list of pricing region codes to try for a given
    delivery country.  CH is tried first, then EU as a fallback, because
    most EU suppliers only have EU-region pricing rows even though they
    also serve CH."""
    region = country_to_region(country)
    if region == "CH":
        return ["CH", "EU"]
    return [region]


def countries_to_regions(countries: list[str]) -> set[str]:
    """Return the set of pricing regions covering all delivery countries."""
    return {country_to_region(c) for c in countries}
