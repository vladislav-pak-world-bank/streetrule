"""Read the supplied law files and write output/rules.json. One model call per document."""

import csv
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

from core.llm import structured  # noqa: E402

CACHE = ROOT / "output" / "cache"
AS_OF = "2026-10-01"
CHUNK = 18000

SYSTEM = f"""You extract rental-housing rules from one source document for a lookup tool.
Today's query date is {AS_OF}. Only extract rules in these categories:
rent_increase_limits, just_cause_eviction, security_deposits, application_screening_fees, screening_restrictions, algorithmic_rent_setting.
Status is as of {AS_OF}: in_force, not_yet_effective, pending, or failed.
A law with an effective date after {AS_OF} is not_yet_effective. A bill that has not passed is pending. A proposal that was struck or vetoed is failed.
A law of general application counts when it governs how residential rent is set, for example an antitrust ban on common pricing algorithms: categorize it as algorithmic_rent_setting.
A chaptered or enacted statute is in_force or not_yet_effective, never pending.
quoted_span must be copied exactly from the document, at least 20 characters, with no paraphrase.
citation is the official cite if the document states one, otherwise the document title.
If the document states no rule in those categories, return an empty list.
Do not invent a rule, a date, or a citation.
"""

RULE = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "jurisdiction", "level", "category", "status", "title", "requirement",
        "key_value", "coverage_conditions", "exemptions", "effective_date",
        "citation", "quoted_span", "confidence", "conflict_flag", "conflict_note",
    ],
    "properties": {
        "jurisdiction": {"type": "string"},
        "level": {"type": "string", "enum": ["state", "city"]},
        "category": {"type": "string", "enum": [
            "rent_increase_limits", "just_cause_eviction", "security_deposits",
            "application_screening_fees", "screening_restrictions", "algorithmic_rent_setting",
        ]},
        "status": {"type": "string", "enum": ["in_force", "not_yet_effective", "pending", "failed"]},
        "title": {"type": "string"},
        "requirement": {"type": "string"},
        "key_value": {"type": ["string", "null"]},
        "coverage_conditions": {"type": ["string", "null"]},
        "exemptions": {"type": ["string", "null"]},
        "effective_date": {"type": ["string", "null"]},
        "citation": {"type": "string"},
        "quoted_span": {"type": "string"},
        "confidence": {"type": ["number", "null"]},
        "conflict_flag": {"type": "boolean"},
        "conflict_note": {"type": ["string", "null"]},
    },
}
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["rules"],
    "properties": {"rules": {"type": "array", "items": RULE}},
}


def chunks(text: str) -> list[str]:
    if len(text) <= CHUNK:
        return [text]
    parts = []
    start = 0
    while start < len(text) and len(parts) < 4:
        parts.append(text[start:start + CHUNK])
        start += CHUNK - 400
    return parts


STATES = {"california": "CA", "new jersey": "NJ", "massachusetts": "MA", "ca": "CA", "nj": "NJ", "ma": "MA"}


def normalize_jurisdiction(rule: dict, manifest: str) -> str:
    """Return 'CA' for a state rule, 'City, ST' for a city rule, using the manifest when the model drifts."""
    raw = (rule.get("jurisdiction") or "").strip()
    listed = [j.strip() for j in manifest.split(";") if j.strip()] or [manifest.strip()]
    low = raw.lower()
    if "municipalit" in low or "statewide" in low or any(name in low for name in ("california", "new jersey", "massachusetts")):
        rule["level"] = "state"
    if rule.get("level") == "state":
        code = STATES.get(raw.lower())
        if code:
            return code
        for j in listed:
            tail = j.split(",")[-1].strip()
            if tail.upper() in ("CA", "NJ", "MA"):
                return tail.upper()
        return raw
    for j in listed:
        if "," in j and j.split(",")[0].strip().lower() in raw.lower():
            return j
    state = listed[0].split(",")[-1].strip().upper()
    city = raw.split(",")[0].strip()
    for prefix in ("City of ", "City and County of "):
        if city.startswith(prefix):
            city = city[len(prefix):]
    if city and state in ("CA", "NJ", "MA"):
        return f"{city}, {state}"
    return listed[0]


def california_default_date(rule: dict, source: str) -> None:
    """Cal. Const. art. IV, sec. 8(c): a non-urgency statute takes effect January 1 after enactment."""
    if rule.get("jurisdiction") != "CA" or rule.get("effective_date") or rule.get("status") in ("pending", "failed"):
        return
    match = re.search(r"(\d{2})/(\d{2})/(\d{2})\s*-\s*Chaptered", source)
    if not match or "urgency" in source.lower():
        return
    year = 2000 + int(match.group(3))
    rule["effective_date"] = f"{year + 1}-01-01"
    rule["status"] = "in_force" if rule["effective_date"] <= AS_OF else "not_yet_effective"
    rule["interaction"] = "Effective date from Cal. Const. art. IV, sec. 8(c): statutes chaptered without an urgency clause take effect January 1 of the next year."


