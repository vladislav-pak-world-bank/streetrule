import csv
from pathlib import Path

from core.apply import build_changes, change_demos, coverage_result
from core.places import legal_place

ROOT = Path(__file__).resolve().parent.parent


def test_boston_neighborhood_is_the_city():
    assert legal_place("Dorchester", "MA") == ("Boston", "MA")
    assert legal_place("San Ysidro", "CA") == ("San Diego", "CA")
    assert legal_place("Hoboken", "NJ") == ("Hoboken", "NJ")


def test_missing_year_is_unknown_not_a_guess():
    rule = {"status": "in_force", "coverage_conditions": "certificate of occupancy on or before 1979", "exemptions": "", "category": "rent_increase_limits", "level": "city"}
    row = {"year_built": "", "units": "20"}
    assert coverage_result(rule, row, "2026-10-01") == "unknown"


def test_future_effective_date_is_not_in_force():
    rule = {"status": "in_force", "effective_date": "2027-07-01", "coverage_conditions": "", "exemptions": "", "category": "algorithmic_rent_setting", "level": "state"}
    assert coverage_result(rule, {"year_built": "1920", "units": "10"}, "2026-10-01") == "not_yet_effective"


def test_an_enacted_rule_applies_once_its_date_arrives():
    rule = {"status": "not_yet_effective", "effective_date": "2027-07-01", "coverage_conditions": "", "exemptions": "", "depends_on": [], "category": "algorithmic_rent_setting", "level": "state"}
    row = {"year_built": "1920", "units": "10"}
    assert coverage_result(rule, row, "2026-10-01") == "not_yet_effective"
    assert coverage_result(rule, row, "2027-07-02") == "applies"


def test_struck_ballot_affects_nobody():
    with (ROOT / "data" / "sample_addresses.csv").open() as f:
        rows = list(csv.DictReader(f))
    changes = build_changes(rows)
    assert changes["T5"]["affected_address_ids"] == []
    assert len(changes["T1"]["affected_address_ids"]) == 250
    assert len(changes["T2"]["affected_address_ids"]) == 90


def test_change_demos_match_the_brief():
    demos = {item["id"]: item for item in change_demos()["tests"]}
    assert "not yet effective" in demos["T1"]["lines"][1]
    assert "applies" in demos["T1"]["lines"][2]
    assert "not yet effective" in demos["T3"]["lines"][1]
    assert "applies" in demos["T3"]["lines"][2]
    assert "Conflict flagged" in demos["T3"]["lines"][4]
    assert demos["T5"]["affected"] == 0
    assert any("pending" in line for line in demos["T4"]["lines"])
