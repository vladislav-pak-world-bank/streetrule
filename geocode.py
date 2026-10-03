"""Resolve each sample address to its incorporated place with the US Census Geocoder.

Writes data/geocoded.json: {address_id: {"place": "Boston", "geoid": "2507000", "matched": "..."}}.
Addresses the Census cannot match get place null and fall back to core/places.py.
"""

import json
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from core.apply import load_addresses

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "geocoded.json"
URL = "https://geocoding.geo.census.gov/geocoder/geographies/address"
SUFFIX = re.compile(r"\s+(city|town|township|CDP)$", re.I)


def first_street(street: str) -> str:
    """'1031-1035 CLINTON ST' -> '1031 CLINTON ST'; the Census matches one house number."""
    return re.sub(r"^(\d+)[-–][\d.]+\s", r"\1 ", street.strip())


def same_number(sent: str, matched: str) -> bool:
    """Reject a match to a different house number: '322 Western Ave' once matched '5 Western Ave' in Boston."""
    a = re.match(r"\d+", sent)
    b = re.match(r"\d+", matched or "")
    return bool(a and b and a.group() == b.group())


def geocode(row: dict) -> tuple[str, dict]:
    street = first_street(row["street_address"])
    query = urllib.parse.urlencode({
        "street": street,
        "city": row["postal_city"],
        "state": row["state"],
        "zip": row["zip"],
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "layers": "Incorporated Places",
        "format": "json",
    })
    for _ in range(3):
        try:
            with urllib.request.urlopen(f"{URL}?{query}", timeout=30) as response:
                matches = json.load(response)["result"]["addressMatches"]
            break
        except Exception:
            matches = None
    if not matches:
        return row["address_id"], {"place": None, "geoid": None, "matched": None}
    if not same_number(street, matches[0]["matchedAddress"]):
        return row["address_id"], {"place": None, "geoid": None, "matched": matches[0]["matchedAddress"], "rejected": "different house number"}
    places = matches[0]["geographies"].get("Incorporated Places") or []
    if not places:
        return row["address_id"], {"place": None, "geoid": None, "matched": matches[0]["matchedAddress"]}
    return row["address_id"], {
        "place": SUFFIX.sub("", places[0]["NAME"]),
        "geoid": places[0]["GEOID"],
        "matched": matches[0]["matchedAddress"],
    }


def main() -> None:
    rows = load_addresses()
    with ThreadPoolExecutor(max_workers=10) as pool:
        result = dict(pool.map(geocode, rows))
    OUT.write_text(json.dumps(result, indent=1, sort_keys=True))
    matched = sum(1 for v in result.values() if v["place"])
    print(f"geocoded {matched} of {len(rows)} addresses to an incorporated place")


if __name__ == "__main__":
    main()
