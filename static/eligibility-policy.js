// Pure, evidence-only target policy for the frontend. The backend remains the
// authority for filtering; this module provides a safe display fallback and a
// documented integration seam for the asynchronous search worker.
(function exposeEligibilityPolicy(root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.JobEligibilityPolicy = factory();
}(typeof window === "undefined" ? globalThis : window, function createEligibilityPolicy() {
  const seniorLevels = new Set(["senior", "lead", "principal", "staff", "manager", "director", "executive"]);

  function text(value) { return String(value == null ? "" : value).trim().toLowerCase(); }
  function code(code, detail) { return { code, detail }; }

  function assess(job = {}, criteria = {}) {
    const reasons = [];
    const analysis = job.qualification_fit_seniority || {};
    const level = text(analysis.detected_level || job.seniority_level).replaceAll("-", "_");
    const required = analysis.required_experience || job.experience_requirements?.required || {};
    const maximum = Number(criteria.maximum_required_years ?? 3);
    const roleType = text(job.role_type);
    const occupationMatch = text(job.occupation_match_type);
    const content = text(`${job.title || ""} ${job.job_description || job.description || ""}`);
    const newGraduateWording = /new\s*(?:or|\/)?\s*recent graduate|recent graduate|new grad/.test(content);
    const geographic = text(job.geographic_eligibility || job.geographic_match_status);

    if (text(job.posting_availability) === "confirmed_closed") return { status: "excluded", reasons: [code("confirmed_closed", "Posting is confirmed closed.")] };
    if (["unrelated", "confirmed_unrelated"].includes(roleType) || occupationMatch === "unrelated") return { status: "excluded", reasons: [code("occupation_mismatch", "Posting is not relevant to the selected occupation.")] };
    if (roleType === "internship" && !criteria.include_internships) return { status: "excluded", reasons: [code("internship_not_selected", "Internships are outside the selected junior-role eligibility policy.")] };
    if (seniorLevels.has(level) || analysis.management_role || analysis.leadership_expectations) return { status: "excluded", reasons: [code("seniority_restricted", "Explicit senior, lead, management, or director scope is outside the early-career target.")] };
    if (required.minimum != null && Number(required.minimum) > maximum && !newGraduateWording) return { status: "excluded", reasons: [code("required_experience_exceeds_target", `Required professional experience exceeds ${maximum} years.`)] };
    if (["outside_radius", "confirmed_ineligible", "confirmed_outside"].includes(geographic)) return { status: "excluded", reasons: [code("geography_mismatch", "Posting is confirmed outside the requested geographic scope.")] };

    if (!occupationMatch && !roleType) reasons.push(code("occupation_unverified", "Occupation relevance is not confirmed by the posting data."));
    if (!level || ["unknown", "ambiguous", "unverified"].includes(level)) reasons.push(code("seniority_unverified", "Seniority is not stated; it is not treated as senior or junior."));
    if (required.minimum == null) reasons.push(code("experience_unverified", "Required professional experience is not explicitly confirmed."));
    if (newGraduateWording && required.minimum != null && Number(required.minimum) > maximum) reasons.push(code("new_graduate_context_ambiguous", "New-graduate wording conflicts with a numeric experience context; review the original requirement."));
    if (roleType === "internship" && criteria.include_internships) reasons.push(code("internship_policy_selected", "Internship is retained because the user selected internship eligibility."));
    if (["unknown", "provisional", "city_only", "region_only"].includes(geographic) || (!geographic && (job.distance_km == null || Number(job.distance_km) >= 9999))) {
      reasons.push(code("workplace_unverified", "Exact workplace or distance is not verified."));
    }
    if (reasons.some((reason) => ["occupation_unverified", "seniority_unverified", "experience_unverified"].includes(reason.code))) return { status: "review_required", reasons };
    if (reasons.length) return { status: "provisional", reasons };
    return { status: "verified", reasons: [code("criteria_confirmed", "No hard eligibility blocker was found in the available posting evidence.")] };
  }

  return { assess };
}));
