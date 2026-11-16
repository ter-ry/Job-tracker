#!/usr/bin/env node

// Executed browser regression for the New Opportunities renderer and async
// polling path. It intentionally uses only disposable API responses and never
// writes application data.
const assert = require("node:assert");
const { chromium } = require("playwright");

const baseUrl = process.env.JOB_TRACKER_URL || "http://127.0.0.1:5000";

async function main() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM_PATH || "/usr/bin/chromium",
    args: ["--no-sandbox"],
  });
  const page = await browser.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.goto(baseUrl, { waitUntil: "networkidle" });

  await page.evaluate(() => {
    state.discoveryView = "table";
    state.discoveryPreferences = { filters: {}, sort: { field: "application_priority_score", direction: "desc" } };
    state.discoveryResults = [{
      id: 9101, source: "indeed", source_job_id: "runtime-1", title: "Software Developer",
      company: "Runtime Fixture", location: "Toronto, ON", url: "https://example.test/runtime-1",
      application_url: "https://example.test/runtime-1/apply", discovery_result_category: "actionable",
      discovery_match_status: "verified", result_stage: "qualified", discovery_profile_independent: 1,
    }];
    state.discoveryAllResults = state.discoveryResults.slice();
    state.discoveryMeta = {
      total: 1,
      diagnostics: {},
      search_progress: { requested_target: 10, qualifying_matches: 1, verified_matches: 1, provisional_matches: 0, review_required: 0, raw_inspected: 1 },
    };
    renderDiscoveryResults(state.discoveryMeta);
  });
  const rendered = await page.locator("#discovery-results").innerText();
  assert.match(rendered, /New Opportunities/);
  assert.match(rendered, /Verified new matches/);
  assert.doesNotMatch(rendered, /undefined/);

  const calls = [];
  await page.route("**/api/discovery/inbox/**", async (route) => {
    calls.push(new URL(route.request().url()).pathname);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: 9101, status: "Saved", date_applied: "2026-11-15" }) });
  });
  await page.route("**/api/discovery/inbox*", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  for (const action of ["saveDiscoveryJob", "applyDiscoveryJob", "skipDiscoveryJob"]) {
    await page.evaluate(async (name) => {
      state.discoveryResults = [{ id: 9101, source: "indeed", source_job_id: "runtime-1", title: "Software Developer", company: "Runtime Fixture", result_stage: "qualified" }];
      state.discoveryAllResults = state.discoveryResults.slice();
      await window[name]("indeed|runtime-1");
    }, action);
  }
  assert.deepStrictEqual(calls.map((path) => path.split("/").at(-1)), ["save", "applied", "ignore"]);

  // Best Match preserves junior-first eligibility tiers even when an
  // intermediate role has a higher numeric score.
  await page.evaluate(() => {
    state.discoveryView = "cards";
    state.discoveryPreferences = { filters: {}, sort: { field: "application_priority_score", direction: "desc" } };
    state.discoveryResults = [
      { id: 9201, title: "Intermediate Developer", company: "High Score", application_priority_score: 98, qualification_fit_seniority: { detected_level: "intermediate" }, discovery_result_category: "actionable" },
      { id: 9202, title: "Junior Developer", company: "Junior First", application_priority_score: 42, qualification_fit_seniority: { detected_level: "junior" }, discovery_result_category: "actionable" },
    ];
    state.discoveryAllResults = state.discoveryResults.slice();
    renderDiscoveryResults({ total: 2, source_counts: {}, diagnostics: {} });
  });
  const bestMatchTitles = await page.locator("#discovery-results .discovery-card h3").allTextContents();
  assert.deepStrictEqual(bestMatchTitles.slice(0, 2), ["Junior Developer", "Intermediate Developer"]);

  let pollCount = 0;
  await page.route("**/api/discovery/searches/runtime-ui*", async (route) => {
    pollCount += 1;
    const completed = pollCount > 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        search_id: "runtime-ui", status: completed ? "completed" : "running",
        jobs: [{ id: completed ? 9103 : 9102, source: "indeed", source_job_id: `poll-${pollCount}`, title: "Polled Developer", company: "Poll Fixture", result_stage: "qualified", discovery_result_category: "actionable" }],
        next_sequence: pollCount, progress: { requested_target: 2, qualifying_matches: pollCount, raw_inspected: pollCount },
      }),
    });
  });
  await page.evaluate(() => {
    state.discoveryActiveSearchId = "runtime-ui";
    state.discoveryResults = [];
    state.discoveryAllResults = [];
    state.discoveryMeta = {};
  });
  await page.evaluate(() => pollProgressiveDiscoverySearch("runtime-ui", 0));
  assert.strictEqual(pollCount, 2);
  assert.strictEqual(await page.locator("#discovery-results").getByText("New Opportunities").count(), 1);
  assert.deepStrictEqual(pageErrors, []);
  await browser.close();
  console.log("discovery UI runtime regression passed");
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
