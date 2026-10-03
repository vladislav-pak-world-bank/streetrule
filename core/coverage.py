"""Decide whether a rule covers an address from the rule's extracted thresholds and the address facts.

Every decision is a list of checks a person can read: "Built 1920, on or before the 1979-06-13 cutoff."
A check passes, fails (the rule does not cover the address), or is open (a fact is missing or on a boundary).
"""

from datetime import date

FACT_LABELS = {
    "year_built": "year built",
    "units": "unit count",
    "owner_occupied": "whether the owner lives there",
    "public_funding": "whether the property receives public funding",
    "owner_type": "the owner type",
}


def address_facts(row: dict, overrides: dict | None = None) -> dict:
    """Facts from the public record, replaced by anything the user supplied."""
    def number(value):
        value = str(value or "").strip()
        return int(value) if value.isdigit() else None

    def yes_no(value):
        value = str(value or "").strip().lower()
        return {"yes": True, "true": True, "no": False, "false": False}.get(value)

    facts = {
        "year_built": number(row.get("year_built")),
        "units": number(row.get("units")),
        "owner_occupied": None,
        "public_funding": None,
        "condo": "condo" in (row.get("use_description") or "").lower(),
    }
    supplied = set()
    for key, value in (overrides or {}).items():
        if value in (None, ""):
            continue
        parsed = number(value) if key in ("year_built", "units") else yes_no(value)
        if parsed is None or parsed == facts.get(key):
            continue
        facts[key] = parsed
        supplied.add(key)
    facts["supplied"] = sorted(supplied)
    return facts


def _cutoff(value: str | None) -> date | None:
    if not value:
        return None
    parts = [int(p) for p in value.split("-")]
    return date(parts[0], parts[1] if len(parts) > 1 else 12, parts[2] if len(parts) > 2 else 28)


def _check(state: str, text: str, fact: str | None = None) -> dict:
    return {"state": state, "text": text, "fact": fact}


def evaluate(conditions: dict, facts: dict, as_of: date) -> list[dict]:
    checks = []
    year, units = facts["year_built"], facts["units"]
    certificate = bool(conditions.get("cutoff_uses_certificate"))
    measured = "certificate of occupancy" if certificate else "construction"

    before = _cutoff(conditions.get("built_on_or_before"))
    if before:
        if year is None:
            checks.append(_check("open", f"Covers only buildings whose {measured} is on or before {before}. Year built is not in the record.", "year_built"))
        elif year < before.year:
            checks.append(_check("pass", f"Built {year}, before the {before} cutoff."))
        elif year > before.year:
            checks.append(_check("fail", f"Built {year}, after the {before} cutoff."))
        elif before.month == 12 and before.day == 31 and not certificate:
            checks.append(_check("pass", f"Built {year}, within the cutoff year."))
        else:
            checks.append(_check("open", f"Built {year}, the cutoff year. The {measured} date decides it.", "year_built"))

    after = _cutoff(conditions.get("built_after"))
    if after:
        if year is None:
            checks.append(_check("open", f"Covers only buildings whose {measured} is after {after}. Year built is not in the record.", "year_built"))
        elif year > after.year:
            checks.append(_check("pass", f"Built {year}, after {after}."))
        elif year < after.year:
            checks.append(_check("fail", f"Built {year}, before {after}."))
        else:
            checks.append(_check("open", f"Built {year}, the cutoff year. The {measured} date decides it.", "year_built"))

    rolling = conditions.get("exempt_if_newer_than_years")
    if rolling:
        if year is None:
            checks.append(_check("open", f"Buildings first occupied within the last {rolling} years are exempt. Year built is not in the record.", "year_built"))
        else:
            age = as_of.year - year
            if age > rolling:
                checks.append(_check("pass", f"Built {year}, {age} years before the query date: older than the {rolling}-year exemption."))
            elif age < rolling:
                checks.append(_check("fail", f"Built {year}: within the {rolling}-year new-construction exemption."))
            else:
                checks.append(_check("open", f"Built {year}: exactly at the {rolling}-year boundary. The {measured} date decides it.", "year_built"))

    for bound, word in (("min_units", "at least"), ("max_units", "at most")):
        limit = conditions.get(bound)
        if limit is None:
            continue
        if units is None:
            checks.append(_check("open", f"Covers properties with {word} {limit} units. Unit count is not in the record.", "units"))
        elif (units >= limit) if bound == "min_units" else (units <= limit):
            checks.append(_check("pass", f"{units} units, {word} {limit}."))
        else:
            checks.append(_check("fail", f"{units} units; the rule covers {word} {limit}."))

    owner_limit = conditions.get("exempt_owner_occupied_max_units")
    if owner_limit:
        owner = facts["owner_occupied"]
        if units is not None and units > owner_limit:
            checks.append(_check("pass", f"{units} units, more than the {owner_limit}-unit owner-occupied exemption."))
        elif owner is False:
            checks.append(_check("pass", "The owner does not live there, so the owner-occupied exemption does not apply."))
        elif owner is True and units is not None:
            checks.append(_check("fail", f"Owner-occupied with {units} units: exempt (limit {owner_limit})."))
        elif owner is True:
            checks.append(_check("open", f"Owner-occupied buildings of {owner_limit} or fewer units are exempt. Unit count is not in the record.", "units"))
        else:
            checks.append(_check("open", f"Owner-occupied buildings of {owner_limit} or fewer units are exempt. Public records do not say who lives there.", "owner_occupied"))

    if conditions.get("exempt_single_family_or_condo"):
        if facts["condo"] or units == 1:
            checks.append(_check("open", "Single-family homes and condominiums can be exempt, depending on the owner type, which public records omit.", "owner_type"))
        elif units is None:
            checks.append(_check("open", "Single-family homes and condominiums can be exempt. Unit count is not in the record.", "units"))
        else:
            checks.append(_check("pass", f"{units} units: not a single-family home or condominium."))

    if conditions.get("requires_public_funding"):
        funded = facts["public_funding"]
        if funded is True:
            checks.append(_check("pass", "The property receives public funding."))
        elif funded is False:
            checks.append(_check("fail", "Covers only publicly funded or income-restricted housing; this property is not."))
        else:
            checks.append(_check("open", "Covers only publicly funded or income-restricted housing. Public records do not say.", "public_funding"))
    return checks


def verdict(checks: list[dict]) -> str:
    if any(c["state"] == "fail" for c in checks):
        return "not_covered"
    if any(c["state"] == "open" for c in checks):
        return "unknown"
    return "applies"
