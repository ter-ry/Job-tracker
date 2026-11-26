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
  await page.route("**/api/candidate-profiles", async (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([
    { id: 201, name: "SWE applicant", workflow: "software" },
    { id: 202, name: "ECE applicant", workflow: "ece" },
  ]) }));
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.locator("#global-applicant-selector option").nth(1).waitFor({ state: "attached" });
  await page.locator("#global-applicant-selector").selectOption("202");

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
    await page.evaluate(() => {
      state.discoveryWorkflow = "ece";
      state.candidateProfiles = [{ id: 202, name: "ECE applicant", workflow: "ece" }];
      state.selectedCandidateProfileId = "202";
      state.discoveryInboxCategory = "ready_to_apply";
      state.discoveryInboxCounts = { ready_to_apply: 1 };
      renderDiscoveryInbox([{
        id: 77, title: "Registered ECE", company: "Inspire Montessori School", provider_company: "Inspire Montessori School",
        workflow: "ece", location: "Scarborough, ON", workplace_address: "55 Town Centre Crt, Scarborough, ON M1P 4X4",
        workplace_precision: "street address", employment_type: "permanent, full-time and part-time", salary: "$25/hour",
        discovery_result_category: "actionable", discovery_result_reason: "Stored ECE evidence", url: "https://example.test/77",
        discovery_inbox_category: "ready_to_apply",
      }]);
    });
    const inbox = await page.evaluate(() => {
      const row = document.querySelector(".inbox-row");
      const vacancy = row.querySelector(".inbox-vacancy");
      return {
        columns: getComputedStyle(row).gridTemplateColumns,
        vacancyWidth: vacancy.getBoundingClientRect().width,
        rowWidth: row.getBoundingClientRect().width,
        text: row.innerText,
        actionCount: row.querySelectorAll(".row-actions .button").length,
      };
    });
    assert.strictEqual(inbox.columns.split(" ").length, 1);
    assert.ok(inbox.vacancyWidth > inbox.rowWidth * 0.8);
    assert.match(inbox.text, /Inspire Montessori School/);
    assert.match(inbox.text, /55 Town Centre Crt/);
    assert.doesNotMatch(inbox.text, /Detected seniority|Technical compatibility|résumé/i);
    assert.ok(inbox.actionCount >= 2);
    await page.screenshot({ path: `${screenshotDir}/inbox-ece-${viewport.width}x${viewport.height}.png` });
  }
  await browser.close();
  console.log(`UI layout browser regression passed; screenshots: ${screenshotDir}`);
}

main().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
