"""Hunyuan geo gate: EU / UK / Korea cannot use Tencent-via-FAL.

Not legal advice. Country is ISO 3166-1 alpha-2 (Cloudflare CF-IPCountry).
Missing country → Hunyuan refused (fail closed). UI hide is not enough.
"""

from __future__ import annotations

from collections.abc import Mapping

# EU member states (ISO 3166-1 alpha-2) + UK + South Korea.
HUNYUAN_BLOCKED_COUNTRIES: frozenset[str] = frozenset(
    {
        "AT",
        "BE",
        "BG",
        "HR",
        "CY",
        "CZ",
        "DK",
        "EE",
        "FI",
        "FR",
        "DE",
        "GR",
        "HU",
        "IE",
        "IT",
        "LV",
        "LT",
        "LU",
        "MT",
        "NL",
        "PL",
        "PT",
        "RO",
        "SK",
        "SI",
        "ES",
        "SE",
        "GB",
        "UK",  # alias some CDNs send instead of GB
        "KR",
    }
)

HUNYUAN_BLOCK_REASON = (
    "Hunyuan on FAL is Tencent via FAL. Not available for EU / UK / Korea."
)


class HunyuanGeoBlocked(ValueError):
    """Raised when Hunyuan is requested from a blocked or unknown country."""


def normalize_country(raw: str | None) -> str | None:
    code = (raw or "").strip().upper()
    if not code or code in {"XX", "T1", "ZZ"}:  # CF unknowns / Tor
        return None
    if code == "UK":
        return "GB"
    if len(code) != 2 or not code.isalpha():
        return None
    return code


def hunyuan_allowed(country: str | None) -> bool:
    code = normalize_country(country)
    if code is None:
        return False
    return code not in HUNYUAN_BLOCKED_COUNTRIES


def assert_hunyuan_allowed(country: str | None) -> str:
    """Return normalized country or raise HunyuanGeoBlocked."""
    code = normalize_country(country)
    if code is None:
        raise HunyuanGeoBlocked(
            "country is required for Hunyuan (ISO 3166-1 alpha-2); missing or unknown"
        )
    if code in HUNYUAN_BLOCKED_COUNTRIES:
        raise HunyuanGeoBlocked(HUNYUAN_BLOCK_REASON)
    return code


def country_from_headers(
    headers: Mapping[str, str] | None,
    *,
    explicit: str | None = None,
) -> str | None:
    """Prefer explicit body/query, then Cloudflare / proxy geo headers."""
    from_explicit = normalize_country(explicit)
    if from_explicit:
        return from_explicit
    if not headers:
        return None
    lowered = {str(k).lower(): str(v) for k, v in headers.items()}
    for key in ("cf-ipcountry", "x-geo-country", "x-country-code", "x-appengine-country"):
        found = normalize_country(lowered.get(key))
        if found:
            return found
    return None
