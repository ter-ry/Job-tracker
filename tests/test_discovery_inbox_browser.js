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
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([{ search_id: "e968ffcafb0f4524be269e517a6709a1", review_count: 44, excluded_count: 44 }]) });
      return;
    }
    const scoped = url.searchParams.has("search_id");
    const count = scoped ? 44 : 45;
    const category = url.searchParams.get("category") || "all_discovered";
    const rows = Array.from({ length: count }, (_, index) => ({
      id: index + 1,
      title: scoped ? category === "excluded" ? `Excluded ${index + 1}` : `Review ${index + 1}` : index === 0 ? "Bluestar durable history" : index === 1 ? "Sun Life durable history" : `History ${index + 1}`,
      company: "Browser Fixture",
      location: "Toronto, ON",
      url: `https://example.test/${index + 1}`,
      discovery_result_category: scoped ? category === "excluded" ? "excluded" : "review_required" : index === 44 ? "actionable" : "review_required",
      discovery_inbox_category: scoped ? category === "excluded" ? "excluded" : "review_required" : index === 44 ? "new_actionable" : "review_required",
      discovery_result_reason: "Evidence incomplete",
    }));
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(rows) });
  });
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.evaluate(async () => {
    setDiscoverySection("saved");
    state.selectedCandidateProfileId = "7";
    state.discoveryLastSearchId = "e968ffcafb0f4524be269e517a6709a1";
    state.discoveryResults = [];
    state.discoveryAllResults = [];
    state.discoveryInboxCategory = "all_discovered";
    state.discoveryInboxSearchId = "";
    state.discoveryInboxRuns = [{ search_id: "e968ffcafb0f4524be269e517a6709a1", review_count: 44, excluded_count: 44 }];
    renderDiscoveryInbox([]);
    renderDiscoveryResults({ total: 0, source_counts: {}, diagnostics: {}, search_progress: { review_required: 44 } });
  });

  await page.locator("[data-inbox-search-run]").selectOption("e968ffcafb0f4524be269e517a6709a1");
  // Keep the click/select assertion independent of any initial page-load
  // race, then exercise the same loader with the selected run.
  await page.evaluate(async () => {
    state.discoveryInboxSearchId = document.querySelector("[data-inbox-search-run]").value;
    state.discoveryInboxCategory = "review_required";
    await loadDiscoveryInbox(true);
  });
  await page.locator('[data-inbox-clear-search]').waitFor({ state: "visible" });
  assert.strictEqual(await page.locator("#discovery-inbox article").count(), 44);
  const scoped = requests.find((url) => url.searchParams.has("search_id"));
  assert.ok(scoped, "scoped request was sent");
  assert.strictEqual(scoped.searchParams.get("category"), "review_required");

  await page.getByRole("button", { name: /Excluded Jobs/ }).click();
  assert.strictEqual(await page.evaluate(() => state.discoveryInboxSearchId), "e968ffcafb0f4524be269e517a6709a1");
  await page.evaluate(async () => {
    state.discoveryInboxCategory = "excluded";
    await loadDiscoveryInbox(true);
  });
  await page.waitForFunction(() => document.querySelectorAll("#discovery-inbox article").length === 44);
  const excluded = requests.filter((url) => url.searchParams.get("category") === "excluded").at(-1);
  assert.ok(excluded, "scoped excluded request was sent");
  assert.strictEqual(excluded.searchParams.get("search_id"), "e968ffcafb0f4524be269e517a6709a1");
  await page.locator("#discovery-inbox article details").first().click();
  assert.match(await page.locator("#discovery-inbox").innerText(), /Evidence incomplete/);

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
