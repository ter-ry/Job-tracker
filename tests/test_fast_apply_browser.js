#!/usr/bin/env node

const assert = require("node:assert");
const { chromium } = require("playwright");

const baseUrl = process.env.JOB_TRACKER_URL || "http://127.0.0.1:5000";

async function main() {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || "/usr/bin/chromium", args: ["--no-sandbox"] });
  const page = await browser.newPage();
  const pageErrors = [];
  let counterRequests = 0;
  page.on("pageerror", (error) => pageErrors.push(error));
  await page.route("**/api/discovery/inbox**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const profile = url.searchParams.get("candidate_profile_id") || "";
    if (request.method() === "POST") {
      if (request.url().endsWith("/2/ignore")) return route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: "fixture action failed" }) });
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
    }
    if (request.method() !== "GET") return route.continue();
    if (url.pathname.endsWith("/counts")) { counterRequests += 1; return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ready_to_apply: 501 }) }); }
    if (url.pathname.endsWith("/search-runs")) return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
    if (url.searchParams.get("category") !== "ready_to_apply") return route.fulfill({ status: 200, contentType: "application/json", body: "[]", headers: { "X-Job-Tracker-Total": "0" } });
    const pageNumber = Number(url.searchParams.get("page") || 0);
    const requestedPageSize = Number(url.searchParams.get("page_size") || 500);
    const total = profile === "2" ? 1 : 501;
    if (profile === "2") await new Promise((resolve) => setTimeout(resolve, 180));
    const start = pageNumber * requestedPageSize;
    const rows = Array.from({ length: Math.max(0, Math.min(requestedPageSize, total - start)) }, (_, index) => ({
      id: start + index + 1,
      title: profile === "2" ? `ECE persisted role ${start + index + 1}` : `Persisted role ${start + index + 1}`,
      company: "Fast Apply Fixture",
      location: "Toronto, ON",
      url: `https://example.test/${start + index + 1}`,
      discovery_result_category: "actionable",
      discovery_inbox_category: "ready_to_apply",
      qualification_fit_seniority: { detected_level: "unknown" },
      experience_requirements: { required: { minimum: 1 } },
      application_priority_score: 70,
      experience_requirements: { required: { minimum: 0, maximum: 3 }, preferred: { minimum: 4, maximum: 5 } },
    }));
    return route.fulfill({ status: 200, contentType: "application/json", headers: { "X-Job-Tracker-Total": String(total), "X-Job-Tracker-Page": String(pageNumber), "X-Job-Tracker-Page-Size": "500" }, body: JSON.stringify(rows) });
  });
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.locator("#fast-apply-current").waitFor({ state: "attached" });
  await page.waitForTimeout(500);
  await page.evaluate(() => {
    state.candidateProfiles = [{ id: 1, workflow: "software", name: "Applicant One" }, { id: 2, workflow: "software", name: "Applicant Two" }];
    state.selectedCandidateProfileId = "1";
    openFastApply();
  });
  await page.waitForFunction(() => state.fastApplyQueue.length === 10 && state.fastApplyInitialTotal === 501);
  await page.waitForFunction(() => state.fastApplyPrefetchedQueue.length === 10);
  assert.match(await page.locator("#fast-apply-current").innerText(), /Persisted role 1/);
  await page.evaluate(() => { state.selectedCandidateProfileId = "2"; return loadFastApplyQueue(); });
  await page.waitForFunction(() => state.fastApplyApplicantId === "2" && state.fastApplyQueue.length === 1);
  assert.match(await page.locator("#fast-apply-current").innerText(), /ECE persisted role 1/);
  await page.evaluate(() => { state.selectedCandidateProfileId = "1"; return loadFastApplyQueue(); });
  await page.waitForFunction(() => state.fastApplyApplicantId === "1" && state.fastApplyQueue.length === 10 && state.fastApplyInitialTotal === 501);
  assert.match(await page.locator("#fast-apply-current").innerText(), /0–3 years/);
  assert.doesNotMatch(await page.locator("#fast-apply-current").innerText(), /profileId is not defined/);

  await page.evaluate(async () => {
    state.selectedCandidateProfileId = "2";
    const stale = loadFastApplyQueue();
    state.selectedCandidateProfileId = "1";
    const current = loadFastApplyQueue();
    await Promise.all([stale, current]);
  });
  await page.waitForFunction(() => state.fastApplyApplicantId === "1" && state.fastApplyQueue.length === 10 && state.fastApplyInitialTotal === 501);
  assert.strictEqual(await page.evaluate(() => state.fastApplyApplicantId), "1");

  await page.locator('[data-fast-action="save"]').click();
  await page.waitForFunction(() => state.fastApplyQueue.length === 9 && state.fastApplyPendingAction === false && /Persisted role 2/.test(document.querySelector("#fast-apply-current").innerText));
  assert.match(await page.locator("#fast-apply-current").innerText(), /Persisted role 2/);
  await page.getByRole("button", { name: "Skip" }).click();
  await page.waitForFunction(() => /fixture action failed/.test(document.querySelector("#fast-apply-current").innerText));
  assert.match(await page.locator("#fast-apply-current").innerText(), /Persisted role 2/);
  assert.strictEqual(await page.evaluate(() => state.fastApplyQueue.length), 9);
  assert.ok(counterRequests >= 1, "successful action refreshed authoritative counters");
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.locator("#fast-apply-current").waitFor({ state: "attached" });
  await page.evaluate(() => { state.candidateProfiles = [{ id: 1, workflow: "software", name: "Applicant One" }]; state.selectedCandidateProfileId = "1"; openFastApply(); });
  await page.waitForFunction(() => state.fastApplyQueue.length === 10 && state.fastApplyApplicantId === "1" && state.fastApplyInitialTotal === 501);
  assert.match(await page.locator("#fast-apply-current").innerText(), /Persisted role 1/);
  assert.strictEqual(pageErrors.length, 0, pageErrors.map((error) => error.message).join("\n"));
  await browser.close();
  console.log("Fast Apply persistent queue browser regression passed");
}

main().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
