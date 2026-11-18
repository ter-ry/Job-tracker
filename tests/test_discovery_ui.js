const assert = require("assert");
const fs = require("fs");

const html = fs.readFileSync("templates/index.html", "utf8");
const js = fs.readFileSync("static/app.js", "utf8");
const css = fs.readFileSync("static/styles.css", "utf8");
const policy = require("../static/eligibility-policy.js");

function count(text, needle) {
  return text.split(needle).length - 1;
}

// The user-facing defaults are desired new matches, never raw provider rows.
assert.match(html, /id="discovery-new-matching-target"[^>]*value="50"/);
assert.match(html, /id="saved-search-new-target"[^>]*value="50"/);
assert.match(js, /new_matching_target: Number\(value\("discovery-new-matching-target"\) \|\| 50\)/);
assert.doesNotMatch(html, /id="discovery-total-cap"[^>]*type="number"/);
assert.doesNotMatch(html, /id="discovery-per-source-cap"[^>]*type="number"/);

// Both workflows, applicant switching, and useful title/seniority controls stay wired.
assert.match(html, /value="software"/);
assert.match(html, /value="ece"/);
assert.match(html, /id="discovery-title-match-mode"/);
assert.match(html, /id="discovery-seniority"/);
assert.match(html, /id="discovery-maximum-years"/);
assert.match(js, /state\.discoveryInboxJobs = \[\];[\s\S]*loadDiscoveryInbox\(true\)/);
assert.match(js, /candidate_profile_id \|\| ""/);

