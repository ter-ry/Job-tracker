"""Deterministic regressions for the private-beta search reliability fixes."""

from pathlib import Path

import app


def _search(**changes):
    value = {
        "search_mode": "shortlist", "occupation": "software developer",
        "match_policy": "apply_broadly",
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
    # A usable posting description permits provisional review when seniority
    # is unstated. A title-only provider row instead belongs in Needs Review.
    candidate = _job(job_description="Build and maintain Python applications and unit tests.", remote_type="Remote")
    status, reason = app.discovery_target_assessment(candidate, _search())
    assert status == "provisional"
    assert "résumé" in reason.lower() or "resume" in reason.lower()
    assert app.discovery_target_eligible(candidate, _search())


def test_explicit_senior_and_confirmed_excess_years_are_strict_only_blockers():
    senior = _job(seniority_level="senior", qualification_fit_seniority={"detected_level": "senior", "required_experience": {}})
    years = _job(qualification_fit_seniority={"detected_level": "junior", "required_experience": {"minimum": 5}})
    assert app.discovery_target_assessment(senior, _search())[0] == "provisional"
    assert app.discovery_target_assessment(years, _search())[0] == "provisional"
    strict = _search(match_policy="strict_matching")
    assert app.discovery_target_assessment(senior, strict)[0] == "ineligible"
    assert app.discovery_target_assessment(years, strict)[0] == "ineligible"


def test_provider_intern_label_does_not_exclude_non_intern_title():
    job = _job(title="Software Developer", role_type="intern", discovery_include_internships=False,
               discovery_occupation="software developer", job_description="Build production APIs.")
    assert app.discovery_result_category(job)[0] != "excluded"


def test_broad_swe_scope_excludes_grounded_unrelated_title_without_occupation_field():
    job = _job(title="CNC Machinist", discovery_match_policy="apply_broadly", discovery_search_mode="shortlist")
    assert app.discovery_result_category(job)[0] == "excluded"


def test_implausibly_large_experience_value_stays_reviewable():
    job = _job(title="Junior Software Developer", job_description="Requirements: 35+ years of experience.",
               qualification_fit_seniority={"detected_level": "unknown", "required_experience": {"minimum": 35}})
    status, reason = app.discovery_target_assessment(job, _search())
    assert status == "provisional"
    assert "stretch" in reason.lower()


def test_canonical_url_drops_provider_tracking_and_www_aliases():
    assert app.canonical_url("https://www.example.test/jobs/42/?utm_source=feed&ref=abc") == "https://example.test/jobs/42"
    assert app.canonical_url("https://ATS.example/jobs/ReqABC?utm_source=feed&req=ReqABC") == "https://ats.example/jobs/ReqABC?req=ReqABC"
    assert app.canonical_url("https://ats.example/jobs/ReqABC") != app.canonical_url("https://ats.example/jobs/reqabc")


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


def test_ci73_swe_seniority_and_experience_are_ranked_broadly_but_block_strict_matching():
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
        assert category != "excluded", (title, category, reason)
        assert app.discovery_target_assessment(job, search)[0] != "ineligible"
        strict = dict(job, discovery_match_policy="strict_matching")
        assert app.discovery_result_category(strict)[0] in {"excluded", "review_required"}
        assert app.discovery_target_assessment(strict, dict(search, match_policy="strict_matching"))[0] == "ineligible"


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


def test_swe_broad_seniority_remains_visible_while_strict_matching_excludes_it():
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
        assert category != "excluded", (category, reason)
        assert app.discovery_target_assessment(job, search)[0] != "ineligible"
        strict = dict(search, match_policy="strict_matching")
        assert app.discovery_target_assessment(job, strict)[0] == "ineligible"


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
    assert app.discovery_target_assessment(td, search)[0] != "ineligible"
    assert app.discovery_result_category(td)[0] != "excluded"
    assert app.discovery_target_assessment(td, dict(search, match_policy="strict_matching"))[0] == "ineligible"
    assert app.plausible_software_role(academic) is False
    assert app.plausible_software_role(amex) is True
    assert app.discovery_result_category(amex)[0] != "excluded"


def test_raw_provider_text_drives_td_five_year_exclusion_without_injected_analysis(monkeypatch, tmp_path):
    """Exercise provider payload -> extraction -> scoring -> final policy."""
    raw = {
        "source": "indeed",
        "source_job_id": "td-raw-five-years",
        "title": "Software Engineer II (Full Stack)",
        "company": "TD",
        "location": "Toronto, ON",
        "job_url": "https://ca.indeed.com/viewjob?jk=td-raw-five-years",
        "description": (
            "Minimum qualifications: 5+ years of professional software engineering "
            "experience. Build and maintain full-stack applications with Python and React."
        ),
        "job_type": "full-time",
    }
    converted = app.jobspy_result_to_job_payload(raw)
    assert "required_experience" not in converted
    assert "qualification_fit_seniority" not in converted
    assert "5+ years" in converted["job_description"]

    monkeypatch.setattr(app, "DATA_DIR", Path(tmp_path))
    monkeypatch.setattr(app, "DB_PATH", Path(tmp_path) / "raw-td.sqlite")
    client = app.app.test_client()
    client.get("/api/health")
    fetched = {
        "jobs": [raw], "errors": {}, "source_counts": {"indeed": 1},
        "source_diagnostics": {"indeed": {"state": "completed", "result_count": 1}},
        "source_snapshots": {}, "attempted_query_batches": [],
        "completed_query_batches": [], "pending_query_batches": [],
    }
    monkeypatch.setattr(app, "fetch_discovery_jobs_for_search", lambda *args, **kwargs: fetched)
    monkeypatch.setattr(
        app, "geocode_discovery_job",
        lambda job, *_args, **_kwargs: ({**job, "distance_km": 9999, "location_search_eligible": True}, {"ok": False}),
    )
    payload = {
        "keywords": "software developer",
        "location": "Toronto, ON",
        "enabled_sources": ["indeed"],
        "search_mode": "shortlist",
        "occupation": "software developer",
        "match_policy": "apply_broadly",
        "seniority": "entry_level,junior",
        "maximum_required_years": 3,
        "new_matching_target": 3,
    }
    with app.app.app_context():
        result = app.run_discovery_pipeline(payload)
    assert result["jobs"]
    assert not result["excluded_jobs"]
    retained = result["jobs"][0]
    assert retained["discovery_result_category"] != "excluded"
    assert retained["qualification_fit_seniority"]["detected_level"] == "intermediate"
    assert retained["experience_requirements"]["required"]["minimum"] == 5
    assert retained["experience_requirements"]
    with app.app.app_context():
        row = app.query_db("SELECT discovery_result_category, job_description FROM jobs WHERE source_job_id = ?", ["td-raw-five-years"], one=True)
        assert row["discovery_result_category"] != "excluded"
        assert "5+ years" in row["job_description"]


def test_academic_titles_are_rejected_even_when_provider_role_family_is_software():
    search = _search(match_policy="apply_broadly")
    for title in (
        "Academic Assistant, Python Programming and Data Science",
        "Instructor, Software Programming",
        "Teacher, Computer Science",
    ):
        job = _swe_policy_job(title, "Teach students using Python and software tools.", role_type="software developer")
        assert app.plausible_software_role(job) is False
        assert app.discovery_target_assessment(job, search)[0] == "ineligible"


def test_owner_swe_adjacent_technical_roles_are_recall_first_candidates():
    search = _search(match_policy="apply_broadly", maximum_required_years=4)
    records = [
        ("Infrastructure Engineer", "Operate AWS cloud infrastructure, Terraform, Python automation and CI/CD."),
        ("Junior Solutions Engineer", "Implement customer integrations using APIs, JavaScript and cloud tooling."),
        ("AWS Developer", "Build Node.js services, deploy with AWS and maintain CI/CD pipelines."),
        ("Technical Specialist, JavaScript and React", "Implement React applications and Java services for clients."),
        ("Software Test Engineer", "Create automated software quality tests with Python and CI/CD."),
        ("Full Stack Developer", "Build full-stack applications with React, Python and SQL."),
        ("Software Engineer II, AI Engineering", "Build machine learning services and production software in Python."),
        ("Full-Stack Development Engineer", "Develop web applications and APIs with JavaScript and cloud services."),
        ("Backend Engineer", "Build backend APIs and database services with Python."),
        ("Front End Engineer", "Develop React and TypeScript user interfaces."),
        ("Intermediate Software Developer, DevOps", "Maintain software delivery pipelines, AWS and infrastructure automation."),
        ("Front End Engineer", "Build frontend applications with React and JavaScript."),
        ("Software Engineer II", "Develop distributed software services and APIs."),
        ("Software Engineer II", "Build production software systems and automated tests."),
        ("Software Dev Engineer II, Goodreads", "Develop web services and full-stack features with Java and APIs."),
    ]
    for title, description in records:
        job = _swe_policy_job(title, description)
        assert app.plausible_software_role(job), title
        assert app.discovery_target_assessment(job, search)[0] in {"provisional", "verified"}, title


def test_confirmed_unrelated_programming_titles_remain_excluded():
    for title in ("Community Programming Coordinator", "Fundraising Developer", "Employment Development Specialist"):
        job = _swe_policy_job(title, "Coordinate community events and employment development programs.")
        assert app.clearly_non_software_role(job)
        assert app.discovery_target_assessment(job, _search(match_policy="apply_broadly"))[0] == "ineligible"


def test_mojibake_salesjack_range_uses_lower_bound_and_not_upper_bound():
    description = "Requirements: 2â€“5 years of full-time full stack engineering experience after graduating."
    analysis = app.analyze_job_seniority({"title": "Software Engineer", "job_description": description})
    required = analysis["required_experience"]
    assert required["minimum"] == 2
    assert required["maximum"] == 5
    assert "2" in required["text"] and "5" in required["text"]
    assert app.discovery_target_assessment(
        {"title": "Software Engineer", "discovery_occupation": "software developer", "job_description": description, "qualification_fit_seniority": analysis},
        _search(match_policy="apply_broadly", maximum_required_years=3),
    )[0] != "ineligible"


def test_non_internship_and_mentoring_interns_do_not_become_intern_roles():
    for description in (
        "This is a non-internship full-time software engineering role.",
        "Mentor interns while building production APIs as a software engineer.",
    ):
        analysis = app.analyze_job_seniority({"title": "Software Engineer", "job_description": description})
        assert analysis["detected_level"] != "internship"
