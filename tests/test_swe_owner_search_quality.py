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


def test_unknown_local_distance_retained_only_as_labelled_provisional_in_city_mode():
    job = _job(remote_type="On-site", distance_radius_status="unknown", distance_km=9999)
    search = _search(geographic_match_mode="provisional")
    status, reason = app_module.discovery_target_assessment(job, search)
    assert status == "provisional"
    assert "unverified commute" in reason.lower()
    assert "does not establish" in reason.lower()
    assert app_module.discovery_target_eligible(job, search)
    # Same posting cannot pass the strict distance gate without coordinates.
    strict = _search(geographic_match_mode="strict")
    strict_status, strict_reason = app_module.discovery_target_assessment(job, strict)
    assert strict_status == "review_required"
    assert "strict-radius" in strict_reason.lower()
    assert not app_module.discovery_target_eligible(job, strict)


def test_unknown_distance_never_overrides_confirmed_seniority_or_experience_exclusion():
    job = _job(
        remote_type="On-site",
        distance_radius_status="unknown",
        distance_km=9999,
        qualification_fit_seniority={"detected_level": "junior", "required_experience": {"minimum": 7}},
    )
    assert app_module.discovery_target_assessment(job, _search(geographic_match_mode="provisional"))[0] == "ineligible"


def test_missing_requirements_remain_review_only_even_in_provisional_geography_mode():
    job = _job(remote_type="On-site", distance_radius_status="unknown", job_description="")
    status, _ = app_module.discovery_target_assessment(job, _search(geographic_match_mode="provisional"))
    assert status == "review_required"


def test_toronto_search_postal_does_not_inherit_an_unrelated_profile_city():
    class UnresolvedProvider:
        name = "offline"

        def geocode(self, query, country="Canada"):
            raise TimeoutError("provider unavailable")

    context = app_module.resolve_discovery_location_context(
        "M2J0B6",
        profile={"home_location_normalized": "Ottawa, ON"},
        provider=UnresolvedProvider(),
        use_cache=False,
    )
    assert context["discovery_location"] == "Toronto, ON"
    assert context["distance_origin"] == "M2J 0B6"
    assert not context["distance_origin_lookup"]["ok"]



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


def test_nominatim_asks_for_postal_details_and_prefers_exact_candidate(monkeypatch):
    import json

    returned = [
        {
            "lat": "43.653", "lon": "-79.383", "display_name": "Toronto, Ontario, Canada",
            "address": {"postcode": "M2J 0B5"}, "type": "postcode",
        },
        {
            "lat": "43.770", "lon": "-79.350", "display_name": "M2J 0B6, Toronto, Ontario, Canada",
            "address": {"postcode": "M2J 0B6"}, "type": "postcode",
        },
    ]
    urls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(returned).encode("utf-8")

    def fake_urlopen(request, timeout):
        urls.append(request.full_url)
        return Response()

    monkeypatch.setattr(app_module.urllib.request, "urlopen", fake_urlopen)
    lookup = app_module.NominatimGeocodingProvider().geocode("M2J 0B6, Canada")
    assert "addressdetails=1" in urls[0]
    assert lookup["postal_code"] == "M2J 0B6"
    assert lookup["latitude"] == 43.77
    assert app_module.geocode_matches_canadian_location("M2J 0B6", lookup)


def test_wrong_postal_result_stays_rejected_even_with_addressdetails(monkeypatch):
    import json

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps([
                {
                    "lat": "43.653", "lon": "-79.383", "display_name": "Toronto, Ontario, Canada",
                    "address": {"postcode": "M2J 0B5"}, "type": "postcode",
                },
            ]).encode("utf-8")

    monkeypatch.setattr(app_module.urllib.request, "urlopen", lambda request, timeout: Response())
    lookup = app_module.NominatimGeocodingProvider().geocode("M2J 0B6, Canada")
    assert not app_module.geocode_matches_canadian_location("M2J 0B6", lookup)


def test_neighbouring_gta_municipalities_are_not_excluded_before_radius_evidence():
    for advertised in ("North York, ON", "Markham, ON", "Vaughan, ON", "Scarborough, ON"):
        posting = {
            "location": advertised, "remote_type": "On-site",
            "distance_km": 9999, "distance_confidence": 0,
            "application_priority_score": 80,
        }
        evaluated = app_module.apply_discovery_search_constraints(
            posting, "", "Toronto, ON", 20, "provisional"
        )
        assert evaluated["location_search_eligible"] is True, advertised
        assert evaluated["distance_radius_status"] == "unknown", advertised
        assert evaluated["geographic_eligibility"] == "provisional", advertised


def test_strict_radius_keeps_nearby_city_without_distance_in_needs_review():
    posting = {
        "location": "Markham, ON", "remote_type": "On-site",
        "distance_km": 9999, "distance_confidence": 0,
    }
    evaluated = app_module.apply_discovery_search_constraints(
        posting, "", "Toronto, ON", 20, "strict"
    )
    assert evaluated["distance_radius_status"] == "unknown"
    assert evaluated["geographic_eligibility"] == "unverified"
    assert evaluated["location_search_eligible"] is None


def test_confirmed_other_province_or_outside_radius_still_excluded():
    posting = {"location": "Vancouver, BC", "remote_type": "On-site", "distance_km": 9999}
    other_province = app_module.apply_discovery_search_constraints(
        posting, "", "Toronto, ON", 20, "provisional"
    )
    assert other_province["location_search_eligible"] is False
    assert "province" in " ".join(other_province["application_priority_reasons"]).lower()

    far = {"location": "Markham, ON", "remote_type": "On-site", "distance_km": 27, "distance_confidence": 90}
    outside = app_module.apply_discovery_search_constraints(far, "", "Toronto, ON", 20, "provisional")
    assert outside["distance_radius_status"] == "outside_radius"
    assert outside["location_search_eligible"] is False
