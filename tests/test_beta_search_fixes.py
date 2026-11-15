"""Deterministic regressions for the private-beta search reliability fixes."""

import app


def _search(**changes):
    value = {
        "search_mode": "shortlist", "occupation": "software developer",
        "seniority": "entry_level,junior", "maximum_required_years": 3,
        "include_provisional_matches": True,
    }
    value.update(changes)
    return value


def _job(**changes):
    value = {
        "title": "Software Developer", "seniority_level": "unknown",
        "qualification_fit_seniority": {"detected_level": "unknown", "required_experience": {}},
    }
    value.update(changes)
    return value


def test_topbox_like_unknown_seniority_is_provisional_not_senior_mismatch():
    status, reason = app.discovery_target_assessment(_job(), _search())
    assert status == "provisional"
    assert "not stated" in reason
    assert app.discovery_target_eligible(_job(), _search())


def test_explicit_senior_and_confirmed_excess_years_are_hard_blockers():
    senior = _job(seniority_level="senior", qualification_fit_seniority={"detected_level": "senior", "required_experience": {}})
    years = _job(qualification_fit_seniority={"detected_level": "junior", "required_experience": {"minimum": 5}})
    assert app.discovery_target_assessment(senior, _search())[0] == "ineligible"
    assert app.discovery_target_assessment(years, _search())[0] == "ineligible"


def test_unknown_city_location_is_provisional_but_strict_radius_requires_evidence():
    base = {"remote_type": "On-site", "location": "Toronto, ON", "distance_km": 9999, "application_priority_score": 80}
    provisional = app.apply_discovery_search_constraints(dict(base), "", "Toronto, ON", 50, "provisional")
    strict = app.apply_discovery_search_constraints(dict(base), "", "Toronto, ON", 50, "strict")
    assert provisional["geographic_eligibility"] == "provisional"
    assert app.discovery_result_category(provisional)[0] == "actionable"
    assert app.discovery_result_category(strict)[0] == "review_required"


def test_zero_radius_disables_distance_enforcement_and_remote_has_no_commute_gate():
    onsite = app.apply_discovery_search_constraints({"remote_type": "On-site", "location": "Toronto", "distance_km": 9999}, "", "Toronto", 0)
    remote = app.apply_discovery_search_constraints({"remote_type": "Remote", "remote_eligibility": "canadian_eligible", "distance_radius_status": "unknown"}, "remote", "Toronto", 50)
    assert onsite["distance_radius_status"] == "not_checked"
    assert app.discovery_result_category(remote, "remote")[0] == "actionable"
