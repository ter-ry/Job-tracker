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


def _swe_policy_job(title, description, **changes):
    value = _job(
        title=title,
        job_description=description,
        discovery_search_mode="shortlist",
        discovery_match_policy="apply_broadly",
        discovery_maximum_required_years=3,
        occupation_match_type="exact",
        title_match_score=100,
        remote_search_eligible="true",
        remote_eligibility="canadian_eligible",
        qualification_fit_seniority=app.analyze_job_seniority({"title": title, "job_description": description}),
        application_priority_score=99,
    )
    value.update(changes)
    return value


def test_ci73_swe_hard_exclusions_precede_apply_broadly_and_strict_matching():
    search = _search(match_policy="apply_broadly", seniority="entry_level,junior", maximum_required_years=3)
    excluded = [
        ("Senior Staff Software Developer", "Requirements: 10+ years of software development experience."),
        ("Staff Software Engineer", "Must have 8+ years of professional software engineering experience."),
        ("Senior Software Engineer", "Minimum qualifications include 6 years of software engineering experience."),
        ("Senior Software Developer", "7+ years of software development experience required."),
        ("Software Engineer II", "4+ years of professional engineering experience required."),
        ("Full Stack Developer", "Must have 5 years of full-stack development experience."),
    ]
    for title, description in excluded:
        job = _swe_policy_job(title, description)
        category, reason = app.discovery_result_category(job)
        assert category == "excluded", (title, category, reason)
        assert "experience" in reason.lower() or "senior" in reason.lower(), reason
        assert app.discovery_target_assessment(job, search)[0] == "ineligible"
        strict = dict(job, discovery_match_policy="strict_matching")
        assert app.discovery_result_category(strict)[0] == "excluded"


def test_ci73_swe_eligible_junior_and_new_grad_roles_survive_hard_policy():
    search = _search(match_policy="apply_broadly", seniority="entry_level,junior", maximum_required_years=3)
    eligible = [
        ("Jr. Software Developer", "Requirements: 2–3 years of software development experience."),
        ("Junior Software Engineer", "Junior role; 2 years required."),
        ("Software Developer (New or Recent Graduate)", "Required: 1–3 years of experience."),
        ("Software Engineer I, Backend", "Entry-level role; no more than 3 years required."),
        ("Software Developer", "2 years required; 5 years preferred."),
    ]
    for title, description in eligible:
        job = _swe_policy_job(title, description)
        category, reason = app.discovery_result_category(job)
        assert category != "excluded", (title, category, reason)
        assert app.discovery_target_eligible(job, search)


def test_seniority_parser_prefers_associate_and_new_grad_title_signals():
    associate = app.analyze_job_seniority({"title": "Associate Software Developer", "job_description": "The team may lead technical initiatives."})
    graduate = app.analyze_job_seniority({"title": "Software Developer (New or Recent Graduate)", "job_description": "Build software with mentorship."})
    senior_staff = app.analyze_job_seniority({"title": "Senior Staff Software Developer", "job_description": "10+ years mentioned."})
    assert associate["detected_level"] in {"entry_level", "junior"}
    assert graduate["detected_level"] == "entry_level"
    assert senior_staff["detected_level"] in {"senior", "lead"}


def test_swe_hard_exclusions_precede_unknown_geography_and_remote_review():
    search = _search(match_policy="apply_broadly", maximum_required_years=3)
    unknown_radius = _swe_policy_job(
        "Senior Staff Software Engineer", "10+ years of software engineering experience required.",
        distance_radius_status="unknown", geographic_eligibility="unverified",
        location_search_eligible=True,
    )
    unknown_remote = _swe_policy_job(
        "Senior Software Engineer", "6 years of software engineering experience required.",
        remote_type="Remote", remote_search_eligible="", remote_eligibility="unknown",
        location_search_eligible=True,
    )
    for job in (unknown_radius, unknown_remote):
        category, reason = app.discovery_result_category(job, "remote" if job is unknown_remote else "")
        assert category == "excluded", (category, reason)
        assert app.discovery_target_assessment(job, search)[0] == "ineligible"
        assert "senior" in reason.lower() or "experience" in reason.lower()


def test_ci76_owner_swe_examples_do_not_leak_through_apply_broadly_fallbacks():
    search = _search(match_policy="apply_broadly", maximum_required_years=3)
    td = _swe_policy_job(
        "Software Engineer II (Full Stack)",
        "Minimum qualifications: 5+ years of professional software engineering experience.",
        qualification_fit_seniority={"detected_level": "intermediate", "required_experience": {"minimum": 5}},
        distance_radius_status="unknown", geographic_eligibility="unverified",
    )
    academic = _swe_policy_job(
        "Academic Assistant, Python Programming and Data Science",
        "Support students with Python and data science programming.",
        role_type="",
        qualification_fit_seniority={"detected_level": "unknown", "required_experience": {}},
    )
    amex = _swe_policy_job(
        "Campus Software Engineer I",
        "Entry-level software engineering role with mentorship.",
        qualification_fit_seniority={"detected_level": "entry_level", "required_experience": {"minimum": 0}},
    )
    assert app.discovery_target_assessment(td, search)[0] == "ineligible"
    assert app.discovery_result_category(td)[0] == "excluded"
    assert app.plausible_software_role(academic) is False
    assert app.plausible_software_role(amex) is True
    assert app.discovery_result_category(amex)[0] != "excluded"
