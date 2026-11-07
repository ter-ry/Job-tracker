#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const baseUrl = process.env.JOB_TRACKER_URL || "http://127.0.0.1:5000";
const artifactDir = process.env.ACCEPTANCE_ARTIFACT_DIR || "/tmp/job-tracker-discovery-acceptance";
const fixturePath = path.join(__dirname, "..", "tests", "fixtures", "discovery_canada_acceptance.json");
const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf8"));

async function jsonRequest(request, url, options = {}) {
  const response = await request.fetch(`${baseUrl}${url}`, options);
  if (!response.ok()) throw new Error(`${options.method || "GET"} ${url}: HTTP ${response.status()} ${await response.text()}`);
  return response.json();
}

async function main() {
  fs.mkdirSync(artifactDir, { recursive: true });
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || "/usr/bin/chromium", args: ["--no-sandbox"] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1200 } });
  const page = await context.newPage();
  const profile = await jsonRequest(page.request, "/api/candidate-profiles", {
    method: "POST",
    headers: { "content-type": "application/json" },
    data: { name: "SWE résumé", description: "Python, Flask, SQL, REST APIs, JavaScript and cloud fundamentals." },
  });
  await jsonRequest(page.request, `/api/candidate-profiles/${profile.id}/resumes`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    data: { name: "SWE base résumé", content: "Built Python and Flask REST APIs with SQL. Automated testing and cloud fundamentals.", docx_path: process.env.ACCEPTANCE_RESUME_DOCX_PATH || "", is_default: true },
  });
  const seeded = [];
  for (const item of fixture.jobs) {
    seeded.push(await jsonRequest(page.request, "/api/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      data: {
        company: item.company,
        title: item.title,
        location: item.location,
        url: item.url,
        application_url: item.application_url,
        source: item.source,
        remote_type: item.remote_type,
        job_description: item.job_description,
        discovery_state: "new",
        discovery_first_seen_at: "2026-11-03T00:00:00",
        discovery_last_seen_at: "2026-11-03T00:00:00",
        discovery_remote_preference: "remote",
        remote_eligibility: item.remote_eligibility,
        remote_search_eligible: item.remote_search_eligible,
      },
    }));
  }

  await page.route("**/api/discovery/jobspy", async (route) => {
    const body = JSON.parse(JSON.stringify(fixture));
    body.jobs = body.jobs.map((job, index) => ({ ...job, id: seeded[index].id, already_saved: false, saved_job_status: "" }));
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Find jobs" }).click();
  await page.waitForFunction(() => [...document.querySelectorAll("#discovery-profile option")].some((option) => option.textContent.includes("SWE résumé")));
  await page.locator("#discovery-profile").selectOption(String(profile.id));
  await page.locator("#discovery-keywords").fill("software developer");
  await page.locator("#discovery-location").fill("Canada");
  await page.locator("#discovery-remote-preference").selectOption("remote");
  await page.evaluate(() => searchDiscovery({ preventDefault() {} }));
  await page.locator('[data-discovery-action="save"]').first().waitFor();
  await page.screenshot({ path: path.join(artifactDir, "01-canada-search.png"), fullPage: true });

  await page.locator("#discovery-results details.score-details summary").filter({ hasText: "Why this score?" }).first().click();
  const searchText = `${await page.locator("#discovery-results").innerText()} ${await page.locator("#discovery-results").innerHTML()}`;
  for (const expected of ["Canada", "Qualification Match", "Application Priority", "SWE résumé", "Toronto, ON"]) {
    if (!searchText.includes(expected)) throw new Error(`Search evidence missing: ${expected}`);
  }

  await page.locator('[data-discovery-action="save"]').first().click();
  await page.locator('[data-discovery-action="applied"]').first().click();
  await page.locator('[data-discovery-action="hide"]').first().click();
  await page.screenshot({ path: path.join(artifactDir, "02-applied-skipped.png"), fullPage: true });

  await page.reload({ waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Discovery" }).click();
  await page.getByRole("button", { name: "Saved searches" }).click();
  const appliedCount = await page.getByRole("button", { name: /Applied/ }).innerText();
  const skippedCount = await page.getByRole("button", { name: /Skipped/ }).innerText();
  const savedCount = await page.getByRole("button", { name: /Saved for later/ }).innerText();
  if (!/1/.test(appliedCount) || !/1/.test(skippedCount) || !/1/.test(savedCount)) throw new Error(`History counts wrong: ${appliedCount}; ${skippedCount}; ${savedCount}`);

  const inbox = await page.evaluate(async () => ({
    current: await fetch("/api/discovery/inbox").then((response) => response.json()),
    history: await fetch("/api/discovery/inbox?include_history=1").then((response) => response.json()),
  }));
  if (inbox.current.length !== 0) throw new Error(`Processed records returned to New inbox: ${inbox.current.length}`);
  const categories = Object.fromEntries(inbox.history.map((item) => [item.title, item.discovery_inbox_category]));
  if (categories["Junior Python Developer"] !== "saved" || categories["Backend Engineer"] !== "applied" || categories["Backend Engineer QA"] !== "skipped") throw new Error(`Unexpected categories: ${JSON.stringify(categories)}`);

  fs.writeFileSync(path.join(artifactDir, "browser-log.json"), JSON.stringify({ profileId: profile.id, seededJobIds: seeded.map((job) => job.id), categories, appliedCount, skippedCount, savedCount }, null, 2));
  await browser.close();
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
