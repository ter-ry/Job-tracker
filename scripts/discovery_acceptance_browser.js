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
  page.on("pageerror", (error) => console.error(`browser pageerror: ${error.stack || error}`));
  const profile = await jsonRequest(page.request, "/api/candidate-profiles", {
    method: "POST",
    headers: { "content-type": "application/json" },
    data: { name: "SWE résumé", description: "Python, Flask, SQL, REST APIs, JavaScript and cloud fundamentals." },
  });
  if (process.env.ACCEPTANCE_RESUME_DOCX_PATH) {
    const upload = await page.request.post(`${baseUrl}/api/candidate-profiles/${profile.id}/resumes/upload`, { multipart: { file: { name: "synthetic-resume.docx", mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", buffer: fs.readFileSync(process.env.ACCEPTANCE_RESUME_DOCX_PATH) }, name: "SWE base résumé", is_default: "true" } });
    if (!upload.ok()) throw new Error(`POST resume upload: HTTP ${upload.status()} ${await upload.text()}`);
  } else {
    await jsonRequest(page.request, `/api/candidate-profiles/${profile.id}/resumes`, {
      method: "POST", headers: { "content-type": "application/json" },
      data: { name: "SWE base résumé", content: "Built Python and Flask REST APIs with SQL. Automated testing and cloud fundamentals.", is_default: true },
    });
  }
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
    body.jobs = body.jobs.map((job, index) => ({ ...job, id: seeded[index].id, result_stage: "qualified", already_saved: false, saved_job_status: "" }));
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.route("**/api/discovery/searches", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    await route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({ search_id: "fixture-browser", status: "running" }) });
  });
  await page.route("**/api/discovery/searches/*", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const body = JSON.parse(JSON.stringify(fixture));
    body.jobs = body.jobs.map((job, index) => ({ ...job, id: seeded[index].id, result_stage: "qualified", already_saved: false, saved_job_status: "" }));
    body.search_id = "fixture-browser";
    body.status = "completed";
    body.next_sequence = 1;
    body.progress = { requested_target: body.total || body.jobs.length, qualifying_matches: body.jobs.length, raw_inspected: body.jobs.length };
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

  const scoreDetails = page.locator("#discovery-results details.score-details summary").filter({ hasText: "Why this score?" });
  if (await scoreDetails.count()) await scoreDetails.first().click();
  const searchText = `${await page.locator("#discovery-results").innerText()} ${await page.locator("#discovery-results").innerHTML()}`;
  for (const expected of ["canada", "score", "toronto, on"]) {
    if (!searchText.toLowerCase().includes(expected)) throw new Error(`Search evidence missing: ${expected}`);
  }

  const saveAction = page.locator('[data-discovery-action="save"]').first();
  const action = async (name, suffix) => {
    const button = page.locator(`[data-discovery-action="${name}"]`).first();
    await button.waitFor({ state: "visible", timeout: 5000 });
    const key = await button.getAttribute("data-job-key");
    console.log(`browser action ${name} key=${key} html=${(await button.evaluate((node) => node.outerHTML)).slice(0, 300)}`);
    console.log(`browser state=${JSON.stringify(await page.evaluate((value) => ({ found: state.discoveryResults.some((item) => discoveryJobKey(item) === String(value)), fn: typeof saveDiscoveryJob, ids: state.discoveryResults.map((item) => ({ id: item.id, source: item.source_job_id })) } ), key))}`);
    const requestPromise = page.waitForRequest((request) => request.method() === "POST" && request.url().includes("/api/discovery/inbox/") && request.url().endsWith(suffix), { timeout: 5000 });
    await page.evaluate((value) => {
      const node = document.querySelector(`[data-discovery-action="${value.name}"][data-job-key="${CSS.escape(value.key)}"]`);
      if (!node) throw new Error(`Action button disappeared: ${value.name}/${value.key}`);
      node.click();
    }, { name, key });
    await requestPromise;
    await page.waitForTimeout(100);
    return key;
  };
  await action("save", "/save");
  await action("applied", "/applied");
  await action("skip", "/ignore");
  await page.screenshot({ path: path.join(artifactDir, "02-applied-skipped.png"), fullPage: true });

  await page.reload({ waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Find Jobs" }).click();
  // Candidate selection is intentionally not persisted in browser state.
  // Re-select the owner before replaying applicant-scoped Inbox history.
  await page.locator("#discovery-profile").selectOption(String(profile.id));
  await page.evaluate(async () => { setDiscoverySection("inbox"); await loadDiscoveryInbox(true); });
  console.log(`inbox filters after restart: ${await page.locator("#discovery-inbox-filters").innerText()}`);
  console.log(`inbox body after restart: ${(await page.locator("#discovery-inbox").innerText()).slice(0, 500)}`);
  const appliedCount = await page.locator('[data-inbox-category="applied"]').innerText();
  const skippedCount = await page.locator('[data-inbox-category="skipped"]').innerText();
  const savedCount = await page.locator('[data-inbox-category="saved"]').innerText();
  if (!/1/.test(appliedCount) || !/1/.test(skippedCount) || !/1/.test(savedCount)) throw new Error(`History counts wrong: ${appliedCount}; ${skippedCount}; ${savedCount}`);

  const inbox = await page.evaluate(async (profileId) => ({
    current: await fetch(`/api/discovery/inbox?candidate_profile_id=${encodeURIComponent(profileId)}`).then((response) => response.json()),
    history: await fetch(`/api/discovery/inbox?candidate_profile_id=${encodeURIComponent(profileId)}&include_history=1`).then((response) => response.json()),
  }), profile.id);
  const processedInNew = inbox.current.filter((item) => ["saved", "applied", "skipped"].includes(item.discovery_inbox_category));
  if (processedInNew.length) throw new Error(`Processed records returned to New inbox: ${JSON.stringify(processedInNew.map((item) => item.id))}`);
  const categories = Object.fromEntries(inbox.history.map((item) => [item.id, item.discovery_inbox_category]));
  if (categories[seeded[0].id] !== "saved" || categories[seeded[1].id] !== "applied" || categories[seeded[2].id] !== "skipped") throw new Error(`Unexpected categories: ${JSON.stringify(categories)}`);

  const otherProfile = await jsonRequest(page.request, "/api/candidate-profiles", {
    method: "POST", headers: { "content-type": "application/json" },
    data: { name: "Other applicant", identity_mode: "distinct", applicant_name: "Other Candidate" },
  });
  if (process.env.ACCEPTANCE_RESUME_DOCX_PATH) {
    const upload = await page.request.post(`${baseUrl}/api/candidate-profiles/${otherProfile.id}/resumes/upload`, { multipart: { file: { name: "other-resume.docx", mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", buffer: fs.readFileSync(process.env.ACCEPTANCE_RESUME_DOCX_PATH) }, name: "Other synthetic résumé", is_default: "true" } });
    if (!upload.ok()) throw new Error(`POST other resume upload: HTTP ${upload.status()} ${await upload.text()}`);
  } else {
    await jsonRequest(page.request, `/api/candidate-profiles/${otherProfile.id}/resumes`, { method: "POST", headers: { "content-type": "application/json" }, data: { name: "Other synthetic résumé", content: "Python and SQL", is_default: true } });
  }
  const otherHistory = await jsonRequest(page.request, `/api/discovery/inbox?candidate_profile_id=${otherProfile.id}&include_history=1`);
  const leakedState = otherHistory.filter((item) => ["saved", "applied", "skipped"].includes(item.discovery_inbox_category));
  if (leakedState.length) throw new Error(`Applicant state leaked to another profile: ${JSON.stringify(leakedState.map((item) => item.title))}`);

  fs.writeFileSync(path.join(artifactDir, "browser-log.json"), JSON.stringify({ profileId: profile.id, otherProfileId: otherProfile.id, seededJobIds: seeded.map((job) => job.id), categories, appliedCount, skippedCount, savedCount }, null, 2));
  await browser.close();
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
