from datetime import date

from core.coverage import address_facts, evaluate, verdict
from core.places import resolve

AS_OF = date(2026, 10, 1)
SF_RENT = {"built_on_or_before": "1979-06-13", "cutoff_uses_certificate": True}
CA_CAP = {"exempt_if_newer_than_years": 15, "cutoff_uses_certificate": True, "exempt_owner_occupied_max_units": 2}


def decide(conditions, year="", units="", **supplied):
    facts = address_facts({"year_built": year, "units": units, "use_description": ""}, supplied)
    return verdict(evaluate(conditions, facts, AS_OF))


def test_certificate_cutoff_year_is_unknown():
    assert decide(SF_RENT, "1926", "6") == "applies"
    assert decide(SF_RENT, "1979", "6") == "unknown"
    assert decide(SF_RENT, "1986", "49") == "not_covered"
    assert decide(SF_RENT, "", "6") == "unknown"


def test_rolling_new_construction_exemption():
    assert decide(CA_CAP, "1990", "10") == "applies"
    assert decide(CA_CAP, "2019", "10") == "not_covered"
    assert decide(CA_CAP, "2011", "10") == "unknown"


def test_a_supplied_fact_settles_an_unknown():
    owner_rule = {"exempt_owner_occupied_max_units": 2}
    assert decide(owner_rule, "1950", "2") == "unknown"
    assert decide(owner_rule, "1950", "2", owner_occupied="yes") == "not_covered"
    assert decide(owner_rule, "1950", "2", owner_occupied="no") == "applies"
    assert decide(owner_rule, "1950", "8") == "applies"


def test_census_rejects_a_match_to_another_house_number():
    row = {"address_id": "A0009", "postal_city": "Cambridge", "state": "MA"}
    assert resolve(row)["city"] == "Cambridge"


def test_neighborhood_resolves_to_city_with_census_evidence():
    row = {"address_id": "A0065", "postal_city": "Dorchester", "state": "MA"}
    where = resolve(row)
    assert where["city"] == "Boston"
    assert where["method"] == "census"
