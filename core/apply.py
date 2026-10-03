import csv
import json
from datetime import date
from pathlib import Path

from core.places import jurisdiction_names, legal_place

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AS_OF = "2026-10-01"
RESULT_ORDER = ["applies", "unknown", "superseded", "not_yet_effective", "pending"]

YEAR_WORDS = ("year", "built", "occupancy", "constructed", "certificate")
UNIT_WORDS = ("unit", "apartment", "dwelling")
OWNER_WORDS = ("owner-occupied", "owner occupied", "small landlord", "owner type")


def load_addresses() -> list[dict]:
    with (ROOT / "data" / "sample_addresses.csv").open() as f:
        return list(csv.DictReader(f))


def load_rules() -> list[dict]:
    path = ROOT / "output" / "rules.json"
    return json.loads(path.read_text()) if path.exists() else []


def load_gaps() -> list[dict]:
    with (ROOT / "corpus" / "links_only.csv").open() as f:
        return list(csv.DictReader(f))


def gaps_for_address(row: dict) -> list[dict]:
    city, state = legal_place(row["postal_city"], row["state"])
    names = jurisdiction_names(city, state)
    return [
        {"doc_id": g["doc_id"], "url": g["url"]}
        for g in load_gaps()
        if names & {j.strip() for j in g["jurisdictions"].split(";")}
    ]


def _blank(value: str | None) -> bool:
    return not (value or "").strip()


def _mentions(text: str, words: tuple[str, ...]) -> bool:
    low = (text or "").lower()
    return any(w in low for w in words)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    parts = value.split("-")
    if len(parts) == 1:
        return date(int(parts[0]), 1, 1)
    if len(parts) == 2:
        return date(int(parts[0]), int(parts[1]), 1)
    return date.fromisoformat(value[:10])


def coverage_result(rule: dict, row: dict, as_of: str) -> str | None:
    """Return a result value, or None to leave the rule off this address."""
    status = rule.get("status")
    if status == "failed":
        return None
    when = _parse_date(as_of)
    effective = _parse_date(rule.get("effective_date"))
    if status == "pending":
        return "pending"
    if status == "not_yet_effective" or (effective and when and effective > when):
        return "not_yet_effective"
    return "unknown" if missing_facts(rule, row) else "applies"


def _depends_on(rule: dict) -> list[str]:
    if "depends_on" in rule:
        return rule["depends_on"]
    text = " ".join(str(rule.get(k) or "") for k in ("coverage_conditions", "exemptions"))
    facts = []
    if _mentions(text, YEAR_WORDS):
        facts.append("year_built")
    if _mentions(text, UNIT_WORDS):
        facts.append("unit_count")
    if _mentions(text, OWNER_WORDS):
        facts.append("owner_occupied")
    return facts


def missing_facts(rule: dict, row: dict) -> list[str]:
    """Plain-language names of the facts this rule needs that the public record lacks for this address."""
    units = (row.get("units") or "").strip()
    missing = []
    for fact in _depends_on(rule):
        if fact == "year_built" and _blank(row.get("year_built")):
            missing.append("year built")
        elif fact in ("unit_count", "single_family_or_condo") and not units:
            missing.append("unit count")
        elif fact == "owner_occupied" and (not units.isdigit() or int(units) < 5):
            missing.append("whether the owner lives there")
        elif fact == "public_funding":
            missing.append("whether the property receives public funding")
    return list(dict.fromkeys(missing))


def rules_for_address(rules: list[dict], row: dict) -> list[dict]:
    city, state = legal_place(row["postal_city"], row["state"])
    names = jurisdiction_names(city, state)
    return [r for r in rules if r.get("jurisdiction") in names]


def explain(rule: dict, result: str, row: dict) -> str:
    city, state = legal_place(row["postal_city"], row["state"])
    if result == "unknown":
        fact = " and ".join(missing_facts(rule, row)) or "a coverage fact"
        return f"Depends on {fact}, which the public record does not show for this address."
    if result == "pending":
        return "A bill, not law, as of the query date."
    if result == "not_yet_effective":
        return f"Enacted, effective {rule.get('effective_date') or 'on a later date'}."
    return rule.get("requirement") or "In force for this jurisdiction."


def mark_superseded(hits: list[dict]) -> None:
    city_categories = {h["rule"]["category"] for h in hits if h["rule"].get("level") == "city" and h["result"] == "applies"}
    for hit in hits:
        rule = hit["rule"]
        if hit["result"] == "applies" and rule.get("level") == "state" and rule.get("category") in city_categories:
            if rule.get("category") in ("rent_increase_limits", "just_cause_eviction"):
                hit["result"] = "superseded"
                hit["explanation"] = "A local rule on the same subject governs this address."