// Result categories are explicit and excluded jobs never enter the main queue.
assert.match(js, /renderGroup\("New Opportunities"/);
assert.doesNotMatch(js, /renderGroup\("Verified matches"/);
assert.doesNotMatch(js, /renderGroup\("Provisional matches"/);
assert.doesNotMatch(js, /renderGroup\("Review required"/);
assert.match(js, /state\.discoveryExcludedResults = responseJobs\.filter/);
assert.match(js, /state\.discoveryResults = merged\.filter\(\(job\) => job\.discovery_result_category === "actionable"\)/);

// Actions are applicant-scoped and update local state immediately.
for (const endpoint of ["/save", "/applied", "/ignore"]) {
  assert.match(js, new RegExp(endpoint.replace("/", "\\/")));
}
assert.match(js, /candidate_profile_id/);
assert.match(js, /function removeActiveDiscoveryJob/);
assert.match(js, /function restoreInboxJob/);

// Progressive continuation is opt-in to an explicit backend contract.
assert.match(js, /function continuationContract/);
assert.match(js, /Continue Search is not available for this search response yet/);
assert.match(js, /continuation_available/);
assert.doesNotMatch(html, /id="discovery-continue"/);
assert.match(html, /id="discovery-include-provisional"/);
assert.match(html, /id="discovery-geographic-match-mode"/);
assert.match(html, /id="discovery-include-internships"/);
assert.match(html, /id="open-all-discovered"/);
assert.match(js, /setDiscoverySection\("saved"\)/);
assert.match(js, /function tryProgressiveDiscoverySearch/);
assert.match(js, /search_id/);
assert.match(js, /new_jobs \|\| payload\.jobs/);
assert.match(js, /function stopProgressiveDiscoverySearch/);
assert.match(js, /function acknowledgeRenderedDiscoveryJobs/);
assert.match(js, /\/delivered/);
assert.match(js, /renderDiscoveryResults\(state\.discoveryMeta\);\s*acknowledgeRenderedDiscoveryJobs/);
assert.match(html, /id="discovery-match-policy"/);
assert.match(html, /id="fast-apply-open"/);
assert.match(js, /function openFastApply/);
assert.match(js, /Why the requested target was not reached/);
assert.match(js, /Cancellation acknowledged/);
assert.match(js, /"paused", "completed", "completed_with_errors"/);
assert.match(js, /outcome\.status === 202 && result\.search_id/);
assert.match(js, /retaining earlier results while new provider batches arrive/);
assert.match(js, /function loadCandidateProfiles/);
assert.match(js, /candidateProfilesStatus = "error"/);
assert.match(js, /Retry/);
assert.match(js, /discoveryInboxSearchId/);
assert.match(js, /function discoveryInboxRequestUrl/);
assert.match(js, /params\.set\("category", "review_required"\)/);
assert.match(js, /params\.set\("search_id", String\(searchId\)\)/);
assert.match(js, /Showing search/);
assert.match(js, /Return to full Inbox/);
assert.match(js, /category !== "review_required"/);

// Experience, salary, and workplace wording remain evidence-safe.
for (const label of ["Detected seniority", "Required experience", "Preferred experience", "Applicant demonstrated experience", "Experience fit", "Technical compatibility"]) {
  assert.ok(count(js, label) >= 1, `missing experience label: ${label}`);
}
assert.match(js, /Pay period unverified/);
assert.match(js, /Exact workplace unconfirmed/);
assert.match(js, /View area on map/);
assert.match(js, /sourceDiagnosticStatus/);
assert.match(js, /discovery_result_reason/);
assert.match(js, /data-discovery-no-new-reason/);
assert.match(css, /discovery-result-group/);

// The pure policy never uses a low ranking score as a hard rejection.
const junior = policy.assess({
  role_type: "software developer",
  occupation_match_type: "exact",
  qualification_fit_seniority: { detected_level: "junior", required_experience: { minimum: 1 } },
  application_priority_score: 20,
}, { maximum_required_years: 3 });
assert.notStrictEqual(junior.status, "excluded");
assert.strictEqual(policy.assess({
  role_type: "software developer",
  occupation_match_type: "exact",
  qualification_fit_seniority: { detected_level: "senior", required_experience: { minimum: 8 } },
}, { maximum_required_years: 3 }).status, "excluded");
assert.strictEqual(policy.assess({
  role_type: "software developer",
  occupation_match_type: "exact",
  qualification_fit_seniority: { detected_level: "junior", required_experience: { minimum: 1 } },
  geographic_eligibility: "city_only",
  distance_km: 9999,
}, { maximum_required_years: 3 }).status, "provisional");

// Synthetic release-audit fixtures: names/descriptions are intentionally local
// regression data, not claims about live postings or candidate experience.
const fixtures = [
  ["Hootsuite", { title: "Junior Software Developer", role_type: "software developer", occupation_match_type: "exact", geographic_eligibility: "exact", distance_km: 8, qualification_fit_seniority: { detected_level: "junior", required_experience: { minimum: 1 } } }, "verified"],
  ["Priceline", { title: "Associate Software Developer", role_type: "software developer", occupation_match_type: "exact", geographic_eligibility: "exact", distance_km: 8, qualification_fit_seniority: { detected_level: "entry_level", required_experience: { minimum: 0 } } }, "verified"],
  ["UHN", { title: "Software Developer", job_description: "Build software with the product engineering team.", role_type: "software developer", occupation_match_type: "exact", geographic_eligibility: "exact", distance_km: 8, qualification_fit_seniority: { detected_level: "intermediate", required_experience: { minimum: 2 } } }, "verified"],
  ["BMO", { title: "Software Developer — New or Recent Graduate", job_description: "New or recent graduate opportunity; numeric experience context requires review.", role_type: "software developer", occupation_match_type: "exact", qualification_fit_seniority: { detected_level: "unknown", required_experience: { minimum: 4 } } }, "review_required"],
  ["TOPBOX", { title: "Marketing Coordinator", role_type: "marketing", occupation_match_type: "unrelated" }, "excluded"],
  ["Leap", { title: "Senior Software Engineer", role_type: "software developer", occupation_match_type: "exact", qualification_fit_seniority: { detected_level: "senior", required_experience: { minimum: 6 } } }, "excluded"],
];
for (const [name, job, expected] of fixtures) {
  assert.strictEqual(policy.assess(job, { maximum_required_years: 3 }).status, expected, `${name} fixture classification`);
}
assert.strictEqual(policy.assess({ title: "Software Engineering Intern", role_type: "internship", occupation_match_type: "exact" }, { include_internships: false }).status, "excluded");
assert.notStrictEqual(policy.assess({ title: "Software Engineering Intern", role_type: "internship", occupation_match_type: "exact" }, { include_internships: true }).status, "excluded");

console.log("discovery UI regression checks passed");
