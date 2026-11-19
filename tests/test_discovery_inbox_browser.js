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
  page.on("pageerror", (error) => console.error("browser pageerror:", error.stack || error));
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
    if (url.searchParams.get("q") === "zero") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
      return;
    }
    const category = url.searchParams.get("category") || "all_discovered";
    const count = category === "ready_to_apply" ? 51 : scoped ? 44 : 45;
    const rows = Array.from({ length: count }, (_, index) => ({
      id: index + 1,
      title: scoped ? category === "excluded" ? `Excluded ${index + 1}` : `Review ${index + 1}` : index === 0 ? "Bluestar durable history" : index === 1 ? "Sun Life durable history" : `History ${index + 1}`,
      company: "Browser Fixture",
      location: "Toronto, ON",
      url: `https://example.test/${index + 1}`,
      discovery_result_category: category === "ready_to_apply" ? "actionable" : scoped ? category === "excluded" ? "excluded" : "review_required" : index === 44 ? "actionable" : "review_required",
      discovery_inbox_category: category === "ready_to_apply" ? "ready_to_apply" : scoped ? category === "excluded" ? "excluded" : "review_required" : index === 44 ? "new_actionable" : "review_required",
      discovery_result_reason: "Evidence incomplete",
      search_membership_evidence: scoped ? { rule: category === "excluded" ? "location evidence missing" : "qualification evidence incomplete", source_excerpt: "Original posting evidence retained for this search run." } : {},
    }));
    const page = Number(url.searchParams.get("page") || 0);
    await route.fulfill({ status: 200, contentType: "application/json", headers: { "X-Job-Tracker-Total": String(count), "X-Job-Tracker-Page": String(page), "X-Job-Tracker-Page-Size": "50" }, body: JSON.stringify(rows.slice(page * 50, page * 50 + 50)) });
  });
  // The application keeps status polling requests open while a discovery
  // worker is available; DOM readiness is the meaningful startup boundary.
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.locator("#discovery-inbox").waitFor({ state: "attached" });
  // Let the normal application bootstrap finish before installing the
  // deterministic fixture; otherwise its late profile refresh can replace
  // the run selector while the interaction is being exercised.
  await page.waitForTimeout(750);
  await page.getByRole("button", { name: "Jobs Inbox" }).click();
  await page.locator(".discovery-view-inbox").waitFor({ state: "visible" });
  await page.getByRole("button", { name: "Find jobs", exact: true }).click();
  await page.getByRole("button", { name: "Jobs Inbox" }).click();
  await page.locator(".discovery-view-inbox").waitFor({ state: "visible" });
  await page.evaluate(async () => {
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
  await page.locator("[data-inbox-search-run]").waitFor({ state: "visible" });

  const reviewRequestPromise = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return url.pathname.endsWith("/api/discovery/inbox") && url.searchParams.get("search_id") === "e968ffcafb0f4524be269e517a6709a1" && url.searchParams.get("category") === "review_required";
  });
  await page.locator("[data-inbox-search-run]").selectOption("e968ffcafb0f4524be269e517a6709a1");
  const reviewRequest = await reviewRequestPromise;
  assert.strictEqual(new URL(reviewRequest.url()).searchParams.get("category"), "review_required");
  await page.locator('[data-inbox-clear-search]').waitFor({ state: "visible" });
  assert.strictEqual(await page.locator("#discovery-inbox article").count(), 44);
  const scoped = requests.find((url) => url.searchParams.has("search_id"));
  assert.ok(scoped, "scoped request was sent");
  assert.strictEqual(scoped.searchParams.get("category"), "review_required");

  const [excludedRequest] = await Promise.all([
    page.waitForRequest((request) => {
      const url = new URL(request.url());
      return url.pathname.endsWith("/api/discovery/inbox") && url.searchParams.get("search_id") === "e968ffcafb0f4524be269e517a6709a1" && url.searchParams.get("category") === "excluded";
    }),
    page.getByRole("button", { name: /Excluded Jobs/ }).click(),
  ]);
  assert.strictEqual(await page.evaluate(() => state.discoveryInboxSearchId), "e968ffcafb0f4524be269e517a6709a1");
  assert.strictEqual(new URL(excludedRequest.url()).searchParams.get("category"), "excluded");
  await page.waitForFunction(() => document.querySelectorAll("#discovery-inbox article").length === 44);
  const excluded = requests.filter((url) => url.searchParams.get("category") === "excluded").at(-1);
  assert.ok(excluded, "scoped excluded request was sent");
  assert.strictEqual(excluded.searchParams.get("search_id"), "e968ffcafb0f4524be269e517a6709a1");
  await page.locator("#discovery-inbox article details").first().click();
  assert.match(await page.locator("#discovery-inbox").innerText(), /location evidence missing/);

  await page.getByRole("button", { name: "Return to full Inbox" }).click();
  await page.waitForFunction(() => document.querySelectorAll("#discovery-inbox article").length === 45);
  const unscoped = requests.filter((url) => url.pathname.endsWith("/inbox")).at(-1);
  assert.ok(unscoped, "unscoped request was sent");
  assert.strictEqual(unscoped.searchParams.has("search_id"), false);
  assert.strictEqual(await page.locator('[data-inbox-clear-search]').count(), 0);
  assert.match(await page.locator("#discovery-inbox").innerText(), /Bluestar durable history/);
  assert.match(await page.locator("#discovery-inbox").innerText(), /Sun Life durable history/);
  await page.getByRole("button", { name: "History" }).click();
  const zeroRequest = page.waitForRequest((request) => new URL(request.url()).searchParams.get("q") === "zero");
  await page.locator("[data-inbox-history-search]").fill("zero");
  await zeroRequest;
  await page.waitForFunction(() => /No all discovered discovery records/.test(document.querySelector("#discovery-inbox").innerText));
  assert.match(await page.locator("#discovery-inbox").innerText(), /No all discovered discovery records/);
  await page.evaluate(() => { state.discoveryInboxQuery = ""; });
  await page.getByRole("button", { name: /Ready to Apply/ }).click();
  await page.waitForFunction(() => document.querySelectorAll("#discovery-inbox article").length === 50);
  await page.getByRole("button", { name: "Next" }).first().click();
  await page.waitForFunction(() => document.querySelectorAll("#discovery-inbox article").length === 1);
  assert.match(await page.locator("#discovery-inbox").innerText(), /Page 2 of 2 · 51 results/);
  await browser.close();
  console.log("discovery Inbox browser click regression passed");
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
