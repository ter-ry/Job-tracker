#!/usr/bin/env node

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
  const requests = [];
  await page.route("**/api/discovery/inbox*", async (route) => {
    const url = new URL(route.request().url());
    requests.push(url);
    if (url.pathname.endsWith("/counts")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ all_discovered: 45, all_relevant: 44, new_actionable: 1, review_required: 44 }) });
      return;
    }
    if (url.pathname.endsWith("/search-runs")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([{ search_id: "e968ffcafb0f4524be269e517a6709a1", review_count: 44, excluded_count: 0 }]) });
      return;
    }
    const scoped = url.searchParams.has("search_id");
    const count = scoped ? 44 : 45;
    const rows = Array.from({ length: count }, (_, index) => ({
      id: index + 1,
      title: scoped ? `Review ${index + 1}` : index === 0 ? "Bluestar durable history" : index === 1 ? "Sun Life durable history" : `History ${index + 1}`,
      company: "Browser Fixture",
      location: "Toronto, ON",
      url: `https://example.test/${index + 1}`,
      discovery_result_category: scoped ? "review_required" : index === 44 ? "actionable" : "review_required",
      discovery_inbox_category: scoped ? "review_required" : index === 44 ? "new_actionable" : "review_required",
      discovery_result_reason: "Evidence incomplete",
    }));
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(rows) });
  });
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.evaluate(() => {
    state.selectedCandidateProfileId = "7";
    state.discoveryLastSearchId = "e968ffcafb0f4524be269e517a6709a1";
    state.discoveryResults = [];
    state.discoveryAllResults = [];
    renderDiscoveryResults({ total: 0, source_counts: {}, diagnostics: {}, search_progress: { review_required: 44 } });
  });

  await page.getByRole("button", { name: "Inspect 44 Needs Review jobs" }).click();
  await page.locator('[data-inbox-clear-search]').waitFor({ state: "visible" });
  assert.strictEqual(await page.locator("#discovery-inbox article").count(), 44);
  const scoped = requests.find((url) => url.searchParams.has("search_id"));
  assert.ok(scoped, "scoped request was sent");
  assert.strictEqual(scoped.searchParams.get("category"), "review_required");

  await page.getByRole("button", { name: "Return to full Inbox" }).click();
  await page.waitForFunction(() => document.querySelectorAll("#discovery-inbox article").length === 45);
  const unscoped = requests.filter((url) => url.pathname.endsWith("/inbox")).at(-1);
  assert.ok(unscoped, "unscoped request was sent");
  assert.strictEqual(unscoped.searchParams.has("search_id"), false);
  assert.strictEqual(await page.locator('[data-inbox-clear-search]').count(), 0);
  assert.match(await page.locator("#discovery-inbox").innerText(), /Bluestar durable history/);
  assert.match(await page.locator("#discovery-inbox").innerText(), /Sun Life durable history/);
  await browser.close();
  console.log("discovery Inbox browser click regression passed");
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