def quote_in_source(quote: str, source: str) -> str | None:
    if not quote or len(quote) < 20:
        return None
    if quote in source:
        return quote
    folded = " ".join(quote.split())
    hay = " ".join(source.split())
    at = hay.find(folded)
    if at == -1:
        return None
    return folded


FACTS = ["year_built", "unit_count", "owner_occupied", "single_family_or_condo", "public_funding"]

TAG_SYSTEM = """You decide which property facts determine whether one housing rule covers a given rental address.
Choose only from: year_built, unit_count, owner_occupied, single_family_or_condo, public_funding.
Pick a fact only if the rule's coverage or an exemption turns on it. Ignore facts about the tenant, such as income, children, or vouchers.
A rule that covers every rental in its jurisdiction depends on nothing: return an empty list."""

TAG_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["depends_on"],
    "properties": {"depends_on": {"type": "array", "items": {"type": "string", "enum": FACTS}}},
}


def tag_dependencies(rules: list[dict]) -> None:
    path = CACHE / "depends_on.json"
    saved = json.loads(path.read_text()) if path.exists() else {}

    def key(rule: dict) -> str:
        return f"{rule['source_doc_id']}|{rule['quoted_span']}"

    def tag(rule: dict) -> list[str]:
        user = json.dumps({k: rule.get(k) for k in ("jurisdiction", "category", "title", "requirement", "coverage_conditions", "exemptions")})
        return structured(TAG_SYSTEM, user, TAG_SCHEMA)["depends_on"]

    todo = [r for r in rules if key(r) not in saved]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for rule, facts in zip(todo, pool.map(tag, todo)):
            saved[key(rule)] = facts
    path.write_text(json.dumps(saved, indent=2))
    for rule in rules:
        rule["depends_on"] = saved[key(rule)]
    print(f"tagged {len(todo)} rules, {len(rules) - len(todo)} from cache")


COND_SYSTEM = """You turn one housing rule's coverage text into machine-checkable thresholds.
Use only what the rule's text states. Leave a field null or false when the text does not state it. Never infer a number from outside knowledge.
built_on_or_before: ISO date; the rule covers only buildings built (or certified for occupancy) on or before it. Example: 'certificate of occupancy on or before June 13, 1979' -> 1979-06-13.
built_after: ISO date; the rule covers only buildings built after it.
cutoff_uses_certificate: true when the cutoff refers to a certificate of occupancy or first occupancy rather than year built.
exempt_if_newer_than_years: N when buildings first occupied within the last N years are exempt (a rolling exemption).
min_units / max_units: covered only if the property has at least / at most this many units.
exempt_owner_occupied_max_units: N when an owner-occupied building with N or fewer units is exempt.
exempt_single_family_or_condo: true when single-family homes or condominiums are exempt (often with conditions).
requires_public_funding: true when the rule covers only properties with public funding, subsidy, or income-restricted units.
evidence: the words from the rule text that state these thresholds, or an empty string."""

COND_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "built_on_or_before", "built_after", "cutoff_uses_certificate", "exempt_if_newer_than_years",
        "min_units", "max_units", "exempt_owner_occupied_max_units", "exempt_single_family_or_condo",
        "requires_public_funding", "evidence",
    ],
    "properties": {
        "built_on_or_before": {"type": ["string", "null"]},
        "built_after": {"type": ["string", "null"]},
        "cutoff_uses_certificate": {"type": "boolean"},
        "exempt_if_newer_than_years": {"type": ["integer", "null"]},
        "min_units": {"type": ["integer", "null"]},
        "max_units": {"type": ["integer", "null"]},
        "exempt_owner_occupied_max_units": {"type": ["integer", "null"]},
        "exempt_single_family_or_condo": {"type": "boolean"},
        "requires_public_funding": {"type": "boolean"},
        "evidence": {"type": "string"},
    },
}


def tag_conditions(rules: list[dict]) -> None:
    path = CACHE / "conditions.json"
    saved = json.loads(path.read_text()) if path.exists() else {}

    def key(rule: dict) -> str:
        return f"{rule['source_doc_id']}|{rule['quoted_span']}"

    def tag(rule: dict) -> dict:
        user = json.dumps({k: rule.get(k) for k in (
            "jurisdiction", "category", "title", "requirement", "coverage_conditions", "exemptions", "quoted_span",
        )})
        return structured(COND_SYSTEM, user, COND_SCHEMA)

    todo = [r for r in rules if key(r) not in saved]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for rule, cond in zip(todo, pool.map(tag, todo)):
            saved[key(rule)] = cond
    path.write_text(json.dumps(saved, indent=2))
    for rule in rules:
        rule["conditions"] = saved[key(rule)]
    print(f"thresholds for {len(todo)} rules, {len(rules) - len(todo)} from cache")


