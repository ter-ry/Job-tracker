#!/usr/bin/env node

const assert = require("node:assert");
const { chromium } = require("playwright");

const baseUrl = process.env.JOB_TRACKER_URL || "http://127.0.0.1:5000";

async function main() {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || "/usr/bin/chromium", args: ["--no-sandbox"] });
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/discovery/inbox**", (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/counts")) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ready_to_apply: 51, new_actionable: 51, saved: 1, skipped: 1, all_discovered: 52 }) });
    return route.fulfill({ status: 200, contentType: "application/json", headers: { "X-Job-Tracker-Total": "51", "X-Job-Tracker-Page-Size": "50" }, body: JSON.stringify(Array.from({ length: 51 }, (_, index) => ({ id: index + 1, title: `Inbox role ${index + 1}`, company: "Browser Fixture", location: "Toronto, ON", discovery_inbox_category: "ready_to_apply", discovery_result_category: "actionable" }))) });
  });
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "Job Inbox", exact: true }).click();
  await page.locator("#discovery-inbox").waitFor({ state: "visible" });
  const labels = await page.locator("#discovery-inbox-filters").innerText();
  for (const label of ["Ready to Apply", "New", "Saved", "Applied", "Skipped", "All Discovered"]) assert.match(labels, new RegExp(label));
  assert.strictEqual(await page.locator("#discovery-form").isVisible(), false);
  assert.ok(await page.locator("#discovery-inbox article").count() > 0);
  assert.deepStrictEqual(errors, [], errors.join("\n"));
  await browser.close();
  console.log("discovery Inbox browser click regression passed");
}

main().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
