"""Add the hour-16 ordinance without re-reading the whole corpus.

Save the new text as incoming/t6.txt, then run:

    uv run python ingest_one.py incoming/t6.txt --jurisdiction "Cambridge, MA" --url "https://example.test/ordinance"
"""

import argparse
import json
from pathlib import Path

from extract import AS_OF, SCHEMA, SYSTEM, normalize_jurisdiction, quote_in_source, tag_dependencies
from core.llm import structured
from core.apply import write_outputs

ROOT = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--jurisdiction", required=True)
    parser.add_argument("--url", default="")
    parser.add_argument("--doc-id", default="T6")
    args = parser.parse_args()

    source = Path(args.path).read_text(errors="replace")
    data = structured(SYSTEM, f"doc_id: {args.doc_id}\njurisdictions listed in the manifest: {args.jurisdiction}\nsource_url: {args.url}\n\n{source}", SCHEMA)
    found = []
    for rule in data.get("rules") or []:
        span = quote_in_source(rule.get("quoted_span", ""), source)
        if not span:
            continue
        rule["quoted_span"] = span
        rule["jurisdiction"] = normalize_jurisdiction(rule, args.jurisdiction)
        rule["source_doc_id"] = args.doc_id
        rule["source_url"] = args.url
        rule["overrides"] = []
        rule["interaction"] = f"Added after the {AS_OF} corpus, for the hour-16 change test."
        found.append(rule)
    if not found:
        raise SystemExit("No quoted rule survived. The ordinance was not added.")

    tag_dependencies(found)
    rules_path = ROOT / "output" / "rules.json"
    rules = json.loads(rules_path.read_text())
    start = len(rules) + 1
    for offset, rule in enumerate(found):
        rule["team_rule_id"] = f"r-{start + offset:04d}"
        rules.append(rule)
    rules_path.write_text(json.dumps(rules, indent=2))
    write_outputs()
    print(f"added {len(found)} rules from {args.doc_id}")


if __name__ == "__main__":
    main()
