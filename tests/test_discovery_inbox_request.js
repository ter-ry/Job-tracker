const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync("static/app.js", "utf8");
const start = source.indexOf("function discoveryInboxRequestUrl");
const end = source.indexOf("\nasync function reEvaluateDiscoveryHistory", start);
assert.ok(start >= 0 && end > start, "Inbox request builder is present");
const calls = [];
const context = {
  URLSearchParams,
  state: {
    selectedCandidateProfileId: "7", discoveryInboxCategory: "review_required",
    discoveryInboxSearchId: "a".repeat(32), discoveryInboxPage: 0, discoveryInboxJobs: [],
  },
  document: { getElementById: () => ({ textContent: "" }) },
  renderDiscoveryInbox: () => {},
  api: { get: async (url) => { calls.push(url); return []; } },
};
vm.runInNewContext(`${source.slice(start, end)}; this.loadDiscoveryInbox = loadDiscoveryInbox; this.discoveryInboxRequestUrl = discoveryInboxRequestUrl;`, context);

(async () => {
  const searchId = context.state.discoveryInboxSearchId;
  await context.loadDiscoveryInbox(true);
  const scopedUrl = calls.filter((url) => url.startsWith("/api/discovery/inbox?")).at(-1);
  const scoped = new URL(`http://localhost${scopedUrl}`);
  assert.strictEqual(scoped.searchParams.get("candidate_profile_id"), "7");
  assert.strictEqual(scoped.searchParams.get("category"), "review_required");
  assert.strictEqual(scoped.searchParams.get("search_id"), searchId);
  assert.strictEqual(scoped.searchParams.get("include_history"), "1");

  context.state.discoveryInboxCategory = "all_relevant";
  context.state.discoveryInboxSearchId = "";
  await context.loadDiscoveryInbox(true);
  const cumulativeUrl = calls.filter((url) => url.startsWith("/api/discovery/inbox?")).at(-1);
  const cumulative = new URL(`http://localhost${cumulativeUrl}`);
  assert.strictEqual(cumulative.searchParams.get("category"), null);
  assert.strictEqual(cumulative.searchParams.get("search_id"), null);

  assert.throws(() => context.discoveryInboxRequestUrl({ category: "all_relevant", searchId }), /Needs Review/);
  console.log("discovery Inbox request flow passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
