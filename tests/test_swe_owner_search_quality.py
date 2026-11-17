"""Owner-reported CI 82 failures: SWE relevance, required years and postal-origin safety."""

import app as app_module


def _search(**overrides):
    return {
        "search_mode": "shortlist",
        "occupation": "software developer",
        "match_policy": "apply_broadly",
        "seniority": "entry_level,junior",
        "maximum_required_years": 3,
        "distance": 20,
        "include_provisional_matches": True,
        **overrides,
    }


def _job(**overrides):
    return {
        "title": "Junior Software Developer",
        "role_type": "developer",
        "discovery_occupation": "software developer",
        "discovery_search_mode": "shortlist",
        "discovery_match_policy": "apply_broadly",
        "discovery_seniority": "entry_level,junior",
        "discovery_maximum_required_years": 3,
        "job_description": "Build and maintain backend services in Python and SQL.",
        "qualification_fit_seniority": {"detected_level": "junior"},
        "remote_type": "Remote",
        "distance_radius_status": "not_checked",
        **overrides,
    }


def test_nonsoftware_developer_titles_are_not_new_swe_matches():
    assert not app_module.plausible_software_role(_job(title="Sustainability Packaging Developer"))
    assert not app_module.plausible_software_role(_job(title="Production support - Mainframe (NOT developer)"))
    assert app_module.plausible_software_role(_job(title="Junior Backend Software Developer"))
    assert app_module.discovery_target_assessment(
        _job(title="Sustainability Packaging Developer"), _search()
    )[0] == "ineligible"


def test_no_glassdoor_description_is_review_only_not_qualified():
    job = _job(job_description="", required_skills="", preferred_skills="", responsibilities="")
    status, reason = app_module.discovery_target_assessment(job, _search())
    assert status == "review_required"
    assert "no usable requirements" in reason.lower()
    assert not app_module.discovery_target_eligible(job, _search())


def test_qualification_unavailable_is_review_only():
    job = _job(qualification_match_status="unavailable")
    status, _ = app_module.discovery_target_assessment(job, _search())
    assert status == "review_required"


def test_unclassified_five_years_is_review_only_until_evidence_classified():
    job = _job(
        job_description="We seek a developer with 5 to 7 years of experience.",
        qualification_fit_seniority={
            "detected_level": "unknown",
            "ambiguous_experience": [{"minimum": 5, "maximum": 7, "source_evidence": "5 to 7 years of experience"}],
        },
    )
    status, reason = app_module.discovery_target_assessment(job, _search())
    assert status == "review_required"
    assert "5-year" in reason
    assert not app_module.discovery_target_eligible(job, _search())


def test_confirmed_seven_year_requirement_is_ineligible():
    job = _job(qualification_fit_seniority={"detected_level": "unknown", "required_experience": {"minimum": 7}})
    assert app_module.discovery_target_assessment(job, _search())[0] == "ineligible"


def test_intermediate_engineer_not_a_junior_match_when_selected_junior_only():
    job = _job(title="Software Engineer II, Backend", qualification_fit_seniority={"detected_level": "intermediate"})
    assert app_module.discovery_target_assessment(job, _search())[0] == "ineligible"


def test_unknown_local_distance_not_counted_as_a_verified_20km_match():
    job = _job(remote_type="On-site", distance_radius_status="unknown", distance_km=9999)
    status, reason = app_module.discovery_target_assessment(job, _search())
    assert status == "review_required"
    assert "radius" in reason.lower()
    assert not app_module.discovery_target_eligible(job, _search())


def test_remote_job_does_not_require_commute_distance():
    job = _job(remote_type="Remote", distance_radius_status="unknown")
    assert app_module.discovery_target_assessment(job, _search())[0] == "provisional"
    assert app_module.discovery_target_eligible(job, _search())


def test_failed_postal_origin_is_not_replaced_with_home_coordinates():
    location_context = {
        "distance_origin": "M2J 0B6",
        "distance_origin_lookup": {"ok": False, "status": "network_error", "error": "offline"},
    }
    fallback = {"latitude": 43.7, "longitude": -79.4, "status": "saved", "input": "Home"}
    origin = app_module.resolve_search_distance_origin(location_context, fallback)
    assert origin["input"] == "M2J 0B6"
    assert origin["status"] == "network_error"
    assert "latitude" not in origin
    assert origin["error"] == "offline"


def test_successful_postal_origin_preserves_coordinates_and_provenance():
    location_context = {
        "distance_origin": "M2J 0B6",
        "distance_origin_lookup": {
            "ok": True, "status": "cached", "original_input": "M2J 0B6",
            "normalized_query": "M2J 0B6", "latitude": 43.77, "longitude": -79.35,
            "precision": "postal", "provider": "fixture",
        },
    }
    origin = app_module.resolve_search_distance_origin(location_context, {})
    assert origin["latitude"] == 43.77
    assert origin["status"] == "cached"
    assert origin["precision"] == "postal"
