#!/usr/bin/env node

const assert = require("node:assert");
const { chromium } = require("playwright");

const baseUrl = process.env.JOB_TRACKER_URL || "http://127.0.0.1:5000";
const outputDir = process.env.UI_ACCEPTANCE_DIR || "artifacts/ui-acceptance";

async function main() {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || "/usr/bin/chromium", args: ["--no-sandbox"] });
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/candidate-profiles", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([
    { id: 1, name: "SWE Fixture", workflow: "software", commute_origin_input: "Toronto, ON" },
    { id: 2, name: "ECE Fixture", workflow: "ece", commute_origin_input: "Toronto, ON" },
  ]) }));
  await page.route("**/api/discovery/inbox**", (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/counts")) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ready_to_apply: 1, new_actionable: 1 }) });
    return route.fulfill({ status: 200, contentType: "application/json", headers: { "X-Job-Tracker-Total": "1", "X-Job-Tracker-Page-Size": "50" }, body: JSON.stringify([{ id: 1, title: "RECE Educator", company: "Fixture Centre", discovery_inbox_category: "ready_to_apply", discovery_result_category: "actionable", discovery_result_reason: "Persisted ECE reassessment: full-time educator retained.", discovery_employment_status: "Full-time", registration_requirements: [] }]) });
  });
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => state.candidateProfiles.length === 2);

  assert.strictEqual(await page.locator(".discovery-subnav").count(), 0);
  await page.getByRole("button", { name: "Discover", exact: true }).click();
  assert.strictEqual(await page.locator("#discovery-form").isVisible(), true);
  assert.strictEqual(await page.locator("#discovery-inbox").isVisible(), false);
  assert.strictEqual(await page.locator("#fast-apply-panel").isVisible(), false);
  assert.strictEqual(await page.locator("#discovery-enrich-workplaces").count(), 0);
  assert.strictEqual(await page.locator("#discovery-location").count(), 1);
  await page.screenshot({ path: `${outputDir}/owner-acceptance-discover-1280.png`, fullPage: true });

  await page.getByRole("button", { name: "Job Inbox", exact: true }).click();
  assert.strictEqual(await page.locator("#discovery-inbox").isVisible(), true);
  assert.strictEqual(await page.locator("#discovery-inbox-filters").innerText().then((text) => /Ready|New|Saved|Applied|Skipped|All/i.test(text)), true);
  assert.strictEqual(await page.locator("#discovery-form").isVisible(), false);

  await page.getByRole("button", { name: "Fast Apply", exact: true }).click();
  assert.strictEqual(await page.locator("#fast-apply-panel").isVisible(), true);
  assert.strictEqual(await page.locator("#discovery-form").isVisible(), false);
  assert.strictEqual(await page.locator("#discovery-inbox").isVisible(), false);

  await page.getByRole("button", { name: "Applications", exact: true }).click();
  assert.strictEqual(await page.locator("#tracker").isVisible(), true);
  assert.strictEqual(await page.locator("#discovery-form").isVisible(), false);
  await page.getByRole("button", { name: "Settings / Profiles", exact: true }).click();
  assert.strictEqual(await page.locator("#profile").isVisible(), true);
  assert.strictEqual(await page.locator("#candidate-profile-list").isVisible(), true);

  await page.locator("#global-applicant-selector").selectOption("2");
  await page.waitForFunction(() => state.selectedCandidateProfileId === "2" && state.discoveryWorkflow === "ece");
  assert.strictEqual(await page.locator("#discovery-workflow").inputValue(), "ece");
  assert.match(await page.locator("#discovery-keywords").inputValue(), /ECE|RECE/);
  assert.strictEqual(await page.locator("#discovery-search-area").count(), 0);
  assert.strictEqual(await page.locator("#discovery-enrich-workplaces").count(), 0);
  await page.getByRole("button", { name: "Discover", exact: true }).click();
  assert.strictEqual(await page.locator("#discovery-advanced-settings").isVisible(), false);
  await page.getByRole("button", { name: "Fast Apply", exact: true }).click();
  await page.waitForTimeout(100);
  assert.match(await page.locator("#fast-apply-current").innerText(), /Persisted ECE reassessment|No eligible/);
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.screenshot({ path: `${outputDir}/owner-acceptance-ece-1920.png`, fullPage: true });

  assert.deepStrictEqual(errors, [], errors.join("\n"));
  await browser.close();
  console.log("Owner acceptance UI browser regression passed (sanitized fixtures)");
}

main().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
