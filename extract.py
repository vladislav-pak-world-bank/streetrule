"""Read the supplied law files and write output/rules.json. One model call per document."""

import csv
import json
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
                rule["source_doc_id"] = doc["doc_id"]
                rule["source_url"] = doc["url"]
                rule["overrides"] = []
                rule["interaction"] = None
                found.append(rule)
        cache.write_text(json.dumps(found, indent=2))
        kept.extend(found)
        print(f"{doc['doc_id']} {len(found)} rules")

    for i, rule in enumerate(kept, start=1):
        rule["team_rule_id"] = f"r-{i:04d}"
    out = ROOT / "output" / "rules.json"
    out.write_text(json.dumps(kept, indent=2))
    print(f"wrote {len(kept)} rules to {out}")


if __name__ == "__main__":
    main()
