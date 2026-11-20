#!/usr/bin/env node

// Real Chromium UI regression for the read-only Ontario registry preview.
// Run with: JOB_TRACKER_URL=http://127.0.0.1:5002 node tests/test_ontario_facilities_browser.js
const assert = require("node:assert");
const { chromium } = require("playwright");

const baseUrl = process.env.JOB_TRACKER_URL || "http://127.0.0.1:5002";

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || "/usr/bin/chromium", args: ["--no-sandbox"] });
  const page = await browser.newPage();
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.evaluate(() => { state.selectedCandidateProfileId = "17"; state.workplaceEnrichmentSearchId = "e".repeat(32); });
  await page.locator("#ontario-registry-preview-panel").locator("summary").click();
  await page.locator("#ontario-cohort-file").setInputFiles({ name: "ece_cohort_28_jobs.csv", mimeType: "text/csv", buffer: Buffer.from("job_id,employer,job_title,advertised_location\n337,Roden Community Child Care Centre,RECE,Toronto ON\n") });
  await page.locator("#ontario-registry-file").setInputFiles({ name: "child_care_facilities_open_data_oct_2026.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: Buffer.from("offline-fixture") });
  let requested = false;
  await page.route("**/api/jobs/enrich-workplace-registry", async (route) => {
    requested = true;
    const body = route.request().postData() || "";
    assert.match(body, /ece_cohort_28_jobs/);
    assert.match(body, /child_care_facilities_open_data_oct_2026/);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      preview: true, registry_snapshot_date: "2026-10-31", counts: { total: 28, new_unique_facility_matches: 8 },
      message: "Preview only. Every facility is a possible licensed facility — verify job workplace.",
      jobs: [{ job_id: "337", employer: "Roden Community Child Care Centre", job_title: "RECE", category: "strong_single_centre_match", confidence: "strong", candidates: [{ registered_facility_name: "Roden Community Child Care Centre", address: "151 Hiawatha Road, Toronto, ON", licence_status: "Active", matching_evidence: ["municipality matches Toronto"] }] }],
    }) });
  });
  await page.locator("#ontario-registry-preview").click();
  await page.waitForTimeout(100);
  assert.strictEqual(requested, true);
  assert.match(await page.locator("#ontario-registry-preview-output").innerText(), /Roden Community Child Care Centre/);
  assert.match(await page.locator("#ontario-registry-preview-output").innerText(), /verify job workplace/);
  await browser.close();
})().catch((error) => { console.error(error); process.exitCode = 1; });
