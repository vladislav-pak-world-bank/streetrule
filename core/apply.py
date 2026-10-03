import csv
import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from core.coverage import FACT_LABELS, address_facts, evaluate, verdict
from core.places import jurisdiction_names, resolve


def _place(row: dict) -> tuple[str, str]:
    where = resolve(row)
    return where["city"], where["state"]

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AS_OF = "2026-10-01"
RESULT_ORDER = ["applies", "unknown", "superseded", "not_yet_effective", "pending", "not_covered"]
SCORED = ("applies", "unknown", "superseded", "not_yet_effective", "pending")

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
    city, state = _place(row)
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


THRESHOLDS = ("built_on_or_before", "built_after", "exempt_if_newer_than_years", "min_units", "max_units",
              "exempt_owner_occupied_max_units", "exempt_single_family_or_condo", "requires_public_funding")


def has_thresholds(rule: dict) -> bool:
    cond = rule.get("conditions") or {}
    return any(cond.get(k) for k in THRESHOLDS)


def coverage_checks(rule: dict, row: dict, as_of: str, facts: dict | None = None) -> list[dict]:
    """The readable checks behind a coverage decision."""
    facts = facts or address_facts(row)
    if has_thresholds(rule):
        return evaluate(rule["conditions"], facts, _parse_date(as_of) or date.today())
    checks = []
    supplied = set(facts.get("supplied") or [])
    for label in missing_facts(rule, row):
        key = {"year built": "year_built", "unit count": "units", "whether the owner lives there": "owner_occupied",
               "whether the property receives public funding": "public_funding"}[label]
        if key in supplied:
            checks.append({"state": "pass", "text": f"You supplied {label}.", "fact": None})
        else:
            checks.append({"state": "open", "text": f"Coverage turns on {label}, which the public record does not show.", "fact": key})
    return checks


def coverage_result(rule: dict, row: dict, as_of: str, facts: dict | None = None) -> str | None:
    """Return a result value, or None to leave the rule off this address."""
    status = rule.get("status")
    if status == "failed":
        return None
    when = _parse_date(as_of)
    effective = _parse_date(rule.get("effective_date"))
    if status == "pending":
        return "pending"
    if effective and when and effective > when:
        return "not_yet_effective"
    if status == "not_yet_effective" and not (effective and when and effective <= when):
        return "not_yet_effective"
    return verdict(coverage_checks(rule, row, as_of, facts))


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
        elif fact == "public_funding" and _mentions(rule.get("coverage_conditions"), ("funding", "subsid", "publicly", "inclusionary")):
            missing.append("whether the property receives public funding")
    return list(dict.fromkeys(missing))


def rules_for_address(rules: list[dict], row: dict) -> list[dict]:
    city, state = _place(row)
    names = jurisdiction_names(city, state)
    return [r for r in rules if r.get("jurisdiction") in names]


def explain(rule: dict, result: str, row: dict, checks: list[dict] | None = None) -> str:
    if result == "unknown":
        open_facts = [FACT_LABELS[c["fact"]] for c in checks or [] if c["state"] == "open" and c.get("fact")]
        fact = " and ".join(dict.fromkeys(open_facts)) or "a coverage fact"
        return f"Depends on {fact}, which the public record does not show for this address."
    if result == "not_covered":
        return next((c["text"] for c in checks or [] if c["state"] == "fail"), "Outside this rule's coverage.")
    if result == "pending":
        return "A bill, not law, as of the query date."
    if result == "not_yet_effective":
        return f"Enacted, effective {rule.get('effective_date') or 'on a later date'}."
    return rule.get("requirement") or "In force for this jurisdiction."


def mark_superseded(hits: list[dict]) -> None:
    city_categories = {h["rule"]["category"] for h in hits if h["rule"].get("level") == "city" and h["result"] == "applies"}
    for hit in hits:
        rule = hit["rule"]
        if rule.get("cumulative"):
            continue
        if hit["result"] == "applies" and rule.get("level") == "state" and rule.get("category") in city_categories:
            if rule.get("category") in ("rent_increase_limits", "just_cause_eviction"):
                hit["result"] = "superseded"
                hit["explanation"] = "A local rule on the same subject governs this address."


