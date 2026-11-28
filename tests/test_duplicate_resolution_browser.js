#!/usr/bin/env node

const assert = require("node:assert");
const { chromium } = require("playwright");

const baseUrl = process.env.JOB_TRACKER_URL || "http://127.0.0.1:5000";

async function main() {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || "/usr/bin/chromium", args: ["--no-sandbox"] });
  const page = await browser.newPage();
  page.on("pageerror", (error) => console.error("pageerror:", error.stack || error));
  const requests = [];
  await page.route("**/api/applications/duplicate-matches*", async (route) => {
    const method = route.request().method();
    requests.push({ method, url: route.request().url(), body: method === "POST" ? route.request().postDataJSON() : undefined });
    if (method === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([{ id: 41, application_date: "2026-02-03", imported: { company: "Imported Co", title: "Backend Developer", url: "https://example.test/imported" }, existing: { company: "Existing Co", title: "Backend Developer", url: "https://example.test/original" } }]) });
    } else {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
    }
  });
  await page.goto(baseUrl, { waitUntil: "commit", timeout: 10000 });
  await page.waitForTimeout(500);
  assert.strictEqual(await page.evaluate(() => typeof window.loadHistoricalDuplicateMatches), "function");
  await page.evaluate(async () => {
    state.selectedCandidateProfileId = "7";
    await loadHistoricalDuplicateMatches();
  });
  assert.match(await page.locator("#historical-duplicate-matches").innerText(), /Imported Co/);
  await page.locator('.tab[data-tab="tracker"]').click();
  await page.locator("#historical-application-panel").evaluate((element) => { element.open = true; });
  const postPromise = page.waitForRequest((request) => request.method() === "POST" && request.url().includes("/api/applications/duplicate-matches/41/resolve"));
  await page.locator('[data-duplicate-resolution="same_vacancy"]').click();
  const post = await postPromise;
  assert.strictEqual(post.postDataJSON().resolution, "same_vacancy");
  assert.strictEqual(post.postDataJSON().candidate_profile_id, "7");
  await browser.close();
}

main().then(() => console.log("duplicate resolution browser regression passed")).catch((error) => { console.error(error); process.exitCode = 1; });
