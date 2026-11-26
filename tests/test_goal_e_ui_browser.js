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
  await page.route("**/api/candidate-profiles", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([{ id: 1, name: "SWE Fixture", workflow: "software" }, { id: 2, name: "ECE Fixture", workflow: "ece" }]) }));
  await page.route("**/api/discovery/inbox*", (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/counts")) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ready_to_apply: 2, new_actionable: 2 }) });
    if (url.pathname.endsWith("/search-runs")) return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
    return route.fulfill({ status: 200, contentType: "application/json", headers: { "X-Job-Tracker-Total": "2", "X-Job-Tracker-Page-Size": "50" }, body: JSON.stringify([{ id: 1, title: "Software Developer", company: "Fixture Labs", discovery_inbox_category: "ready_to_apply", discovery_result_category: "actionable" }, { id: 2, title: "RECE Educator", company: "Lakeview Centre", discovery_inbox_category: "saved", discovery_result_category: "actionable" }]) });
  });
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(500);
  assert.deepStrictEqual(await page.getByRole("button", { name: "Discover", exact: true }).count(), 1);
  await page.getByRole("button", { name: "Job Inbox", exact: true }).click();
  assert.strictEqual(await page.locator("#workspace-title").innerText(), "Job Inbox");
  await page.locator("#discovery-inbox").waitFor({ state: "visible" });
  await page.getByRole("button", { name: "Settings / Profiles", exact: true }).click();
  await page.getByRole("button", { name: "Light mode", exact: true }).click();
  assert.strictEqual(await page.evaluate(() => document.body.classList.contains("theme-light")), true);
  await page.getByRole("button", { name: "Discover", exact: true }).click();
  await page.locator("#global-applicant-selector").selectOption("2");
  await page.waitForFunction(() => state.selectedCandidateProfileId === "2");
  assert.match(await page.locator("#global-workflow-badge").innerText(), /ECE/);
  await page.screenshot({ path: `${outputDir}/goal-e-shell.png`, fullPage: true });
  assert.deepStrictEqual(errors, [], errors.join("\n"));
  await browser.close();
  console.log("Goal E UI browser regression passed");
}

main().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
