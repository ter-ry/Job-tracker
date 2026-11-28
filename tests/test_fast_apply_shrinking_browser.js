#!/usr/bin/env node

const assert = require("node:assert");
const { chromium } = require("playwright");

const baseUrl = process.env.JOB_TRACKER_URL || "http://127.0.0.1:5030";

async function main() {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || "/usr/bin/chromium", args: ["--no-sandbox"] });
  const page = await browser.newPage();
  const remaining = new Set(Array.from({ length: 36 }, (_, index) => index + 1));
  await page.route("**/api/candidate-profiles", async (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([
        { id: 101, name: "SWE applicant", workflow: "software" },
        { id: 102, name: "ECE applicant", workflow: "ece" },
      ]) });
    }
    return route.continue();
  });
  await page.route("**/api/discovery/inbox**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "POST") {
      const id = Number(url.pathname.split("/").slice(-2, -1)[0]);
      remaining.delete(id);
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
    }
    if (url.pathname.endsWith("/counts")) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ready_to_apply: remaining.size }) });
    if (url.searchParams.get("category") !== "ready_to_apply") return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
    const profileId = url.searchParams.get("candidate_profile_id");
    const rows = profileId === "101" ? [...remaining].slice(0, 10).map((id) => ({
      id, title: `Dynamic vacancy ${id}`, company: "Shrinking Queue Co", location: "Toronto, ON", url: `https://example.test/${id}`,
      discovery_result_category: "actionable", discovery_inbox_category: "ready_to_apply", application_priority_score: 100 - id,
    })) : [];
    return route.fulfill({ status: 200, contentType: "application/json", headers: { "X-Job-Tracker-Total": String(profileId === "101" ? remaining.size : 0), "X-Job-Tracker-Page": "0", "X-Job-Tracker-Page-Size": "10" }, body: JSON.stringify(rows) });
  });
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.locator("#global-applicant-selector option").nth(1).waitFor({ state: "attached" });
  await page.locator("#global-applicant-selector").selectOption("101");
  await page.getByRole("button", { name: "Fast Apply", exact: true }).click();
  await page.waitForFunction(() => state.fastApplyInitialTotal === 36 && state.fastApplyQueue.length === 10);

  const seen = [];
  for (let index = 0; index < 35; index += 1) {
    const id = await page.evaluate(() => Number(state.fastApplyQueue[state.fastApplyIndex]?.id));
    assert.strictEqual(id, index + 1, `expected ranked vacancy ${index + 1}, got ${id}`);
    assert.ok(!seen.includes(id), `vacancy ${id} repeated`);
    seen.push(id);
    await page.locator('[data-fast-action="save"]').click();
    await page.waitForFunction((expected) => state.fastApplyProcessedCount === expected && state.fastApplyPendingAction === false, index + 1);
  }
  assert.deepStrictEqual(seen, Array.from({ length: 35 }, (_, index) => index + 1));
  assert.strictEqual(await page.evaluate(() => Number(state.fastApplyQueue[state.fastApplyIndex]?.id)), 36);

  await page.locator("#global-applicant-selector").selectOption("102");
  await page.waitForFunction(() => state.fastApplyApplicantId === "102" && state.fastApplyQueue.length === 0);
  await page.locator("#global-applicant-selector").selectOption("101");
  await page.waitForFunction(() => state.fastApplyApplicantId === "101" && Number(state.fastApplyQueue[state.fastApplyIndex]?.id) === 36);
  await browser.close();
  console.log("Fast Apply shrinking-queue browser regression passed");
}

main().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