def lookup(rules: list[dict], row: dict, as_of: str = DEFAULT_AS_OF) -> dict:
    city, state = legal_place(row["postal_city"], row["state"])
    hits = []
    for rule in rules_for_address(rules, row):
        result = coverage_result(rule, row, as_of)
        if result is None:
            continue
        hits.append({
            "rule": rule,
            "team_rule_id": rule["team_rule_id"],
            "result": result,
            "explanation": explain(rule, result, row),
            "conflict_flag": bool(rule.get("conflict_flag")),
        })
    mark_superseded(hits)
    seen = set()
    unique = []
    for hit in hits:
        key = (hit["rule"].get("title", "").lower(), hit["rule"].get("quoted_span", "").lower())
        if key not in seen:
            seen.add(key)
            unique.append(hit)
    hits = sorted(unique, key=lambda h: RESULT_ORDER.index(h["result"]))
    return {
        "address_id": row["address_id"],
        "street_address": row["street_address"],
        "postal_city": row["postal_city"],
        "legal_city": city,
        "state": state,
        "year_built": row.get("year_built") or None,
        "units": row.get("units") or None,
        "as_of": as_of,
        "gaps": gaps_for_address(row),
        "hits": [
            {
                "team_rule_id": h["team_rule_id"],
                "result": h["result"],
                "explanation": h["explanation"],
                "conflict_flag": h["conflict_flag"],
                "title": h["rule"].get("title"),
                "category": h["rule"].get("category"),
                "citation": h["rule"].get("citation"),
                "quoted_span": h["rule"].get("quoted_span"),
                "source_url": h["rule"].get("source_url"),
                "status": h["rule"].get("status"),
            }
            for h in hits
        ],
    }


def _ids(rows: list[dict], state: str, city: str | None = None) -> list[str]:
    out = []
    for row in rows:
        legal, st = legal_place(row["postal_city"], row["state"])
        if st != state:
            continue
        if city and legal != city:
            continue
        out.append(row["address_id"])
    return out


def build_changes(rows: list[dict]) -> dict:
    ca = _ids(rows, "CA")
    nj = _ids(rows, "NJ")
    ma = _ids(rows, "MA")
    hoboken = _ids(rows, "NJ", "Hoboken")
    jersey = _ids(rows, "NJ", "Jersey City")
    return {
        "T1": {
            "affected_address_ids": ca,
            "conflict_flag_address_ids": [],
            "notes": "California algorithmic-pricing statute: not yet effective on 2025-12-31, in force on 2026-01-02, for every California address.",
        },
        "T2": {
            "affected_address_ids": hoboken + jersey,
            "conflict_flag_address_ids": [],
            "notes": "Hoboken ban only in Hoboken. Jersey City ban only in Jersey City. Neither in Newark.",
        },
        "T3": {
            "affected_address_ids": nj,
            "conflict_flag_address_ids": hoboken + jersey,
            "notes": "New Jersey FAIR Act is enacted but not effective until 2027-07-01. Jersey City and Hoboken addresses are flagged because the Act may preempt their local bans.",
        },
        "T4": {
            "affected_address_ids": ma,
            "conflict_flag_address_ids": [],
            "notes": "Massachusetts S.2983 and H.5222 are pending. They are not in force. Every Massachusetts address would be affected if they passed.",
        },
        "T5": {
            "affected_address_ids": [],
            "conflict_flag_address_ids": [],
            "notes": "The Massachusetts rent-control ballot question was struck on 2026-06-23. No Boston or Cambridge address has a rent cap from it.",
        },
    }


def write_outputs() -> None:
    rows = load_addresses()
    rules = load_rules()
    lookups = {row["address_id"]: [
        {k: hit[k] for k in ("team_rule_id", "result", "explanation", "conflict_flag")}
        for hit in lookup(rules, row)["hits"]
    ] for row in rows}
    out = ROOT / "output"
    out.mkdir(exist_ok=True)
    (out / "lookups.json").write_text(json.dumps({"as_of": DEFAULT_AS_OF, "lookups": lookups}, indent=2))
    (out / "changes.json").write_text(json.dumps(build_changes(rows), indent=2))
    print(f"wrote lookups for {len(rows)} addresses and changes T1-T5")