def apply_corrections(rules: list[dict]) -> None:
    """Apply reviewed fixes from review/corrections.json; each one records why."""
    path = ROOT / "review" / "corrections.json"
    if not path.exists():
        return
    for fix in json.loads(path.read_text()):
        for rule in rules:
            if rule["source_doc_id"] != fix["source_doc_id"] or rule["category"] != fix["category"]:
                continue
            if fix.get("title_contains") and fix["title_contains"].lower() not in rule.get("title", "").lower():
                continue
            if fix.get("quote_contains") and fix["quote_contains"] not in rule.get("quoted_span", ""):
                continue
            rule.update(fix["set"])
            if fix.get("conditions"):
                rule["conditions"] = {**rule.get("conditions", {}), **fix["conditions"],
                                      "evidence": fix["evidence_quote"], "evidence_doc_id": fix["evidence_doc_id"]}
            rule["interaction"] = f"Reviewed: {fix['reason']}"
            print(f"corrected {rule['team_rule_id']} from {fix['source_doc_id']}")


def sanitize_conditions(rules: list[dict]) -> None:
    """Drop a 'built after' cutoff that contradicts the 'built on or before' cutoff; the model sometimes merges the
    fully covered and partially covered tiers of one ordinance into a single rule."""
    for rule in rules:
        cond = rule.get("conditions") or {}
        before, after = cond.get("built_on_or_before"), cond.get("built_after")
        if before and after and after >= before:
            cond["built_after"] = None


def inherit_city_cutoffs(rules: list[dict]) -> None:
    """A city's rent-increase pages often say 'covered units' and define coverage once. Copy the year cutoff
    from the rule that states it to the other rent-increase rules of the same city, and record where it came from."""
    for rule in rules:
        if rule["level"] != "city" or rule["category"] != "rent_increase_limits":
            continue
        cond = rule.setdefault("conditions", {})
        if cond.get("built_on_or_before"):
            continue
        donor = next((r for r in rules if r is not rule and r["jurisdiction"] == rule["jurisdiction"]
                      and r["category"] == "rent_increase_limits" and (r.get("conditions") or {}).get("built_on_or_before")), None)
        if not donor:
            continue
        for field in ("built_on_or_before", "cutoff_uses_certificate"):
            cond[field] = donor["conditions"].get(field)
        cond["inherited_from"] = donor["team_rule_id"]


def main() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader((ROOT / "corpus" / "corpus_manifest.csv").open()))
    docs = [r for r in rows if r["status"] == "ok" and r["text_file"]]
    kept = []
    for doc in docs:
        cache = CACHE / f"{doc['doc_id']}.json"
        if cache.exists():
            kept.extend(json.loads(cache.read_text()))
            print(f"{doc['doc_id']} cached")
            continue
        source = (ROOT / "corpus" / doc["text_file"]).read_text(errors="replace")
        found = []
        for i, piece in enumerate(chunks(source), start=1):
            user = (
                f"doc_id: {doc['doc_id']}\n"
                f"jurisdictions listed in the manifest: {doc['jurisdictions']}\n"
                f"source_url: {doc['url']}\n\n{piece}"
            )
            try:
                data = structured(SYSTEM, user, SCHEMA)
            except Exception as e:
                print(f"{doc['doc_id']} chunk {i} failed: {type(e).__name__}: {e}")
                continue
            for rule in data.get("rules") or []:
                span = quote_in_source(rule.get("quoted_span", ""), source)
                if not span:
                    continue
                rule["quoted_span"] = span
                rule["jurisdiction"] = normalize_jurisdiction(rule, doc["jurisdictions"])
                rule["source_doc_id"] = doc["doc_id"]
                rule["source_url"] = doc["url"]
                rule["overrides"] = []
                rule["interaction"] = None
                california_default_date(rule, source)
                found.append(rule)
        cache.write_text(json.dumps(found, indent=2))
        kept.extend(found)
        print(f"{doc['doc_id']} {len(found)} rules")

    for i, rule in enumerate(kept, start=1):
        rule["team_rule_id"] = f"r-{i:04d}"
    tag_dependencies(kept)
    tag_conditions(kept)
    sanitize_conditions(kept)
    apply_corrections(kept)
    inherit_city_cutoffs(kept)
    out = ROOT / "output" / "rules.json"
    out.write_text(json.dumps(kept, indent=2))
    print(f"wrote {len(kept)} rules to {out}")


if __name__ == "__main__":
    main()
