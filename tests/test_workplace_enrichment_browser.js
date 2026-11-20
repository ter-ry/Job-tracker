#!/usr/bin/env node

// Real Chromium interaction test. Run with the app in disposable Fresh QA:
// JOB_TRACKER_URL=http://127.0.0.1:5002 node tests/test_workplace_enrichment_browser.js
const assert = require("node:assert");
const { chromium } = require("playwright");

const baseUrl = process.env.JOB_TRACKER_URL || "http://127.0.0.1:5002";

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || "/usr/bin/chromium", args: ["--no-sandbox"] });
  const page = await browser.newPage();
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.evaluate(() => {
    window.confirm = () => false;
    state.selectedCandidateProfileId = "17";
    state.discoveryResults = [{ id: 101, discovery_result_category: "actionable" }];
    state.discoveryLastSearchId = "b".repeat(32);
  });
  const button = page.locator("#discovery-enrich-workplaces");
  assert.strictEqual(await button.isVisible(), true, "Find workplace must be visible in Find Jobs");
  let requested = false;
  await page.route("**/api/jobs/enrich-workplace-locations", async (route) => {
    requested = true;
    const requestBody = JSON.parse(route.request().postData() || "{}");
    assert.strictEqual(requestBody.search_id, "b".repeat(32));
    assert.deepStrictEqual(requestBody.job_ids, [101]);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ preview: true, gained_candidate: 1, records: [{ id: 101, company: "Centre", title: "RECE", status: "candidate_address", url: "https://example.com/job/101", alternatives: [{ address: "1200 Bayview Avenue, Toronto, ON M4G 1Z8", evidence: "Our Centre: 1200 Bayview Avenue" }] }], before_counts: { total: 28 }, cohort_total: 28 }) });
  });
  await button.click();
  await page.waitForTimeout(100);
  assert.strictEqual(requested, true, "Clicking the visible control must request enrichment");
  assert.match(await page.locator("#workplace-enrichment-preview").innerText(), /1200 Bayview Avenue/);
  await browser.close();
})().catch((error) => { console.error(error); process.exitCode = 1; });
