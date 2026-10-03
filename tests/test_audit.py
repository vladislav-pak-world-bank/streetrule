"""Checks that run over every extracted rule, not one example address."""

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AS_OF = "2026-10-01"


def rules():
    return json.loads((ROOT / "output" / "rules.json").read_text())


def source(doc_id: str) -> str:
    return (ROOT / "corpus" / "text" / f"{doc_id}.txt").read_text(errors="replace")


def test_every_quote_is_in_its_source():
    missing = []
    for rule in rules():
        quote = " ".join(rule["quoted_span"].split())
        hay = " ".join(source(rule["source_doc_id"]).split())
        if quote not in hay:
            missing.append(rule["team_rule_id"])
    assert missing == []


def test_every_jurisdiction_matches_the_manifest():
    manifest = {row["doc_id"]: row["jurisdictions"] for row in csv.DictReader((ROOT / "corpus" / "corpus_manifest.csv").open())}
    bad = []
    for rule in rules():
        listed = [part.strip() for part in manifest[rule["source_doc_id"]].split(";")]
        code = rule["jurisdiction"]
        if rule["level"] == "state":
            ok = any(code == item or item.endswith(", " + code) for item in listed)
        else:
            ok = any(code.split(",")[0].lower() in item.lower() for item in listed)
        if not ok:
            bad.append(rule["team_rule_id"])
    assert bad == []


def test_status_agrees_with_the_effective_date():
    bad = []
    for rule in rules():
        when = rule.get("effective_date") or ""
        if rule["status"] == "in_force" and when > AS_OF:
            bad.append(rule["team_rule_id"])
        if rule["status"] == "not_yet_effective" and when and when <= AS_OF:
            bad.append(rule["team_rule_id"])
    assert bad == []


def test_an_adopted_ordinance_is_not_called_a_bill():
    """The Berkeley miss: a numbered ordinance with a recorded vote was marked pending."""
    pending_docs = {rule["source_doc_id"] for rule in rules() if rule["status"] == "pending"}
    missed = []
    for doc_id in pending_docs:
        text = source(doc_id)
        numbered = re.search(r"Ordinance No\.?\s*[0-9]", text)
        voted = re.search(r"Ayes:", text)
        blank_number = "O-________________" in text
        if numbered and voted and not blank_number:
            missed.append(doc_id)
    assert missed == []


def test_an_unsigned_draft_is_not_called_law():
    in_force_docs = {rule["source_doc_id"] for rule in rules() if rule["status"] == "in_force"}
    missed = [doc_id for doc_id in in_force_docs if re.search(r"adopted this Ordinance at a meeting held on\s*_+", source(doc_id))]
    assert missed == []
