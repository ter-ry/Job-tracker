import app
from seniority import analyze_job_seniority


def _swe(title, description="Technology company posting."):
    return {
        "title": title,
        "discovery_occupation": "software developer",
        "discovery_search_mode": "shortlist",
        "discovery_match_policy": "apply_broadly",
        "remote_type": "Remote",
        "remote_search_eligible": "true",
        "remote_eligibility": "canadian_eligible",
        "job_description": description,
    }


def test_goal_b_documented_unrelated_swe_false_positives_are_excluded():
    titles = [
        "Clearco Associate, FP&A", "Maple Client Success Associate",
        "ShyftLabs Business Development Intern", "ShyftLabs Graphic Design Intern",
        "Wealthsimple Margin Supervision Specialist", "Achievers Customer Success Associate",
        "PolicyMe Growth Associate", "MLSE Development Officer", "CBC Producer",
        "Porter Talent Development", "RNC Employment Consultant", "CIBC Training Specialist",
        "Mad Engine Product Developer", "Insurance Sales Associate", "Accounting Assistant",
        "Executive Assistant", "CNC Programmer", "Civil Engineer",
    ]
    assert all(app.discovery_result_category(_swe(title))[0] == "excluded" for title in titles)


def test_owner_false_positive_titles_use_responsibilities_and_keep_fsra_full_stack():
    for title in ("Maple AR Specialist", "Achievers Customer Support Associate", "Clearco Finance Analyst", "Wealthsimple HR Benefits Specialist", "Clearco Account Executive", "PolicyMe Insurance Sales Associate", "Wealthsimple Art Director"):
        assert app.discovery_result_category(_swe(title))[0] == "excluded"
    fsra = _swe("Technical Lead (Full Stack Developer)", "Build and maintain full-stack web applications, APIs, automated tests, and deployment pipelines.")
    assert not app.clearly_non_software_role(fsra)
    assert app.discovery_result_category(fsra)[0] != "excluded"


def test_goal_b_adjacent_technical_roles_and_senior_stretch_remain_available():
    for title in ("Cloud Administrator", "Salesforce Administrator", "Systems Administrator", "Database Administrator", "Technical Consultant", "Technical Specialist", "Software Product Developer", "Research Scientist"):
        job = _swe(title, "Maintain production systems, SQL databases, APIs and automation.")
        assert app.plausible_software_role(job)
        assert app.discovery_result_category(job)[0] != "excluded"
    senior = _swe("Senior Software Engineer", "Required: 8+ years of professional software development.")
    senior["qualification_fit_seniority"] = analyze_job_seniority(senior)
    assert app.discovery_result_category(senior)[0] == "actionable"
    hands_on_manager = _swe("Technical Engineering Manager", "Build Python services and APIs. This role has no direct reports and no people management.")
    assert app.plausible_software_role(hands_on_manager)
    people_manager = _swe("Engineering Manager", "Manage a team of engineers, own hiring and performance reviews.")
    assert not app.plausible_software_role(people_manager)
    assert app.discovery_result_category(people_manager)[0] == "excluded"
    assert app.discovery_result_category(_swe("Commercial Product Developer"))[0] == "excluded"


def test_goal_b_description_junior_reference_does_not_override_unlevelled_title():
    analysis = analyze_job_seniority({
        "title": "Developer",
        "job_description": "Mentor junior developers and collaborate with the platform team. Requires 5+ years of software development.",
    })
    assert analysis["detected_level"] == "senior"
    assert analysis["description_level"] == "unknown"
    surrounding = analyze_job_seniority({
        "title": "Developer",
        "job_description": "Supports senior engineers and assists the lead architect. Builds APIs and services.",
    })
    assert surrounding["description_level"] == "unknown"


def test_goal_b_experience_context_preserves_required_preferred_and_ages():
    analysis = analyze_job_seniority({
        "title": "Software Engineer",
        "job_description": (
            "The company has 35 years of history. Applicants must be 18+ years of age.\n"
            "Requirements\n3+ years of software development; 2–5 years of API work.\n"
            "Preferred\n7+ years of cloud experience. Children aged 1.5 years may attend."
        ),
    })
    assert analysis["required_experience"]["minimum"] == 3
    assert analysis["preferred_experience"]["minimum"] == 7
    assert "35" not in analysis["required_experience"]["source_evidence"]
    assert "1.5" not in str(analysis)


def test_goal_b_ece_contextual_employment_and_mixed_titles():
    def classify(title, description):
        return app.ece_result_category({
            "title": title,
            "job_description": description,
            "discovery_occupation": "early childhood educator",
        })

    status, _ = classify("Little Einstein Registered Early Child Educator", "Full-time educator role.")
    assert status == "actionable"
    supply, _ = classify("Park Lawn Supply RECEs and ECAs", "Supply position for RECEs and ECAs.")
    assert supply == "actionable"
    mixed, _ = classify("Withrow ECE/ECA Supply", "Seeking early childhood assistants only.")
    assert mixed == "excluded"
    educator_duties, _ = classify(
        "Withrow ECE/ECA Supply",
        "Seeking early childhood assistants only. The educator will plan curriculum, supervise children, document observations, and lead classroom learning.",
    )
    assert educator_duties == "actionable"
    teacher, _ = classify("Kindergarten Teacher", "ECE eligibility is an asset.")
    assert teacher == "review_required"
    full_time, _ = classify("Full-time RECE Educator", "The educator works alongside casual colleagues.")
    assert full_time == "actionable"
    staff_mention, _ = classify("Full-time RECE Educator", "Work with ECA staff and support the classroom team.")
    assert staff_mention == "actionable"
    mixed_ece, _ = classify("ECE/ECA Educator", "Full-time early years educator opportunity.")
    assert mixed_ece == "actionable"


def test_goal_b_default_ranking_keeps_unknown_neutral_and_ece_supply_last():
    unknown = {"title": "Software Developer", "application_priority_score": 90, "qualification_fit_seniority": {"detected_level": "unknown"}}
    senior = {"title": "Senior Software Engineer", "application_priority_score": 90, "qualification_fit_seniority": {"detected_level": "senior"}}
    assert app.discovery_sort_value(unknown, "application_priority_score") < app.discovery_sort_value(senior, "application_priority_score")
    common = {"discovery_occupation": "early childhood educator", "application_priority_score": 90}
    permanent = {**common, "title": "RECE permanent", "discovery_employment_status": "permanent_full_time"}
    temporary = {**common, "title": "RECE contract", "discovery_employment_status": "temporary_full_time"}
    supply = {**common, "title": "Supply RECE", "discovery_employment_status": "supply_or_casual"}
    ordered = sorted((supply, temporary, permanent), key=lambda job: app.discovery_sort_value(job, "application_priority_score"))
    assert ordered == [permanent, temporary, supply]