@lru_cache(maxsize=1)
def retrieved_dates() -> dict:
    with (ROOT / "corpus" / "corpus_manifest.csv").open() as f:
        return {row["doc_id"]: (row.get("retrieved_at") or "")[:10] or None for row in csv.DictReader(f)}


def lookup(rules: list[dict], row: dict, as_of: str = DEFAULT_AS_OF, overrides: dict | None = None) -> dict:
    city, state = _place(row)
    facts = address_facts(row, overrides)
    hits = []
    for rule in rules_for_address(rules, row):
        checks = coverage_checks(rule, row, as_of, facts)
        result = coverage_result(rule, row, as_of, facts)
        if result is None:
            continue
        conflict, note = bool(rule.get("conflict_flag")), rule.get("conflict_note")
        if rule.get("jurisdiction") == "NJ" and rule.get("category") == "algorithmic_rent_setting" and city in ("Jersey City", "Hoboken"):
            conflict = True
            note = (
                "Once the New Jersey FAIR Act takes effect on 2027-07-01 it may preempt a local algorithmic-pricing ban. "
                "Jersey City and Hoboken are flagged for review. Their ordinance text was not in the corpus."
            )
        hits.append({
            "rule": rule,
            "team_rule_id": rule["team_rule_id"],
            "result": result,
            "explanation": explain(rule, result, row, checks),
            "checks": checks if result in ("applies", "unknown", "not_covered") else [],
            "conflict_flag": conflict,
            "conflict_note": note,
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
    drivers = {}
    for hit in hits:
        if hit["result"] != "unknown":
            continue
        for fact in dict.fromkeys(c["fact"] for c in hit["checks"] if c["state"] == "open" and c.get("fact")):
            drivers[fact] = drivers.get(fact, 0) + 1
    where = resolve(row)
    return {
        "address_id": row["address_id"],
        "street_address": row["street_address"],
        "postal_city": row["postal_city"],
        "legal_city": city,
        "state": state,
        "place": where,
        "year_built": facts["year_built"],
        "units": facts["units"],
        "facts": {k: facts[k] for k in ("year_built", "units", "owner_occupied", "public_funding")},
        "supplied": facts["supplied"],
        "use_description": row.get("use_description"),
        "source_dataset": row.get("source_dataset"),
        "as_of": as_of,
        "gaps": gaps_for_address(row),
        "unknown_drivers": [
            {"fact": fact, "label": FACT_LABELS[fact], "rules": count}
            for fact, count in sorted(drivers.items(), key=lambda item: -item[1])
        ],
        "counts": {result: sum(1 for h in hits if h["result"] == result) for result in RESULT_ORDER},
        "hits": [
            {
                "team_rule_id": h["team_rule_id"],
                "result": h["result"],
                "explanation": h["explanation"],
                "checks": h["checks"],
                "source_doc_id": h["rule"].get("source_doc_id"),
                "retrieved": retrieved_dates().get(h["rule"].get("source_doc_id")),
                "reviewed": (h["rule"].get("interaction") or "").startswith("Reviewed"),
                "key_value": h["rule"].get("key_value"),
                "conflict_flag": h["conflict_flag"],
                "conflict_note": h.get("conflict_note"),
                "jurisdiction": h["rule"].get("jurisdiction"),
                "level": h["rule"].get("level"),
                "effective_date": h["rule"].get("effective_date"),
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
        legal, st = _place(row)
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
            "notes": "The boundary is the city line: Hoboken addresses, Jersey City addresses, and not Newark. The ordinance text for both cities is link-only in this corpus, so those bans are not quoted as rules in force.",
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
            "notes": "The Massachusetts rent-control ballot question was struck on 2026-06-23. The only source for that (D059) is a link with no text in the corpus, so no Boston or Cambridge address is given a rent cap from it.",
        },
    }


def _sample(rows: list[dict], state: str, city: str) -> dict:
    for row in rows:
        legal, st = _place(row)
        if st == state and legal == city:
            return row
    raise KeyError(city)


def _label(row: dict) -> str:
    return f"{row['street_address']}, {row['postal_city']}, {row['state']}"


def _matching(rules: list[dict], row: dict, as_of: str, category: str, jurisdiction: str | None = None, level: str | None = None) -> list[dict]:
    hits = []
    for hit in lookup(rules, row, as_of)["hits"]:
        if hit["category"] != category:
            continue
        if jurisdiction and hit.get("jurisdiction") != jurisdiction:
            continue
        if level and hit.get("level") != level:
            continue
        hits.append(hit)
    return hits


def change_demos() -> dict:
    """One worked example of each change test, computed from the same lookup the address page uses."""
    rows, rules = load_addresses(), load_rules()
    changes = build_changes(rows)
    san_diego = _sample(rows, "CA", "San Diego")
    hoboken = _sample(rows, "NJ", "Hoboken")
    jersey = _sample(rows, "NJ", "Jersey City")
    newark = _sample(rows, "NJ", "Newark")
    boston = _sample(rows, "MA", "Boston")

    def line(hit: dict, as_of: str) -> str:
        flag = " Conflict flagged." if hit["conflict_flag"] else ""
        return f"{as_of}: {hit['result'].replace('_', ' ')} — {hit['title']}.{flag}"

    t1 = _matching(rules, san_diego, "2025-12-31", "algorithmic_rent_setting", "CA")
    t1_after = _matching(rules, san_diego, "2026-01-02", "algorithmic_rent_setting", "CA")
    fair_now = _matching(rules, newark, "2026-10-01", "algorithmic_rent_setting", "NJ")
    fair_later = _matching(rules, newark, "2027-07-02", "algorithmic_rent_setting", "NJ")
    fair_jersey = _matching(rules, jersey, "2026-10-01", "algorithmic_rent_setting", "NJ")
    bills = _matching(rules, boston, DEFAULT_AS_OF, "algorithmic_rent_setting", "MA")
    rent = _matching(rules, boston, DEFAULT_AS_OF, "rent_increase_limits")

    def city_gap_ids(row: dict) -> str:
        city, state = _place(row)
        target = f"{city}, {state}"
        ids = [
            gap["doc_id"]
            for gap in load_gaps()
            if target in {part.strip() for part in gap["jurisdictions"].split(";")}
        ]
        return ", ".join(ids) or "none"

    boundary = []
    for row in (hoboken, jersey, newark):
        found = _matching(rules, row, DEFAULT_AS_OF, "algorithmic_rent_setting", level="city")
        names = ", ".join(hit["title"] for hit in found) or "no city algorithmic rule quoted"
        boundary.append(f"{_label(row)} — legal city {lookup(rules, row)['legal_city']}. {names}. City sources with no text: {city_gap_ids(row)}.")

    examples = {
        "T1": [f"Example: {_label(san_diego)}.", line(t1[0], "2025-12-31"), line(t1_after[0], "2026-01-02")],
        "T2": boundary,
        "T3": [
            f"Newark example: {_label(newark)}.",
            line(fair_now[0], "2026-10-01"),
            line(fair_later[0], "2027-07-02"),
            f"Jersey City example: {_label(jersey)}.",
            line(fair_jersey[0], "2026-10-01"),
        ],
        "T4": [f"Example: {_label(boston)}."] + [line(hit, DEFAULT_AS_OF) for hit in bills],
        "T5": [
            f"Example: {_label(boston)}.",
            "No rent cap is returned for this address.",
            "The rent rule that does appear forbids rent control. It is not the struck ballot question: "
            + ("; ".join(hit["title"] for hit in rent) or "none")
            + ".",
        ],
    }
    titles = {
        "T1": "California rent-algorithm law takes effect",
        "T2": "Hoboken and Jersey City are different cities",
        "T3": "New Jersey FAIR Act is not in force yet",
        "T4": "Massachusetts algorithm bills have not passed",
        "T5": "The struck Massachusetts rent-cap question covers nobody",
    }
    newark_ids = set(_ids(rows, "NJ", "Newark"))
    met = {
        "T1": "not yet effective" in examples["T1"][1] and "applies" in examples["T1"][2],
        "T2": not newark_ids & set(changes["T2"]["affected_address_ids"]),
        "T3": "not yet effective" in examples["T3"][1] and "applies" in examples["T3"][2] and "Conflict flagged" in examples["T3"][4],
        "T4": bool(bills) and all(hit["result"] == "pending" for hit in bills),
        "T5": not changes["T5"]["affected_address_ids"] and not any("cap" in hit["title"].lower() and hit["result"] == "applies" for hit in rent),
    }
    expected = {t["test_id"]: t["expected_behavior"] for t in json.loads((ROOT / "dev" / "change_tests.json").read_text())}
    return {
        "tests": [
            {
                "id": test_id,
                "title": titles[test_id],
                "affected": len(changes[test_id]["affected_address_ids"]),
                "flagged": len(changes[test_id]["conflict_flag_address_ids"]),
                "notes": changes[test_id]["notes"],
                "expected": expected.get(test_id, ""),
                "met": met[test_id],
                "lines": examples[test_id],
            }
            for test_id in ("T1", "T2", "T3", "T4", "T5")
        ]
    }


@lru_cache(maxsize=1)
def insights() -> dict:
    """Portfolio-wide evidence for the landing page: what the system decided, and what a naive approach gets wrong."""
    rows, rules = load_addresses(), load_rules()
    results, drivers, methods = {}, {}, {}
    by_city = {}
    naive_wrong_city = 0
    for row in rows:
        data = lookup(rules, row)
        city = f"{data['legal_city']}, {data['state']}"
        stats = by_city.setdefault(city, {"city": city, "addresses": 0, "applies": 0, "unknown": 0, "not_covered": 0})
        stats["addresses"] += 1
        methods[data["place"]["method"]] = methods.get(data["place"]["method"], 0) + 1
        if row["postal_city"] != data["legal_city"]:
            naive_wrong_city += 1
        for hit in data["hits"]:
            results[hit["result"]] = results.get(hit["result"], 0) + 1
            if hit["result"] in stats:
                stats[hit["result"]] += 1
        for driver in data["unknown_drivers"]:
            entry = drivers.setdefault(driver["fact"], {"fact": driver["fact"], "label": driver["label"], "answers": 0, "addresses": 0})
            entry["answers"] += driver["rules"]
            entry["addresses"] += 1
    documents = {rule["source_doc_id"] for rule in rules}
    return {
        "rules": len(rules),
        "documents": len(documents),
        "addresses": len(rows),
        "cities": len(by_city),
        "results": results,
        "unknown_drivers": sorted(drivers.values(), key=lambda d: -d["answers"]),
        "by_city": sorted(by_city.values(), key=lambda c: c["city"]),
        "place_methods": methods,
        "naive_wrong_city": naive_wrong_city,
        "naive_overreach": results.get("not_covered", 0),
        "conflicts": len({(rule["jurisdiction"], rule["category"]) for rule in rules if rule.get("conflict_flag")})
        + (1 if any(rule["jurisdiction"] == "NJ" and rule["category"] == "algorithmic_rent_setting" for rule in rules) else 0),
        "reviewed": sum(1 for rule in rules if (rule.get("interaction") or "").startswith("Reviewed")),
        "pending_or_future": sum(1 for rule in rules if rule["status"] in ("pending", "not_yet_effective")),
    }


def write_outputs() -> None:
    rows = load_addresses()
    rules = load_rules()
    lookups = {row["address_id"]: [
        {k: hit[k] for k in ("team_rule_id", "result", "explanation", "conflict_flag")}
        for hit in lookup(rules, row)["hits"]
        if hit["result"] in SCORED
    ] for row in rows}
    out = ROOT / "output"
    out.mkdir(exist_ok=True)
    (out / "lookups.json").write_text(json.dumps({"as_of": DEFAULT_AS_OF, "lookups": lookups}, indent=2))
    (out / "changes.json").write_text(json.dumps(build_changes(rows), indent=2))
    print(f"wrote lookups for {len(rows)} addresses and changes T1-T5")
