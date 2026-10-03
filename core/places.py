"""Postal city is the mailing city, not always the legal city."""

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


def jurisdiction_names(city: str, state: str) -> set[str]:
    return {state, f"{city}, {state}"}
