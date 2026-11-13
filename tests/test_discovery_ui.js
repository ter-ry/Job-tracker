const assert = require("assert");
const fs = require("fs");

const html = fs.readFileSync("templates/index.html", "utf8");
const js = fs.readFileSync("static/app.js", "utf8");
const css = fs.readFileSync("static/styles.css", "utf8");

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
assert.match(js, /renderGroup\("New matches"/);
assert.match(js, /renderGroup\("Review required"/);
assert.match(js, /state\.discoveryExcludedResults = responseJobs\.filter/);
assert.match(js, /job\.discovery_result_category !== "excluded"/);

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

// Experience, salary, and workplace wording remain evidence-safe.
for (const label of ["Detected seniority", "Required experience", "Preferred experience", "Applicant demonstrated experience", "Experience fit", "Technical compatibility"]) {
  assert.ok(count(js, label) >= 1, `missing experience label: ${label}`);
}
assert.match(js, /Pay period unverified/);
assert.match(js, /Exact workplace unconfirmed/);
assert.match(js, /View area on map/);
assert.match(js, /sourceDiagnosticStatus/);
assert.match(css, /discovery-result-group/);

console.log("discovery UI regression checks passed");
