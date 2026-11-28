#!/usr/bin/env node

const assert = require("node:assert");
const fs = require("fs");
const { chromium } = require("playwright");

const baseUrl = process.env.JOB_TRACKER_URL || "http://127.0.0.1:5030";
const screenshotDir = "/tmp/job-tracker-ui-screenshots";

async function main() {
  fs.mkdirSync(screenshotDir, { recursive: true });
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || "/usr/bin/chromium", args: ["--no-sandbox"] });
  const page = await browser.newPage();
  const startupRequests = [];
  const preferenceRequests = [];
  const preferenceWrites = [];
  let progressiveSearchPayload = null;
  page.on("request", (request) => {
    if (request.url().includes("/api/")) startupRequests.push(request.url());
  });
  await page.route("**/api/candidate-profiles", async (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([
    { id: 201, name: "SWE applicant", workflow: "software" },
    { id: 202, name: "ECE applicant", workflow: "ece" },
  ]) }));
  await page.route("**/api/discovery/preferences*", async (route) => {
    const url = new URL(route.request().url());
    if (route.request().method() === "POST") {
      preferenceWrites.push(JSON.parse(route.request().postData() || "{}"));
    }
    preferenceRequests.push({ profile: url.searchParams.get("candidate_profile_id"), workflow: url.searchParams.get("workflow") });
    const ece = url.searchParams.get("workflow") === "ece";
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ preferences: { search: { workflow: ece ? "ece" : "software", keywords: ece ? "Registered Early Childhood Educator; RECE" : "platform engineer", include_internships: !ece, match_policy: ece ? "strict_matching" : "apply_broadly", enabled_sources: ["indeed", "glassdoor", "employer_direct"] } } }) });
  });
  await page.route("**/api/discovery/searches", async (route) => {
    progressiveSearchPayload = JSON.parse(route.request().postData() || "{}");
    return route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({ accepted: true, search_id: 1 }) });
  });
  await page.route("**/api/discovery/inbox**", async (route) => route.fulfill({ status: 200, contentType: "application/json", headers: { "X-Job-Tracker-Total": "0" }, body: "[]" }));
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.locator("#global-applicant-selector option").nth(1).waitFor({ state: "attached" });
  assert.ok(!startupRequests.some((url) => /\/api\/jobs(?:\?|$)|\/documents(?:\?|$)|saved-search|scheduler|task-status/.test(url)), `startup hydrated unrelated data: ${startupRequests.join("\n")}`);
  await page.locator("#global-applicant-selector").selectOption("202");
  await page.waitForTimeout(100);
  await page.locator("#discovery-profile").selectOption("201");
  await page.waitForTimeout(100);
  const searchState = await page.evaluate(() => ({
    workflow: state.discoveryWorkflow,
    keywords: document.querySelector("#discovery-keywords")?.value || "",
    criteria: discoverySearchCriteriaFromControls(),
  }));
  assert.ok(preferenceRequests.some((request) => request.profile === "202" && request.workflow === "ece"));
  assert.ok(preferenceRequests.some((request) => request.profile === "201" && request.workflow === "software"));
  assert.strictEqual(searchState.workflow, "software");
  assert.strictEqual(searchState.keywords, "platform engineer");
  assert.strictEqual(searchState.criteria.match_policy, "apply_broadly");
  assert.strictEqual(searchState.criteria.include_internships, true);
  assert.ok(preferenceWrites.some((write) => String(write.candidate_profile_id) === "202" && write.preferences?.search?.keywords === "Registered Early Childhood Educator; RECE"));
  assert.ok(preferenceWrites.some((write) => String(write.candidate_profile_id) === "201" && write.preferences?.search?.keywords === "platform engineer"));
  assert.ok(!preferenceWrites.some((write) => write.preferences?.search?.keywords === "software developer; junior software engineer"));
  await page.evaluate(async () => fetch("/api/discovery/searches", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(discoverySearchCriteriaFromControls()),
  }));
  assert.strictEqual(progressiveSearchPayload.match_policy, "apply_broadly");
  assert.strictEqual(progressiveSearchPayload.include_internships, true);
  assert.deepStrictEqual(progressiveSearchPayload.enabled_sources, ["indeed", "glassdoor", "employer_direct"]);
  await page.locator("#global-applicant-selector").selectOption("202");
  await page.waitForTimeout(100);

  for (const viewport of [{ width: 1280, height: 720 }, { width: 1920, height: 1080 }]) {
    await page.setViewportSize(viewport);
    await page.getByRole("button", { name: "Applications", exact: true }).click();
    await page.waitForTimeout(250);
    const applications = await page.evaluate(() => ({
      dashboardVisible: document.querySelector("#tracker > .dashboard").getBoundingClientRect().height > 0,
      legacyWorkspaceVisible: document.querySelector("#tracker > .workspace").getBoundingClientRect().height > 0,
      historyVisible: document.querySelector("#jobs-table").getBoundingClientRect().height > 0,
      applicant: document.querySelector("#applications-selected-applicant")?.textContent || "",
    }));
    assert.strictEqual(applications.dashboardVisible, false);
    assert.strictEqual(applications.legacyWorkspaceVisible, false);
    assert.strictEqual(applications.historyVisible, true);
    assert.match(applications.applicant, /ECE applicant/);
    await page.screenshot({ path: `${screenshotDir}/applications-${viewport.width}x${viewport.height}.png` });

    await page.getByRole("button", { name: "Job Inbox", exact: true }).click();
    await page.waitForTimeout(500);
    await page.evaluate(() => {
      state.discoveryWorkflow = "ece";
      state.candidateProfiles = [{ id: 202, name: "ECE applicant", workflow: "ece" }];
      state.selectedCandidateProfileId = "202";
      state.discoveryInboxCategory = "ready_to_apply";
      state.discoveryInboxCounts = { ready_to_apply: 1 };
      state.discoveryInboxJobs = Array.from({ length: 3 }, (_, index) => ({
        id: 77 + index, title: `Registered ECE ${index + 1}`, company: "Inspire Montessori School", provider_company: "Inspire Montessori School",
        workflow: "ece", location: "Scarborough, ON", workplace_address: "55 Town Centre Crt, Scarborough, ON M1P 4X4",
        workplace_precision: "street address", employment_type: "permanent, full-time and part-time", salary: "$25/hour",
        discovery_result_category: "actionable", discovery_result_reason: "Stored ECE evidence", url: `https://example.test/${77 + index}`,
        discovery_inbox_category: "ready_to_apply",
      }));
      renderDiscoveryInbox(state.discoveryInboxJobs);
    });
    await page.locator(".inbox-row").first().waitFor({ state: "attached" });
    const inbox = await page.evaluate(() => {
      const row = document.querySelector(".inbox-row");
      const vacancy = row.querySelector(".inbox-vacancy");
      const actions = [...row.querySelectorAll(".row-actions .button")].map((button) => button.getBoundingClientRect());
      const checkbox = row.querySelector(".inbox-heading input[type=checkbox]").getBoundingClientRect();
      const heading = row.querySelector(".inbox-heading").getBoundingClientRect();
      return {
        columns: getComputedStyle(row).gridTemplateColumns,
        vacancyWidth: vacancy.getBoundingClientRect().width,
        rowWidth: row.getBoundingClientRect().width,
        text: row.innerText,
        actionCount: actions.length,
        actionXs: actions.map((item) => item.x),
        actionYs: actions.map((item) => item.y),
        checkboxBesideHeading: checkbox.y >= heading.y && checkbox.y < heading.bottom,
        rowHeight: row.getBoundingClientRect().height,
        rowCount: document.querySelectorAll(".inbox-row").length,
      };
    });
    assert.strictEqual(inbox.columns.split(" ").length, 1);
    assert.ok(inbox.vacancyWidth > inbox.rowWidth * 0.8);
    assert.strictEqual(inbox.rowCount, 3);
    assert.ok(inbox.rowHeight < 190);
    assert.strictEqual(inbox.actionXs.slice().sort((a, b) => a - b).join(","), inbox.actionXs.join(","));
    assert.ok(new Set(inbox.actionYs.map((value) => Math.round(value))).size <= 1);
    assert.strictEqual(inbox.checkboxBesideHeading, true);
    assert.match(inbox.text, /Inspire Montessori School/);
    assert.match(inbox.text, /55 Town Centre Crt/);
    assert.doesNotMatch(inbox.text, /Detected seniority|Technical compatibility|résumé/i);
    assert.ok(inbox.actionCount >= 2);
    const beforeEvidence = await page.evaluate(() => ({ height: document.querySelector(".inbox-row").getBoundingClientRect().height, scrollY: window.scrollY }));
    await page.locator(".inbox-row [data-inbox-evidence]").first().click();
    await page.locator("#inbox-evidence-dialog").waitFor({ state: "visible" });
    const afterEvidence = await page.evaluate(() => ({ height: document.querySelector(".inbox-row").getBoundingClientRect().height, scrollY: window.scrollY, bodyHeight: document.querySelector(".inbox-evidence-body").getBoundingClientRect().height, overflow: getComputedStyle(document.querySelector(".inbox-evidence-body")).overflowY }));
    assert.strictEqual(afterEvidence.height, beforeEvidence.height);
    assert.strictEqual(afterEvidence.scrollY, beforeEvidence.scrollY);
    assert.match(afterEvidence.overflow, /auto|scroll/);
    await page.locator("#inbox-evidence-dialog button[value=close]").click();
    await page.screenshot({ path: `${screenshotDir}/inbox-ece-${viewport.width}x${viewport.height}.png` });
  }
  await browser.close();
  console.log(`UI layout browser regression passed; screenshots: ${screenshotDir}`);
}

main().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
