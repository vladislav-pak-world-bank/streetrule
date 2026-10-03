"""Postal city is the mailing city, not always the legal city."""

import json
from functools import lru_cache
from pathlib import Path

GEOCODED = Path(__file__).resolve().parent.parent / "data" / "geocoded.json"

BOSTON_NEIGHBORHOODS = {
    "dorchester", "roxbury", "east boston", "brighton", "allston",
    "south boston", "jamaica plain", "hyde park", "mattapan", "boston",
}


def legal_place(postal_city: str, state: str) -> tuple[str, str]:
    city = (postal_city or "").strip()
    state = (state or "").strip().upper()
    low = city.lower()
    if state == "MA" and low in BOSTON_NEIGHBORHOODS:
        return "Boston", "MA"
    if state == "CA" and low == "san ysidro":
        return "San Diego", "CA"
    return city, state


@lru_cache(maxsize=1)
def _geocoded() -> dict:
    return json.loads(GEOCODED.read_text()) if GEOCODED.exists() else {}


def resolve(row: dict) -> dict:
    """Legal city for an address, preferring the US Census incorporated place, with how it was decided."""
    fallback, state = legal_place(row["postal_city"], row["state"])
    census = _geocoded().get(row["address_id"]) or {}
    place = census.get("place")
    if place and place == fallback:
        return {"city": place, "state": state, "method": "census", "geoid": census.get("geoid"),
                "note": f"US Census Geocoder places this address in {place} (GEOID {census.get('geoid')})."}
    if place:
        return {"city": fallback, "state": state, "method": "disagreement", "geoid": census.get("geoid"),
                "note": f"The Census places this address in {place}, the address record in {fallback}. Flagged for review; {fallback} used."}
    method = "alias" if fallback != row["postal_city"] else "postal"
    why = census.get("rejected") or "no Census match"
    note = (f"Mailing name {row['postal_city']} is a neighborhood of {fallback}." if method == "alias"
            else f"Postal city used ({why}).")
    return {"city": fallback, "state": state, "method": method, "geoid": None, "note": note}


def jurisdiction_names(city: str, state: str) -> set[str]:
    return {state, f"{city}, {state}"}
