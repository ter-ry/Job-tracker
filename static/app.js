const state = {
  jobs: [],
  profile: {},
  evidence: [],
  generatedText: "",
  activeJobId: "",
  discoveryResults: [],
  discoveryPreferences: {},
  discoverySearchKey: "",
  discoveryMeta: {},
  discoveryView: "table",
  shortlist: [],
  preparationQueue: [],
  candidateProfiles: [],
  generationSelections: {},
  selectedCandidateProfileId: "",
};

const jobFields = [
  "company",
  "title",
  "location",
  "url",
  "application-url",
  "source",
  "salary",
  "deadline",
  "remote-type",
  "role-type",
  "seniority-level",
  "status",
  "date-applied",
  "fit-score",
  "skills-match-score",
  "role-match-score",
  "location-score",
  "remote-score",
  "salary-score",
  "seniority-score",
  "coding-risk-score",
  "application-effort-score",
  "required-skills",
  "preferred-skills",
  "responsibilities",
  "notes",
  "job-description",
];

const profileFields = [
  "name",
  "email",
  "phone",
  "location",
  "preferred-roles",
  "preferred-locations",
  "work-authorization",
  "key-skills",
  "projects",
  "education",
  "work-experience",
  "resume-text",
  "cover-letter-template",
  "cover-letter-no-dashes",
  "ollama-enabled",
  "ollama-base-url",
  "ollama-model",
  "ollama-timeout-seconds",
  "ollama-max-output-tokens",
  "ollama-max-prompt-chars",
  "target-seniority-levels",
  "maximum-required-years",
  "willing-to-apply-to-stretch-roles",
  "management-roles-allowed",
];

const api = {
  async get(path) {
    const response = await fetch(path);
    if (!response.ok) throw new Error("Request failed");
    return response.json();
  },
  async send(path, method, body) {
    const response = await fetch(path, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || "Request failed");
    }
    return response.json();
  },
  async upload(path, formData) {
    const response = await fetch(path, { method: "POST", body: formData });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || "Upload failed");
    }
    return response.json();
  },
};

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", switchTab));
  document.getElementById("job-form").addEventListener("submit", saveJob);
  document.getElementById("profile-form").addEventListener("submit", saveProfile);
  document.getElementById("discovery-form").addEventListener("submit", searchDiscovery);
  document.getElementById("saved-search-form").addEventListener("submit", saveSavedSearch);
  document.getElementById("new-saved-search").addEventListener("click", () => toggleSavedSearchForm(true));
  document.getElementById("cancel-saved-search").addEventListener("click", () => toggleSavedSearchForm(false));
  document.getElementById("refresh-saved-searches").addEventListener("click", loadSavedSearches);
  document.getElementById("refresh-discovery-inbox").addEventListener("click", loadDiscoveryInbox);
  document.getElementById("toggle-discovery-scheduler").addEventListener("click", toggleDiscoveryScheduler);
  document.getElementById("refresh-discovery-task-status")?.addEventListener("click", loadDiscoveryTaskStatus);
  document.getElementById("csv-import-form").addEventListener("submit", importCsv);
  document.getElementById("discovery-test-sources").addEventListener("click", testJobSources);
  document.getElementById("refresh-shortlist").addEventListener("click", loadAll);
  document.getElementById("refresh-preparation-queue")?.addEventListener("click", loadPreparationQueue);
  document.getElementById("preparation-status-filter")?.addEventListener("change", loadPreparationQueue);
  document.getElementById("generate").addEventListener("click", generateMaterials);
  document.getElementById("analyse-resume-match").addEventListener("click", analyseResumeMatch);
  document.getElementById("generate-local-draft").addEventListener("click", generateLocalDraft);
  document.getElementById("rescore-current").addEventListener("click", rescoreCurrent);
  document.getElementById("rescore-all").addEventListener("click", rescoreAll);
  document.getElementById("reset-form").addEventListener("click", resetForm);
  document.getElementById("copy-output").addEventListener("click", copyOutput);
  document.getElementById("extract-description").addEventListener("click", extractDescription);
  document.getElementById("extract-url").addEventListener("click", extractUrl);
  document.getElementById("profile-test-location").addEventListener("click", testAndSaveLocation);
  document.getElementById("resume-upload").addEventListener("change", uploadResume);
  document.getElementById("cover-letter-template-upload").addEventListener("change", uploadCoverLetterTemplate);
  document.getElementById("new-candidate-profile").addEventListener("click", () => showCandidateProfileForm());
  document.getElementById("cancel-candidate-profile").addEventListener("click", hideCandidateProfileForm);
  document.getElementById("candidate-profile-form").addEventListener("submit", saveCandidateProfile);
  document.getElementById("discovery-view-cards").addEventListener("click", () => setDiscoveryView("cards"));
  document.getElementById("discovery-view-table").addEventListener("click", () => setDiscoveryView("table"));
  document.getElementById("discovery-filter-toggle").addEventListener("click", toggleDiscoveryFilters);
  document.getElementById("discovery-clear-filters").addEventListener("click", clearDiscoveryFilters);
  document.getElementById("discovery-show-all").addEventListener("click", showAllFetchedDiscoveryJobs);
  ["search", "status-filter", "fit-filter", "role-filter", "remote-filter", "risk-filter", "sort-by"].forEach((id) => {
    document.getElementById(id).addEventListener("input", renderJobs);
    document.getElementById(id).addEventListener("change", renderJobs);
  });
  [
    "discovery-sort-mode",
    "discovery-date-window",
    "discovery-per-source-cap",
    "discovery-total-cap",
    "discovery-remote-preference",
    "discovery-bypass-cache",
    "discovery-keywords",
    "discovery-location",
    "discovery-filter-salary-min",
    "discovery-filter-max-distance",
    "discovery-filter-overall-score-min",
    "discovery-filter-posted-within",
    "discovery-filter-remote",
    "discovery-filter-source",
    "discovery-filter-job-field",
    "discovery-filter-seniority",
    "discovery-filter-known-salary",
    "discovery-filter-known-location",
    "discovery-filter-exact-date",
    "discovery-filter-company",
    "discovery-filter-title-keywords",
  ].forEach((id) => {
    const element = document.getElementById(id);
    if (!element) return;
    element.addEventListener("input", handleDiscoveryControlsChanged);
    element.addEventListener("change", handleDiscoveryControlsChanged);
  });
  document.getElementById("discovery-search-depth").addEventListener("change", () => {
    syncDiscoveryDepthDefaults();
    handleDiscoveryControlsChanged();
  });
  applyDiscoverySearchDefaults();
  setDiscoveryControlsEnabled(false);
  loadAll();
  loadSavedSearches();
  loadDiscoveryInbox();
  loadDiscoveryScheduler();
  loadDiscoveryTaskStatus();
});

async function loadAll() {
  try {
    const [jobs, dashboard, profile, ollamaHealth, systemHealth, evidence, candidateProfiles] = await Promise.all([
      api.get("/api/jobs"),
      api.get("/api/dashboard"),
      api.get("/api/profile"),
      api.get("/api/ollama/health").catch((error) => ({ status: "error", summary: error.message })),
      api.get("/api/health").catch((error) => ({ status: "error", summary: error.message })),
      api.get("/api/evidence").catch(() => []),
      api.get("/api/candidate-profiles").catch(() => []),
    ]);
    const shortlist = await api.get("/api/shortlist");
    state.jobs = jobs;
    state.profile = profile;
    state.evidence = evidence;
    state.shortlist = shortlist;
    await loadPreparationQueue();
    state.candidateProfiles = Array.isArray(candidateProfiles) ? candidateProfiles : [];
    await hydrateGenerationSelections();
    state.systemHealth = systemHealth;
    renderDashboard(dashboard);
    renderPipelineDashboard(jobs);
    renderProfile(profile);
    renderCandidateProfiles();
    renderTemplateStatus(profile);
    renderOllamaHealth(ollamaHealth);
    renderEvidenceLibrary(evidence);
    renderJobs();
    renderShortlist();
    await refreshShortlistKeywordScores();
  } catch (error) {
    toast(error.message);
  }
}

async function loadPreparationQueue() {
  const target = document.getElementById("preparation-queue");
  if (!target) return;
  try {
    const status = value("preparation-status-filter");
    state.preparationQueue = await api.get(`/api/preparation/queue${status ? `?status=${encodeURIComponent(status)}` : ""}`);
    renderPreparationQueue();
  } catch (error) { target.textContent = error.message; }
}

function renderPreparationQueue() {
  const target = document.getElementById("preparation-queue");
  if (!target) return;
  const items = Array.isArray(state.preparationQueue) ? state.preparationQueue : [];
  target.classList.toggle("empty", !items.length);
  if (!items.length) { target.textContent = "No application packages queued."; return; }
  target.innerHTML = items.map((item) => {
    const job = item.job || {};
    const score = item.keywords_score || {};
    const matched = score.matched_count != null ? `${score.matched_count}/${score.total || 0}` : "not reviewed";
    const error = item.error || item.resume_error || item.cover_letter_error;
    const actions = item.status === "ready_for_review"
      ? `<button class="button small" type="button" onclick="reviewPreparation(${item.id}, 'approve')">Approve package</button><button class="button ghost small" type="button" onclick="previewPreparation(${item.id})">Preview</button><button class="button ghost small" type="button" onclick="regeneratePreparation(${item.id})">Regenerate</button>${item.prepared_resume_path ? `<a class="button ghost small" href="/api/preparation/${item.id}/download/resume">Download résumé</a>` : ""}${item.prepared_cover_letter_path ? `<a class="button ghost small" href="/api/preparation/${item.id}/download/cover-letter">Download cover letter</a>` : ""}`
      : item.status === "queued" || item.status === "failed"
        ? `${item.review_status === "manual_eligibility" ? `<button class="button small" type="button" onclick="reviewEligibility(${item.id})">Confirm Canadian eligibility</button>` : `<button class="button small" type="button" onclick="prepareQueueItem(${item.id})">${item.status === "failed" ? "Retry preparation" : "Prepare package"}</button>`}`
        : "";
    return `<article class="preparation-row"><div class="preparation-main"><h3>${escapeHtml(job.title || "Untitled role")}</h3><p><strong>${escapeHtml(job.company || "Unknown company")}</strong> · ${escapeHtml(job.location || "Location unavailable")}</p><p class="muted">${escapeHtml(job.remote_eligibility || "unknown")} · ${escapeHtml(job.salary || "Salary unavailable")} · Job Priority ${Number(item.job_priority || 0)}</p><p class="muted">Profile ${escapeHtml(String(item.candidate_profile_id || "not selected"))} · Résumé ${escapeHtml(item.resume_status || "pending")} · Cover letter ${escapeHtml(item.cover_letter_status || "pending")}</p>${item.eligibility_note ? `<p class="muted">${escapeHtml(item.eligibility_note)}</p>` : ""}${error ? `<p class="risk high">${escapeHtml(error)}</p>` : ""}</div><div class="preparation-meta"><strong>${escapeHtml(item.status.replaceAll("_", " "))}</strong><span>Keywords Score ${escapeHtml(matched)}</span><div class="row-actions">${actions}${job.url ? `<a class="button ghost small" href="${escapeAttribute(job.url)}" target="_blank" rel="noreferrer">Open application</a>` : ""}<button class="button ghost small" type="button" onclick="reviewPreparation(${item.id}, 'skip')">Skip</button></div></div></article>`;
  }).join("");
}

async function queueDiscoveryJob(id) {
  try {
    const profiles = await api.get("/api/candidate-profiles");
    if (!profiles.length) throw new Error("Create a candidate profile with a résumé and cover letter template before preparing this job.");
    let profile = profiles.length === 1 ? profiles[0] : null;
    if (!profile) {
      const choices = profiles.map((item, index) => `${index + 1}. ${item.name}`).join("\n");
      const selected = window.prompt(`Choose the candidate profile for this package by number:\n${choices}`);
      const index = Number(selected) - 1;
      profile = Number.isInteger(index) && profiles[index] ? profiles[index] : null;
      if (!profile) throw new Error("Choose a valid candidate profile before preparing this job.");
    }
    const documents = await api.get(`/api/candidate-profiles/${profile.id}/documents`);
    const resume = (documents.resumes || []).find((item) => item.is_default) || documents.resumes?.[0];
    const cover = (documents.cover_letter_templates || []).find((item) => item.is_default) || documents.cover_letter_templates?.[0];
    if (!resume || !cover) throw new Error(`Profile "${profile.name}" must have both a DOCX résumé and a DOCX cover letter template before preparing this job.`);
    const item = await api.send("/api/preparation/queue", "POST", { job_id: id, candidate_profile_id: profile.id, resume_id: resume.id, cover_letter_template_id: cover.id });
    toast("Application package queued for review");
    const job = state.jobs.find((entry) => Number(entry.id) === Number(id));
    if (job) {
      openPipelineJobDetails(id);
      renderPipelinePreparationState(job, item, item.review_status === "manual_eligibility" ? "Manual eligibility review required" : "Queued for preparation");
    }
    await loadPreparationQueue();
  } catch (error) { toast(error.message); }
}

async function prepareQueueItem(id) {
  try { const result = await api.send(`/api/preparation/${id}/prepare`, "POST", {}); toast(result.status === "ready_for_review" ? "Package ready for review" : "Package preparation failed"); await loadPreparationQueue(); } catch (error) { toast(error.message); }
}

async function regeneratePreparation(id) {
  try { const result = await api.send(`/api/preparation/${id}/regenerate`, "POST", {}); toast(result.status === "ready_for_review" ? "Package regenerated for review" : "Package regeneration failed"); await loadPreparationQueue(); } catch (error) { toast(error.message); }
}

async function reviewEligibility(id) {
  if (!window.confirm("Confirm that this opportunity is eligible for work in Canada before preparing documents?")) return;
  try { await api.send(`/api/preparation/${id}/eligibility-review`, "POST", { confirmed: true }); toast("Eligibility confirmed; prepare the package when ready"); await loadPreparationQueue(); } catch (error) { toast(error.message); }
}

async function reviewPreparation(id, action) {
  try { await api.send(`/api/preparation/${id}/review`, "POST", { action }); toast(action === "approve" ? "Package approved for your next manual step" : "Package skipped"); await loadPreparationQueue(); } catch (error) { toast(error.message); }
}

async function previewPreparation(id) {
  try { const result = await api.get(`/api/preparation/${id}/preview`); const target = document.getElementById("preparation-queue"); target.insertAdjacentHTML("afterbegin", `<details class="preparation-preview" open><summary>Document preview</summary><h4>Résumé</h4><pre>${escapeHtml(result.resume || "Unavailable")}</pre><h4>Cover letter</h4><pre>${escapeHtml(result.cover_letter || "Unavailable")}</pre></details>`); } catch (error) { toast(error.message); }
}

async function loadSavedSearches() {
  const list = document.getElementById("saved-search-list");
  if (!list) return;
  try {
    const searches = await api.get("/api/discovery/searches");
    list.innerHTML = searches.length ? searches.map((search) => `
      <article class="saved-search-row">
        <div><strong>${escapeHtml(search.name)}</strong><span class="muted">${escapeHtml(search.keywords)} · ${escapeHtml(search.location || "Anywhere")}</span><span class="muted">${search.enabled ? "Scheduled" : "Manual only"} · ${escapeHtml((search.enabled_sources || []).map(sourceLabel).join(", "))} · ${search.auto_prepare_enabled ? `Auto preparation at ${Number(search.auto_prepare_min_priority || 75)}+ for new discovery results` : "Preparation manual"}</span></div>
        <div class="actions compact"><button class="button small" type="button" onclick="runSavedSearch(${search.id})">Run now</button><button class="button ghost small" type="button" onclick='editSavedSearch(${JSON.stringify(search).replaceAll("'", "&apos;")} )'>Edit</button></div>
      </article>`).join("") : `<p class="muted">No saved searches yet.</p>`;
  } catch (error) { list.innerHTML = `<p class="muted">${escapeHtml(error.message)}</p>`; }
}

function toggleSavedSearchForm(show) {
  const form = document.getElementById("saved-search-form");
  if (form) form.hidden = !show;
  if (show) document.getElementById("saved-search-name").focus();
}

function editSavedSearch(search) {
  toggleSavedSearchForm(true);
  setValue("saved-search-id", search.id);
  setValue("saved-search-name", search.name);
  setValue("saved-search-keywords", search.keywords);
  setValue("saved-search-location", search.location);
  setValue("saved-search-remote", search.remote_preference);
  setValue("saved-search-seniority", search.seniority);
  setValue("saved-search-minimum-salary", search.minimum_salary || "");
  setValue("saved-search-date-window", search.date_window || "14d");
  setValue("saved-search-interval", search.interval_minutes || 360);
  setChecked("saved-search-enabled", Boolean(search.enabled));
  setChecked("saved-search-auto-prepare", Boolean(search.auto_prepare_enabled));
  setValue("saved-search-auto-min-priority", search.auto_prepare_min_priority || 75);
  setValue("saved-search-auto-profile", search.auto_prepare_candidate_profile_id || "");
  document.querySelectorAll('input[name="saved-search-source"]').forEach((input) => { input.checked = (search.enabled_sources || []).includes(input.value); });
}

async function saveSavedSearch(event) {
  event.preventDefault();
  const id = value("saved-search-id");
  const body = {
    name: value("saved-search-name"), keywords: value("saved-search-keywords"), location: value("saved-search-location"),
    remote_preference: value("saved-search-remote"), seniority: value("saved-search-seniority"), minimum_salary: Number(value("saved-search-minimum-salary") || 0),
    date_window: value("saved-search-date-window"), interval_minutes: Number(value("saved-search-interval") || 360), enabled: checked("saved-search-enabled"),
    auto_prepare_enabled: checked("saved-search-auto-prepare"), auto_prepare_min_priority: Number(value("saved-search-auto-min-priority") || 75),
    auto_prepare_candidate_profile_id: Number(value("saved-search-auto-profile") || 0),
    enabled_sources: [...document.querySelectorAll('input[name="saved-search-source"]:checked')].map((input) => input.value),
  };
  try {
    await api.send(id ? `/api/discovery/searches/${id}` : "/api/discovery/searches", id ? "PUT" : "POST", body);
    toast("Saved search updated"); toggleSavedSearchForm(false); await loadSavedSearches();
  } catch (error) { toast(error.message); }
}

async function runSavedSearch(id) {
  try { const result = await api.send(`/api/discovery/searches/${id}/run`, "POST", {}); toast(`Discovery found ${result.persisted.new} new and ${result.persisted.duplicate} existing jobs`); await Promise.all([loadSavedSearches(), loadDiscoveryInbox()]); }
  catch (error) { toast(error.message); }
}

async function loadDiscoveryInbox() {
  const target = document.getElementById("discovery-inbox");
  if (!target) return;
  try {
    const jobs = await api.get("/api/discovery/inbox");
    target.classList.toggle("empty", !jobs.length);
    target.innerHTML = jobs.length ? jobs.map((job) => `<article class="inbox-row"><div><strong>${escapeHtml(job.title || "Untitled role")}</strong><span>${escapeHtml(job.company || "Unknown company")} · ${escapeHtml(job.location || "Location unavailable")}</span><span class="muted">${escapeHtml(job.remote_eligibility || "unknown")} · ${escapeHtml(job.salary || "Salary unavailable")} · ${escapeHtml(job.source || "JobSpy")} · ${escapeHtml(job.posted_date || "date unknown")}</span></div><div><strong>Job Priority ${Number(job.overall_score || job.fit_score || 0)}</strong><span class="muted">Discovered ${escapeHtml(job.discovery_first_seen_at || "")}</span></div><div class="row-actions"><button class="button small" type="button" onclick="reviewInboxJob(${job.id})">Review</button><button class="button ghost small" type="button" onclick="queueDiscoveryJob(${job.id})">Prepare package</button><button class="button ghost small" type="button" onclick="saveInboxJob(${job.id})">Shortlist</button><button class="button ghost small" type="button" onclick="ignoreInboxJob(${job.id})">Ignore</button>${job.url ? `<a class="button ghost small" href="${escapeAttribute(job.url)}" target="_blank" rel="noreferrer">Open</a>` : ""}</div></article>`).join("") : "No discovered opportunities yet.";
  } catch (error) { target.textContent = error.message; }
}

async function reviewInboxJob(id) { try { await api.send(`/api/discovery/inbox/${id}/review`, "POST", {}); await loadDiscoveryInbox(); } catch (error) { toast(error.message); } }
async function ignoreInboxJob(id) { try { await api.send(`/api/discovery/inbox/${id}/ignore`, "POST", {}); await loadDiscoveryInbox(); } catch (error) { toast(error.message); } }
async function saveInboxJob(id) {
  try { const jobs = await api.get("/api/jobs"); const job = jobs.find((item) => Number(item.id) === Number(id)); if (!job) throw new Error("Job not found"); await api.send("/api/shortlist", "POST", job); toast("Job shortlisted"); await loadAll(); await loadDiscoveryInbox(); }
  catch (error) { toast(error.message); }
}

async function loadDiscoveryScheduler() {
  try { const result = await api.get("/api/discovery/scheduler"); updateDiscoverySchedulerButton(result.enabled); } catch (_) { /* older databases */ }
}
function updateDiscoverySchedulerButton(enabled) { setText("toggle-discovery-scheduler", enabled ? "Disable database scheduler" : "Enable database scheduler"); setText("discovery-scheduler-status", enabled ? "Enabled for due saved searches; Windows task is separate" : "Disabled"); }
async function toggleDiscoveryScheduler() { try { const current = await api.get("/api/discovery/scheduler"); const result = await api.send("/api/discovery/scheduler", "PUT", { enabled: !current.enabled }); updateDiscoverySchedulerButton(result.enabled); } catch (error) { toast(error.message); } }
async function loadDiscoveryTaskStatus() {
  const target = document.getElementById("discovery-task-status");
  if (!target) return;
  try {
    const result = await api.get("/api/discovery/task-status");
    target.textContent = result.message || (result.installed ? "Installed" : "Not installed");
    target.classList.toggle("task-installed", Boolean(result.installed));
  } catch (error) { target.textContent = `Task status unavailable: ${error.message}`; }
}

function showCandidateProfileForm(profile = null) {
  const form = document.getElementById("candidate-profile-form");
  form.hidden = false;
  form.dataset.profileId = profile?.id || "";
  setText("candidate-profile-form-title", profile ? `Edit ${profile.name}` : "Create candidate profile");
  document.getElementById("candidate-profile-name").value = profile?.name || "";
  document.getElementById("candidate-profile-name").disabled = Boolean(profile);
  document.getElementById("candidate-profile-identity-mode").value = profile?.identity_mode || "shared";
  document.getElementById("candidate-profile-applicant-name").value = profile?.applicant_name || "";
  document.getElementById("candidate-profile-applicant-email").value = profile?.applicant_email || "";
  document.getElementById("candidate-profile-applicant-phone").value = profile?.applicant_phone || "";
  document.getElementById("candidate-profile-applicant-location").value = profile?.applicant_location || "";
}

function hideCandidateProfileForm() {
  const form = document.getElementById("candidate-profile-form");
  form.hidden = true;
  form.reset();
  form.dataset.profileId = "";
  document.getElementById("candidate-profile-name").disabled = false;
}

async function saveCandidateProfile(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = {
    name: value("candidate-profile-name"),
    identity_mode: value("candidate-profile-identity-mode"),
    applicant_name: value("candidate-profile-applicant-name"),
    applicant_email: value("candidate-profile-applicant-email"),
    applicant_phone: value("candidate-profile-applicant-phone"),
    applicant_location: value("candidate-profile-applicant-location"),
  };
  try {
    if (form.dataset.profileId) await api.send(`/api/candidate-profiles/${form.dataset.profileId}`, "PATCH", payload);
    else await api.send("/api/candidate-profiles", "POST", payload);
    hideCandidateProfileForm();
    toast("Candidate profile saved");
    await loadAll();
  } catch (error) { toast(error.message); }
}

function renderCandidateProfiles() {
  const list = document.getElementById("candidate-profile-list");
  if (!list) return;
  if (!state.candidateProfiles.length) {
    list.innerHTML = '<p class="muted">No reusable candidate profiles yet.</p>';
    document.getElementById("candidate-profile-documents").classList.add("empty");
    document.getElementById("candidate-profile-documents").textContent = "Create a profile to add role-specific documents.";
    return;
  }
  if (!state.selectedCandidateProfileId) state.selectedCandidateProfileId = String(state.candidateProfiles[0].id);
  const autoProfile = document.getElementById("saved-search-auto-profile");
  if (autoProfile) autoProfile.innerHTML = `<option value="">Choose a profile when available</option>${state.candidateProfiles.map((profile) => `<option value="${escapeAttribute(profile.id)}">${escapeHtml(profile.name)}</option>`).join("")}`;
  list.innerHTML = state.candidateProfiles.map((profile) => `
    <article class="candidate-profile-card ${String(profile.id) === state.selectedCandidateProfileId ? "selected" : ""}">
      <div><h3>${escapeHtml(profile.name)}</h3><p class="muted">${profile.identity_mode === "distinct" ? escapeHtml(profile.applicant_name || "Distinct identity not set") : "Uses active profile identity"}</p></div>
      <div class="actions compact"><button class="button small ghost" type="button" onclick="selectCandidateProfile(${profile.id})">Manage documents</button><button class="button small ghost" type="button" onclick='showCandidateProfileForm(${JSON.stringify(profile).replaceAll("'", "&#39;")})'>Edit identity</button></div>
    </article>`).join("");
  renderCandidateProfileDocuments();
}

async function selectCandidateProfile(profileId) {
  state.selectedCandidateProfileId = String(profileId);
  renderCandidateProfiles();
  await renderCandidateProfileDocuments();
}

async function renderCandidateProfileDocuments() {
  const target = document.getElementById("candidate-profile-documents");
  if (!target || !state.selectedCandidateProfileId) return;
  const profile = state.candidateProfiles.find((item) => String(item.id) === state.selectedCandidateProfileId);
  if (!profile) return;
  try {
    const documents = await api.get(`/api/candidate-profiles/${profile.id}/documents`);
    const documentRows = (items, kind, label) => items.length ? items.map((item) => `<li><span>${escapeHtml(item.name)}${item.is_default ? " <strong>(default)</strong>" : ""}</span>${item.is_default ? "" : `<button class="button small ghost" type="button" onclick="setCandidateDefault(${profile.id}, '${kind}', ${item.id})">Set default</button>`}</li>`).join("") : `<li class="muted">No ${label} uploaded yet.</li>`;
    target.classList.remove("empty");
    target.innerHTML = `<div class="panel-header"><h3>${escapeHtml(profile.name)} documents</h3><span class="muted">Original DOCX files are kept in the application data directory.</span></div>
      <div class="grid two"><label>Upload base résumé (.docx)<input id="candidate-resume-file" type="file" accept=".docx" onchange="uploadCandidateDocument(${profile.id}, 'resume', this)"></label><label>Upload cover letter template (.docx)<input id="candidate-cover-file" type="file" accept=".docx" onchange="uploadCandidateDocument(${profile.id}, 'cover', this)"></label></div>
      <div class="grid two document-columns"><div><h4>Base résumés</h4><ul class="document-list">${documentRows(documents.resumes || [], "resume", "résumés")}</ul></div><div><h4>Cover letter templates</h4><ul class="document-list">${documentRows(documents.cover_letter_templates || [], "cover", "templates")}</ul></div></div>`;
  } catch (error) { target.textContent = error.message; }
}

async function uploadCandidateDocument(profileId, kind, input) {
  const file = input.files[0];
  if (!file) return;
  const data = new FormData();
  data.append("file", file);
  data.append("is_default", "true");
  try {
    const route = kind === "resume" ? "resumes" : "cover-letter-templates";
    await api.upload(`/api/candidate-profiles/${profileId}/${route}/upload`, data);
    toast("Document uploaded and selected as default");
    await loadAll();
  } catch (error) { toast(error.message); }
}

async function setCandidateDefault(profileId, kind, documentId) {
  try {
    const route = kind === "resume" ? "resumes" : "cover-letter-templates";
    await api.send(`/api/candidate-profiles/${profileId}/${route}/${documentId}/default`, "POST", {});
    toast("Default document updated");
    await loadAll();
  } catch (error) { toast(error.message); }
}

function switchTab(event) {
  const target = event.currentTarget.dataset.tab;
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === target));
  document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.id === target));
}

function renderDashboard(dashboard) {
  setText("jobs-saved", dashboard.jobs_saved);
  setText("applications-this-week", dashboard.applications_this_week);
  setText("follow-ups-needed", dashboard.follow_ups_needed);
  setText("high-fit-jobs", dashboard.high_fit);
  setText("average-fit-score", dashboard.average_fit_score);
  setText("interview-rate", `${dashboard.interview_rate}%`);
  setText("missing-salary", dashboard.missing_salary);
  setText("high-coding-risk", dashboard.high_coding_risk);
}

let pipelineCategory = "All";
let pipelineSort = "qualification";

function normalizedPipelineSalary(job) {
  const value = Number(job.salary_midpoint || job.salary_max || job.salary_min || 0);
  if (!value) return null;
  const currency = String(job.salary_currency || "CAD").toUpperCase();
  const toCad = { CAD: 1, USD: 1.36, EUR: 1.48, GBP: 1.74, AUD: 0.9 };
  return value * (toCad[currency] || 1);
}

function pipelineSortValue(job, mode) {
  if (mode === "qualification") return Number(job.qualification_fit_score ?? -1);
  if (mode === "priority") return Number(job.overall_score ?? -1);
  if (mode === "salary") return normalizedPipelineSalary(job);
  if (mode === "distance") return job.distance_km === "" || job.distance_km == null ? null : Number(job.distance_km);
  if (mode === "posted") return job.posted_date ? Date.parse(job.posted_date) : null;
  if (mode === "discovered") return job.discovery_first_seen_at ? Date.parse(job.discovery_first_seen_at) : null;
  if (mode === "deadline") return job.deadline ? Date.parse(job.deadline) : null;
  return null;
}

function sortPipelineJobs(items, mode) {
  return [...items].sort((a, b) => {
    const left = pipelineSortValue(a, mode);
    const right = pipelineSortValue(b, mode);
    if (left === null && right === null) return Number(a.id || 0) - Number(b.id || 0);
    if (left === null) return 1;
    if (right === null) return -1;
    return mode === "distance" || mode === "deadline" ? left - right : right - left;
  });
}

function renderPipelineDashboard(jobs) {
  const items = Array.isArray(jobs) ? jobs : [];
  const categories = ["All", ...new Set(items.map((job) => String(job.role_type || "").trim()).filter(Boolean))];
  const filters = document.getElementById("pipeline-filters");
  if (!filters) return;
  if (!categories.includes(pipelineCategory)) pipelineCategory = "All";
  filters.innerHTML = categories.map((category) => `<button class="pipeline-filter ${category === pipelineCategory ? "active" : ""}" role="tab" aria-selected="${category === pipelineCategory}" data-category="${escapeHtml(category)}">${escapeHtml(category)}</button>`).join("");
  filters.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => {
    pipelineCategory = button.dataset.category || "All";
    renderPipelineDashboard(items);
  }));
  const sortControl = document.getElementById("pipeline-sort");
  if (sortControl) {
    sortControl.value = pipelineSort;
    sortControl.onchange = (event) => { pipelineSort = event.target.value; renderPipelineDashboard(state.jobs); };
  }
  const filtered = pipelineCategory === "All" ? items : items.filter((job) => String(job.role_type || "") === pipelineCategory);
  setText("pipeline-discovered", items.length);
  setText("pipeline-matches", items.filter((job) => Number(job.qualification_fit_score || 0) >= 75).length);
  setText("pipeline-ready", items.filter((job) => ["ready_for_review"].includes(job.preparation_status)).length);
  const cards = document.getElementById("pipeline-cards");
  if (!filtered.length) {
    cards.innerHTML = `<p class="pipeline-empty">No saved jobs match this category.</p>`;
    return;
  }
  cards.innerHTML = sortPipelineJobs(filtered, pipelineSort).map((job) => {
    const score = Number(job.qualification_fit_score ?? job.fit_score ?? 0);
    const priority = Number(job.overall_score || 0);
    return `<article class="pipeline-card" data-job-id="${job.id}"><div><h3>${escapeHtml(job.title || "Untitled role")}</h3><p>${escapeHtml(job.company || "Unknown company")} · ${escapeHtml(job.location || "Location not listed")}</p><p class="pipeline-subline">${escapeHtml(job.qualification_fit_label || "Qualification fit")}</p></div><div class="pipeline-score"><strong>${score}%</strong><span>Qualification fit</span><small>Job Priority ${priority}</small><button type="button" data-job-id="${job.id}" class="pipeline-action">View details</button></div></article>`;
  }).join("");
  cards.querySelectorAll(".pipeline-card").forEach((card) => card.addEventListener("click", (event) => {
    if (event.target.closest("button, a")) return;
    openPipelineJobDetails(Number(card.dataset.jobId));
  }));
  cards.querySelectorAll(".pipeline-action").forEach((button) => button.addEventListener("click", () => {
    openPipelineJobDetails(Number(button.dataset.jobId));
  }));
}

function openPipelineJobDetails(id) {
  const job = state.jobs.find((item) => Number(item.id) === Number(id));
  const panel = document.getElementById("pipeline-job-details");
  if (!job || !panel) return;
  const requirements = [job.required_skills, job.preferred_skills, job.responsibilities].filter(Boolean).join("\n\n");
  const reasons = (job.qualification_fit_reasons || []).map((reason) => `<li>${escapeHtml(reason)}</li>`).join("") || "<li>Review the full posting and résumé evidence before applying.</li>";
  panel.innerHTML = `<div class="pipeline-detail-header"><div><span class="eyebrow">Job details</span><h3>${escapeHtml(job.title || "Untitled role")}</h3><p>${escapeHtml(job.company || "Unknown company")} · ${escapeHtml(job.location || "Location not listed")}</p></div><button class="button ghost small" type="button" data-close-job-details>Close</button></div><div class="pipeline-detail-grid"><div><strong>Qualification fit</strong><p class="pipeline-detail-score">${Number(job.qualification_fit_score ?? job.fit_score ?? 0)}% · ${escapeHtml(job.qualification_fit_label || "Review required")}</p><ul>${reasons}</ul></div><div><strong>Job Priority</strong><p>${Number(job.overall_score || 0)}</p><strong>Salary</strong><p>${escapeHtml(job.salary || "Not listed")}</p><strong>Posting date</strong><p>${escapeHtml(job.posted_date || "Not listed")}</p><strong>Deadline</strong><p>${escapeHtml(job.deadline || "Not listed")}</p></div></div><details open><summary>Requirements and responsibilities</summary><pre>${escapeHtml(requirements || "No structured requirements were stored.")}</pre></details><details><summary>Full job description</summary><pre>${escapeHtml(job.job_description || "No job description was stored.")}</pre></details><p class="pipeline-detail-links">${job.url ? `<a href="${escapeAttribute(job.url)}" target="_blank" rel="noreferrer">Original posting</a>` : "Original posting unavailable"}${job.application_url && job.application_url !== job.url ? ` · <a href="${escapeAttribute(job.application_url)}" target="_blank" rel="noreferrer">Application page</a>` : ""}</p><div class="actions"><button class="button" type="button" data-prepare-job="${job.id}">Prepare application</button><button class="button ghost" type="button" data-edit-job="${job.id}">Edit job</button></div>`;
  panel.hidden = false;
  panel.querySelector("[data-close-job-details]").addEventListener("click", () => { panel.hidden = true; });
  panel.querySelector("[data-prepare-job]").addEventListener("click", () => queueDiscoveryJob(id));
  panel.querySelector("[data-edit-job]").addEventListener("click", () => { panel.hidden = true; switchTab({ currentTarget: { dataset: { tab: "tracker" } } }); loadJob(job); });
  panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  const existingPreparation = state.preparationQueue.find((item) => Number(item.job_id) === Number(id));
  if (existingPreparation) renderPipelinePreparationState(job, existingPreparation, existingPreparation.status === "approved" ? "Package approved; ready for your next manual step" : "Existing package status");
}

function renderPipelinePreparationState(job, item, message = "") {
  const panel = document.getElementById("pipeline-job-details");
  if (!panel || !item) return;
  const status = String(item.status || "queued").replaceAll("_", " ");
  const error = item.error || item.resume_error || item.cover_letter_error || "";
  const ready = item.status === "ready_for_review";
  const approved = item.status === "approved";
  const manualEligibility = item.review_status === "manual_eligibility";
  const wrapper = document.createElement("section");
  wrapper.className = "pipeline-preparation-state";
  wrapper.dataset.pipelinePreparation = item.id;
  wrapper.innerHTML = `<h4>Application preparation</h4><p class="pipeline-preparation-status"><strong>${escapeHtml(status)}</strong>${message ? ` · ${escapeHtml(message)}` : ""}</p>${manualEligibility ? `<p class="muted">Canadian eligibility is unknown. Confirm it before document generation.</p><button class="button small" type="button" data-confirm-pipeline-eligibility>Confirm Canadian eligibility</button>` : error ? `<p class="risk high">${escapeHtml(error)}</p>` : ready || approved ? `<p class="muted">${approved ? "This package was approved for your next manual step. Nothing was submitted." : "Both documents are ready for your review. Nothing was submitted."}</p><div class="actions compact"><button class="button small" type="button" data-preview-pipeline-preparation>Preview documents</button><a class="button ghost small" href="/api/preparation/${item.id}/download/resume">Download résumé DOCX</a><a class="button ghost small" href="/api/preparation/${item.id}/download/cover-letter">Download cover letter DOCX</a>${approved ? "" : `<button class="button ghost small" type="button" data-approve-pipeline-preparation>Approve package</button>`}</div><div data-pipeline-preview></div>` : `<p class="muted">The package is queued and ready to start. Generation does not submit an application.</p><button class="button small" type="button" data-start-pipeline-preparation>Start preparation now</button>`}`;
  panel.querySelector("[data-pipeline-preparation]")?.remove();
  panel.appendChild(wrapper);
  wrapper.querySelector("[data-confirm-pipeline-eligibility]")?.addEventListener("click", () => confirmPipelineEligibility(item.id, job.id));
  wrapper.querySelector("[data-start-pipeline-preparation]")?.addEventListener("click", () => startPipelinePreparation(item.id, job.id));
  wrapper.querySelector("[data-preview-pipeline-preparation]")?.addEventListener("click", () => previewPipelinePreparation(item.id));
  wrapper.querySelector("[data-approve-pipeline-preparation]")?.addEventListener("click", () => approvePipelinePreparation(item.id, job.id));
}

async function startPipelinePreparation(itemId, jobId) {
  const panel = document.getElementById("pipeline-job-details");
  const state = panel?.querySelector("[data-pipeline-preparation]");
  if (state) state.querySelector(".pipeline-preparation-status").innerHTML = "<strong>preparing</strong> · Generating the selected documents…";
  try {
    const item = await api.send(`/api/preparation/${itemId}/prepare`, "POST", {});
    await loadAll();
    openPipelineJobDetails(jobId);
    const updatedJob = window.state.jobs.find((entry) => Number(entry.id) === Number(jobId));
    if (updatedJob) renderPipelinePreparationState(updatedJob, item, item.status === "ready_for_review" ? "Documents generated successfully" : "Preparation finished");
  } catch (error) {
    if (state) state.insertAdjacentHTML("beforeend", `<p class="risk high">${escapeHtml(error.message)}</p>`);
  }
}

async function confirmPipelineEligibility(itemId, jobId) {
  if (!window.confirm("Confirm that this opportunity is eligible for work in Canada before preparing documents?")) return;
  try { await api.send(`/api/preparation/${itemId}/eligibility-review`, "POST", { confirmed: true }); toast("Eligibility confirmed"); await loadAll(); openPipelineJobDetails(jobId); } catch (error) { toast(error.message); }
}

async function previewPipelinePreparation(itemId) {
  try {
    const result = await api.get(`/api/preparation/${itemId}/preview`);
    const target = document.querySelector("[data-pipeline-preparation] [data-pipeline-preview]");
    if (target) target.innerHTML = `<details class="preparation-preview" open><summary>Generated package preview</summary><h5>Résumé</h5><pre>${escapeHtml(result.resume || "Unavailable")}</pre><h5>Cover letter</h5><pre>${escapeHtml(result.cover_letter || "Unavailable")}</pre></details>`;
  } catch (error) { toast(error.message); }
}

async function approvePipelinePreparation(itemId, jobId) {
  try {
    await api.send(`/api/preparation/${itemId}/review`, "POST", { action: "approve" });
    toast("Package approved for your next manual step");
    await loadAll();
    openPipelineJobDetails(jobId);
    const item = state.preparationQueue.find((entry) => Number(entry.job_id) === Number(jobId));
    if (item) renderPipelinePreparationState(state.jobs.find((entry) => Number(entry.id) === Number(jobId)), item, "Package approved; ready for your next manual step");
  } catch (error) { toast(error.message); }
}

function renderProfile(profile) {
  profileFields.forEach((field) => setValue(`profile-${field}`, profile[toSnake(field)] || ""));
  renderProfileLocationStatus(profile);
}

function renderTemplateStatus(profile) {
  const hasDocx = Boolean(profile.cover_letter_docx_template_path);
  setText(
    "cover-letter-template-status",
    hasDocx
      ? "DOCX template uploaded — formatting-preserving generation available"
      : "No DOCX template uploaded — standard cover-letter formatting will be used"
  );
}

function hasDiscoveryOrigin() {
  const profile = state.profile || {};
  return Boolean(profile.home_location_normalized && profile.home_location_latitude && profile.home_location_longitude && ["saved", "cached"].includes(String(profile.home_location_status || "").toLowerCase()));
}

function renderProfileLocationStatus(profile) {
  const element = document.getElementById("profile-location-status");
  if (!element) return;
  const status = String(profile.home_location_status || "").toLowerCase();
  if (!profile.location) {
    element.textContent = "No home location saved yet.";
    return;
  }
  if (status === "failed") {
    element.textContent = `Location could not be geocoded: ${profile.home_location_error || "unknown error"}`;
    return;
  }
  if (status === "missing") {
    element.textContent = "No home location saved yet.";
    return;
  }
  const precision = profile.home_location_precision || "approximate";
  const normalized = profile.home_location_normalized || profile.location;
  const confidence = profile.home_location_confidence ? `, confidence ${profile.home_location_confidence}%` : "";
  const geocodedAt = profile.home_location_geocoded_at ? ` · checked ${profile.home_location_geocoded_at}` : "";
  element.innerHTML = `Location saved: ${escapeHtml(normalized)} — ${escapeHtml(precision)}${confidence}${geocodedAt}`;
}

function renderOllamaHealth(report) {
  const element = document.getElementById("ollama-health-status");
  if (!element) return;
  if (!report) {
    element.textContent = "Ollama health has not been checked yet.";
    return;
  }
  const parts = [
    report.summary || `Status: ${report.status || "unknown"}`,
    report.enabled ? `Model: ${report.model_name || ""}` : "Disabled",
    report.base_url ? `URL: ${report.base_url}` : "",
    report.reachable ? "Reachable" : "",
    report.model_available ? "Model available" : "",
    report.failure_reason ? `Reason: ${report.failure_reason}` : "",
    report.pull_command ? `Pull: ${report.pull_command}` : "",
  ].filter(Boolean);
  element.textContent = parts.join(" | ");
}

function renderEvidenceLibrary(items) {
  const element = document.getElementById("evidence-library");
  if (!element) return;
  if (!Array.isArray(items) || !items.length) {
    element.classList.add("empty");
    element.textContent = "Saved evidence will appear here.";
    return;
  }
  element.classList.remove("empty");
  element.innerHTML = `
    <div class="review-list">
      ${items
        .slice(0, 12)
        .map(
          (item) => `
            <div class="match-item">
              <strong>${escapeHtml(item.source_label || item.source_field || "Evidence")}</strong>
              <p>${escapeHtml(item.content || "")}</p>
              <div class="actions compact">
                <button class="button small ghost" type="button" onclick="reviewEvidence(${item.id}, true)">Approve</button>
                <button class="button small ghost danger" type="button" onclick="reviewEvidence(${item.id}, false)">Reject</button>
              </div>
              <span class="muted">${item.approved ? "Approved" : "Pending"} · ${escapeHtml(item.review_notes || "")}</span>
            </div>
          `
        )
        .join("")}
    </div>
  `;
}

function renderJobs() {
  const tbody = document.getElementById("jobs-table");
  const search = value("search").toLowerCase();
  const status = value("status-filter");
  const fit = Number(value("fit-filter") || 0);
  const role = value("role-filter");
  const remote = value("remote-filter");
  const risk = value("risk-filter");
  const sortBy = value("sort-by");

  let jobs = state.jobs.filter((job) => {
    const content = `${job.company} ${job.title} ${job.location} ${job.notes} ${job.required_skills}`.toLowerCase();
    const salaryFilter = true;
    return (
      (!search || content.includes(search)) &&
      (!status || job.status === status) &&
      (!fit || Number(job.fit_score || 0) >= fit) &&
      (!role || job.role_type === role) &&
      (!remote || job.remote_type === remote) &&
      (!risk || (risk === "high" ? Number(job.coding_risk_score || 100) < 60 : Number(job.coding_risk_score || 0) >= 60)) &&
      salaryFilter
    );
  });

  jobs = sortJobs(jobs, sortBy);

  if (!jobs.length) {
    tbody.innerHTML = `<tr><td colspan="9" class="muted">No applications match this view.</td></tr>`;
    return;
  }

  tbody.innerHTML = jobs
    .map(
      (job) => `
        <tr>
          <td><strong>${escapeHtml(job.company)}</strong><br>${linkFor(job.url || job.application_url)}</td>
          <td>${escapeHtml(job.title)}<br><span class="muted">${escapeHtml(job.role_type || "")}</span></td>
          <td>${escapeHtml(job.location || "")}<br><span class="muted">${escapeHtml(job.remote_type || "")}</span></td>
          <td>${scorePill(job.fit_score)}<div class="mini-breakdown">${miniBreakdown(job)}</div></td>
          <td>${riskLabel(job)}</td>
          <td>${escapeHtml(job.status)}</td>
          <td>${escapeHtml(job.salary || "Missing")}</td>
          <td>${escapeHtml(job.deadline || "")}</td>
          <td>
            <div class="row-actions">
              <button class="button small ghost" type="button" onclick="editJob(${job.id})">Edit</button>
              <button class="button small ghost" type="button" onclick="generateForJob(${job.id})">Tailor</button>
              <button class="button small ghost" type="button" onclick="followUp(${job.id})">Follow-up</button>
              <button class="button small ghost danger" type="button" onclick="deleteJob(${job.id})">Delete</button>
            </div>
          </td>
        </tr>
      `
    )
    .join("");
}

function sortJobs(jobs, sortBy) {
  const copy = [...jobs];
  const salaryNumber = (job) => Math.max(0, ...String(job.salary || "").match(/\d+/g)?.map(Number) || [0]);
  if (sortBy === "salary") return copy.sort((a, b) => salaryNumber(b) - salaryNumber(a));
  if (sortBy === "distance") return copy.sort((a, b) => Number(a.distance_km || 999999) - Number(b.distance_km || 999999));
  if (sortBy === "posted") return copy.sort((a, b) => String(b.posted_date || "").localeCompare(String(a.posted_date || "")));
  if (sortBy === "discovered") return copy.sort((a, b) => String(b.discovery_first_seen_at || b.date_added || "").localeCompare(String(a.discovery_first_seen_at || a.date_added || "")));
  if (sortBy === "deadline") return copy.sort((a, b) => String(a.deadline || "9999").localeCompare(String(b.deadline || "9999")));
  if (sortBy === "location") return copy.sort((a, b) => String(a.location || "").localeCompare(String(b.location || "")));
  if (sortBy === "date") return copy.sort((a, b) => String(b.date_added || "").localeCompare(String(a.date_added || "")));
  return copy.sort((a, b) => Number(b.fit_score || 0) - Number(a.fit_score || 0));
}

function miniBreakdown(job) {
  return [
    `skills ${job.skills_match_score || 0}`,
    `role ${job.role_match_score || 0}`,
    `loc ${job.location_score || 0}`,
    `salary ${job.salary_score || 0}`,
  ].join(" | ");
}

function riskLabel(job) {
  const coding = Number(job.coding_risk_score || 100);
  const effort = Number(job.application_effort_score || 100);
  if (coding < 60) return `<span class="risk high">High coding</span>`;
  if (effort < 70) return `<span class="risk medium">High effort</span>`;
  return `<span class="risk low">Low</span>`;
}

function scorePill(score) {
  return `<span class="score">${Number(score || 0)}</span>`;
}

function linkFor(url) {
  if (!url) return "";
  return `<a href="${escapeAttribute(url)}" target="_blank" rel="noreferrer">Posting</a>`;
}

function getPayload() {
  return {
    id: value("job-id"),
    company: value("company"),
    title: value("title"),
    location: value("location"),
    url: value("url"),
    application_url: value("application-url"),
    source: value("source"),
    salary: value("salary"),
    deadline: value("deadline"),
    remote_type: value("remote-type"),
    role_type: value("role-type"),
    seniority_level: value("seniority-level"),
    status: value("status"),
    date_applied: value("date-applied"),
    fit_score: value("fit-score"),
    required_skills: value("required-skills"),
    preferred_skills: value("preferred-skills"),
    responsibilities: value("responsibilities"),
    notes: value("notes"),
    job_description: value("job-description"),
  };
}

function getProfilePayload() {
  const payload = {};
  profileFields.forEach((field) => {
    payload[toSnake(field)] = value(`profile-${field}`);
  });
  return payload;
}

async function saveJob(event) {
  event.preventDefault();
  try {
    const id = value("job-id");
    const payload = getPayload();
    const saved = id ? await api.send(`/api/jobs/${id}`, "PUT", payload) : await api.send("/api/jobs", "POST", payload);
    state.activeJobId = saved.id;
    fillJobForm(saved);
    renderScore(saved);
    toast(`${saved.company || "Job"} saved`);
    await loadAll();
  } catch (error) {
    toast(error.message);
  }
}

async function submitProfileSave(successMessage = "Profile saved") {
  try {
    state.profile = await api.send("/api/profile", "POST", getProfilePayload());
    try {
      renderOllamaHealth(await api.get("/api/ollama/health"));
    } catch (healthError) {
      renderOllamaHealth({ status: "error", summary: healthError.message, failure_reason: healthError.message });
    }
    state.evidence = await api.get("/api/evidence").catch(() => state.evidence);
    renderEvidenceLibrary(state.evidence);
    renderProfileLocationStatus(state.profile);
    renderDiscoveryResults(state.discoveryMeta || {});
    toast(successMessage);
  } catch (error) {
    toast(error.message);
  }
}

async function saveProfile(event) {
  event.preventDefault();
  await submitProfileSave("Profile saved");
}

async function testAndSaveLocation(event) {
  event.preventDefault();
  await submitProfileSave("Location tested and saved");
}

async function reviewEvidence(id, approved) {
  try {
    await api.send(`/api/evidence/${id}/review`, "POST", { approved, review_notes: approved ? "Approved for matching" : "Rejected for matching" });
    state.evidence = await api.get("/api/evidence");
    renderEvidenceLibrary(state.evidence);
    toast("Evidence updated");
  } catch (error) {
    toast(error.message);
  }
}

async function uploadResume(event) {
  const file = event.target.files[0];
  if (!file) return;
  const data = new FormData();
  data.append("file", file);
  try {
    const result = await api.upload("/api/profile/upload", data);
    setValue("profile-resume-text", result.resume_text);
    toast("Resume text extracted");
  } catch (error) {
    toast(error.message);
  }
}

async function uploadCoverLetterTemplate(event) {
  const file = event.target.files[0];
  if (!file) return;
  const data = new FormData();
  data.append("file", file);
  data.append("template_kind", "cover_letter");
  try {
    const result = await api.upload("/api/profile/upload", data);
    setValue("profile-cover-letter-template", result.cover_letter_template || "");
    if (result.cover_letter_template_status) {
      state.profile.cover_letter_docx_template_path = result.cover_letter_docx_template_path || "";
      state.profile.cover_letter_template_status = result.cover_letter_template_status;
      renderTemplateStatus(state.profile);
    }
    toast(result.status_message || "Cover letter template uploaded");
  } catch (error) {
    toast(error.message);
  }
}

async function extractDescription() {
  const jobDescription = value("paste-description");
  if (!jobDescription) return toast("Paste a job description first");
  try {
    const details = await api.send("/api/jobs/from-description", "POST", { job_description: jobDescription, source: "Pasted description" });
    fillJobForm({ ...details, job_description: jobDescription, status: "Saved" });
    toast("Details extracted");
  } catch (error) {
    toast(error.message);
  }
}

async function extractUrl() {
  const url = value("import-url");
  if (!url) return toast("Enter a public job URL first");
  try {
    const details = await api.send("/api/jobs/from-url", "POST", { url });
    fillJobForm({ ...details, status: "Saved" });
    toast("Public URL fetched");
  } catch (error) {
    toast(error.message);
  }
}

async function generateMaterials() {
  try {
    const output = await api.send("/api/generate", "POST", getPayload());
    setValue("fit-score", output.fit_score);
    renderScore({ ...getPayload(), ...output.score_breakdown });
    state.generatedText = formatGeneratedText(output);
    renderGenerated(output);
  } catch (error) {
    toast(error.message);
  }
}

async function analyseResumeMatch() {
  try {
    const output = await api.send("/api/jobs/analyse-resume-match", "POST", getPayload());
    renderAnalysis(output);
    toast("Resume match analysed");
  } catch (error) {
    toast(error.message);
  }
}

async function generateLocalDraft() {
  const id = value("job-id");
  if (!id) return toast("Save the job first");
  try {
    const output = await api.send(`/api/jobs/${id}/tailored-draft`, "POST", {});
    state.generatedText = output.draft.text;
    document.getElementById("generated-output").classList.remove("empty");
    document.getElementById("generated-output").innerHTML = `
      <section>
        <h3>Diagnostic résumé suggestions (not an application document)</h3>
        <pre>${escapeHtml(output.draft.text)}</pre>
      </section>
    `;
    toast("Local tailored draft generated");
  } catch (error) {
    toast(error.message);
  }
}

async function rescoreCurrent() {
  const id = Number(value("job-id"));
  if (!id) return toast("Save or select a job first");
  try {
    const result = await api.send("/api/jobs/rescore", "POST", { job_ids: [id] });
    toast(`Re-scored ${result.updated} job`);
    await loadAll();
  } catch (error) {
    toast(error.message);
  }
}

async function rescoreAll() {
  try {
    const result = await api.send("/api/jobs/rescore", "POST", { job_ids: "all" });
    toast(`Re-scored ${result.updated} jobs`);
    await loadAll();
  } catch (error) {
    toast(error.message);
  }
}

function renderAnalysis(output) {
  const semantic = output.semantic_match || {};
  const seniority = output.seniority_analysis || {};
  const fit = output.seniority_fit || {};
  const direct = semantic.direct_matches || [];
  const transferable = semantic.transferable_matches || [];
  const gaps = semantic.missing_requirements || [];
  document.getElementById("generated-output").classList.remove("empty");
  document.getElementById("generated-output").innerHTML = `
    <section>
      <h3>Local resume match</h3>
      <p><strong>Model:</strong> ${escapeHtml(semantic.model || output.model || "keyword-fallback")} · ${semantic.model_available ? "semantic" : "keyword fallback"} · cache ${semantic.cache_hit ? "hit" : "miss"}</p>
      <p><strong>Seniority:</strong> ${escapeHtml(seniority.detected_level || "unknown")} · score ${Number(fit.score || 0)} · confidence ${Number(fit.confidence || 0)}</p>
      <p>${escapeHtml(fit.explanation || "")}</p>
      ${fit.management_role ? `<p class="risk high">Management warning</p>` : ""}
      ${fit.stretch_role ? `<p class="risk medium">Stretch-role warning</p>` : ""}
    </section>
    <section>
      <h3>Direct matches</h3>
      ${renderMatchList(direct)}
    </section>
    <section>
      <h3>Transferable matches</h3>
      ${renderMatchList(transferable)}
    </section>
    <section>
      <h3>Gaps</h3>
      <p>${escapeHtml(gaps.join(", ") || "No required-skill gaps found.")}</p>
    </section>
  `;
}

function renderMatchList(matches) {
  if (!matches.length) return `<p class="muted">None found.</p>`;
  return matches
    .slice(0, 6)
    .map(
      (match) => `
        <div class="match-item">
          <strong>${escapeHtml(match.job_requirement)}</strong>
          <p>${escapeHtml(match.matched_resume_evidence)}</p>
          <span class="muted">${escapeHtml(match.evidence_source)} · ${Number(match.confidence || 0)} · semantic ${Number(match.semantic_similarity || 0)}</span>
        </div>
      `
    )
    .join("");
}

async function generateForJob(id) {
  const job = state.jobs.find((item) => item.id === id);
  if (!job) return;
  fillJobForm(job);
  await generateMaterials();
}

function renderGenerated(output) {
  const jobId = value("job-id");
  const review = output.tailoring_review || {};
  document.getElementById("generated-output").classList.remove("empty");
  document.getElementById("generated-output").innerHTML = `
    <section>
      <h3>Score breakdown: ${output.fit_score}</h3>
      <div class="score-grid">
        ${scoreItem("Skills", output.score_breakdown.skills_match_score)}
        ${scoreItem("Role", output.score_breakdown.role_match_score)}
        ${scoreItem("Location", output.score_breakdown.location_score)}
        ${scoreItem("Remote", output.score_breakdown.remote_score)}
        ${scoreItem("Salary", output.score_breakdown.salary_score)}
        ${scoreItem("Seniority", output.score_breakdown.seniority_score)}
        ${scoreItem("Coding risk", output.score_breakdown.coding_risk_score)}
        ${scoreItem("Effort", output.score_breakdown.application_effort_score)}
      </div>
    </section>
    <section>
      <h3>Keyword guidance</h3>
      <p><strong>Matched:</strong> ${escapeHtml(output.matched_keywords.join(", ") || "None")}</p>
      <p><strong>Supported by profile:</strong> ${escapeHtml(output.supported_keywords.join(", ") || "Add more profile detail")}</p>
      <p><strong>Truthfully add:</strong> ${escapeHtml(output.missing_keywords.join(", ") || "None found")}</p>
      <p><strong>Do not add unsupported:</strong> ${escapeHtml(output.unsupported_keywords.join(", ") || "None")}</p>
    </section>
    ${renderKeywordCoverage(output.keyword_coverage)}
    <section>
      <h3>Tailoring review</h3>
      <p><strong>Extracted phrases:</strong> ${escapeHtml((review.extracted_job_phrases || []).map((item) => item.phrase || item).join(", ") || "None")}</p>
      <p><strong>Applied resume changes:</strong> ${renderReviewItems(review.applied_resume_changes)}</p>
      <p><strong>Skipped resume changes:</strong> ${renderReviewItems(review.skipped_resume_changes)}</p>
      <p><strong>Cover-letter blocks:</strong> ${renderReviewItems(review.cover_letter_evidence_blocks)}</p>
      <details>
        <summary>Matching evidence</summary>
        ${renderReviewItems(review.matching_resume_evidence, true)}
      </details>
      <details>
        <summary>Cover letter preview</summary>
        <pre>${escapeHtml(review.final_cover_letter_preview || output.cover_letter || "")}</pre>
      </details>
    </section>
    <section>
      <h3>Diagnostic résumé suggestions (not an application document)</h3>
      ${output.local_tailored_text ? `<pre>${escapeHtml(output.local_tailored_text)}</pre>` : ""}
      <pre>${escapeHtml(output.resume_text)}</pre>
    </section>
    <section>
      <h3>Cover letter</h3>
      <textarea id="cover-letter-edit" rows="12">${escapeHtml(output.cover_letter)}</textarea>
      <div class="actions compact">
        <button class="button small ghost" type="button" onclick="copyElement('cover-letter-edit')">Copy cover letter</button>
        <button class="button small ghost" type="button" onclick="saveEditedVersion('cover_letter','cover-letter-edit')">Save version</button>
      </div>
    </section>
    <section>
      <h3>Application answers</h3>
      <textarea id="answers-edit" rows="12">${escapeHtml(answersToText(output.short_answers))}</textarea>
      <div class="actions compact">
        <button class="button small ghost" type="button" onclick="copyElement('answers-edit')">Copy answers</button>
        <button class="button small ghost" type="button" onclick="saveEditedVersion('answers','answers-edit')">Save version</button>
      </div>
    </section>
  `;
}

function scoreItem(label, value) {
  return `<div><span>${Number(value || 0)}</span><p>${escapeHtml(label)}</p></div>`;
}

function renderKeywordCoverage(report) {
  if (!report) return "";
  const score = report.keywords_score || {};
  const list = (items, empty) => Array.isArray(items) && items.length
    ? `<div class="keyword-records">${items.map((item) => {
      const keyword = item.keyword || item.normalized || item.requirement || "Keyword";
      const status = item.match_type === "equivalent" ? "Equivalent" : item.match_type === "exact" ? "Exact" : item.match_type === "related_review" ? "Related" : "Missing";
      const category = item.requirement_type || "unclassified";
      const detail = item.evidence
        ? `<div class="keyword-evidence"><strong>Found as:</strong> ${escapeHtml(item.found_as || keyword)}<br><strong>Source:</strong> ${escapeHtml(item.source_section || "Résumé")}<br><strong>Evidence:</strong> ${escapeHtml(item.evidence)}</div>`
        : `<div class="keyword-evidence muted">No résumé evidence recorded.</div>`;
      return `<details class="keyword-record"><summary><span class="keyword-chip">${escapeHtml(keyword)}</span><span class="keyword-status">${escapeHtml(status)}</span><span class="keyword-category">${escapeHtml(category)}</span></summary>${detail}</details>`;
    }).join("")}</div>`
    : `<p class="muted">${escapeHtml(empty)}</p>`;
  const eligibility = Array.isArray(report.eligibility_concerns) && report.eligibility_concerns.length
    ? `<h4>Eligibility concerns</h4>${list(report.eligibility_concerns, "None")}`
    : `<p class="muted">No nontechnical eligibility concerns.</p>`;
  const preferredScore = score.preferred && score.preferred.status === "assessed"
    ? `${Number(score.preferred.score_percent || 0)}% (${Number(score.preferred.matched || 0)}/${Number(score.preferred.total || 0)})`
    : "Not assessed";
  const scoreSection = score.total != null ? `
    <section class="keywords-score-panel">
      <h3>Keywords Score</h3>
      <p><strong>${Number(score.score_percent || 0)}%</strong> · ${Number(score.matched_count || 0)}/${Number(score.total || 0)} eligible keywords matched</p>
      <p><strong>Required (explicitly classified only):</strong> ${score.required && score.required.status === "assessed" ? `${Number(score.required.score_percent || 0)}% (${Number(score.required.matched || 0)}/${Number(score.required.total || 0)})` : "Not assessed"} · <strong>Preferred:</strong> ${preferredScore}</p>
      <p class="muted">Keywords Score measures coverage in the selected résumé. Overall Fit is a separate job prioritization metric and may use the saved active profile.</p>
      ${score.review_before_applying ? `<p class="risk medium"><strong>Review job fit</strong><br>Coverage is below the configurable ${Number(score.review_threshold_percent || 70)}% review guideline.</p>` : `<p class="muted">No keyword coverage review warning.</p>`}
      <h4>Matched</h4>${list(score.matched, "No exact or equivalent keyword matches.")}
      <h4>Related evidence for review</h4>${list(score.related, "None identified.")}
      <h4>Missing</h4>${list(score.missing, "No eligible keywords missing.")}
      <p class="muted">${escapeHtml(score.heuristic_note || "Keyword coverage is a review heuristic, not a hiring decision.")}</p>
    </section>` : "";
  return `
    ${scoreSection}
    <section>
      <h3>Nontechnical job fit</h3>
      ${eligibility}
    </section>
  `;
}

function renderReviewItems(items, includeMatch = false) {
  if (!Array.isArray(items) || !items.length) return `<span class="muted">None</span>`;
  return `
    <ul class="review-list">
      ${items
        .slice(0, 6)
        .map((item) => {
          const title = item.matched_job_phrase || item.job_phrase || item.original_text || item.section || "Item";
          const detail = includeMatch
            ? `${item.evidence_section || ""} · ${item.exact_original_resume_paragraph || item.supporting_evidence || ""}`
            : item.new_text || item.proposed_text || item.supporting_evidence || "";
          return `<li><strong>${escapeHtml(title)}</strong><div>${escapeHtml(detail)}</div></li>`;
        })
        .join("")}
    </ul>
  `;
}

function formatGeneratedText(output) {
  return [
    `Fit score: ${output.fit_score}`,
    `Matched: ${output.matched_keywords.join(", ")}`,
    `Supported: ${output.supported_keywords.join(", ")}`,
    `Truthfully add: ${output.missing_keywords.join(", ")}`,
    `Unsupported: ${output.unsupported_keywords.join(", ")}`,
    "",
    output.resume_text,
    "",
    "Cover letter:",
    output.cover_letter,
    "",
    "Application answers:",
    answersToText(output.short_answers),
  ].join("\n");
}

function answersToText(answers) {
  return answers.map((item) => `${item.question}\n${item.answer}`).join("\n\n");
}

function fillJobForm(job) {
  state.activeJobId = job.id || "";
  setValue("job-id", job.id || "");
  setValue("company", job.company);
  setValue("title", job.title);
  setValue("location", job.location);
  setValue("url", job.url);
  setValue("application-url", job.application_url);
  setValue("source", job.source);
  setValue("salary", job.salary);
  setValue("deadline", job.deadline);
  setValue("remote-type", job.remote_type);
  setValue("role-type", job.role_type || "other");
  setValue("seniority-level", job.seniority_level);
  setValue("status", job.status || "Saved");
  setValue("date-applied", job.date_applied);
  setValue("fit-score", job.fit_score || 0);
  setValue("required-skills", job.required_skills);
  setValue("preferred-skills", job.preferred_skills);
  setValue("responsibilities", job.responsibilities);
  setValue("notes", job.notes);
  setValue("job-description", job.job_description);
  renderScore(job);
  document.querySelector('[data-tab="tracker"]').click();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function renderScore(job) {
  const scoreFields = [
    "skills_match_score",
    "role_match_score",
    "location_score",
    "remote_score",
    "salary_score",
    "seniority_score",
    "coding_risk_score",
    "application_effort_score",
  ];
  scoreFields.forEach((field) => setValue(toKebab(field), job[field] || 0));
  setValue("fit-score", job.fit_score || 0);
  const breakdown = job.score_breakdown?.breakdown || job.breakdown || job.score_breakdown || {};
  const notes = breakdown.notes || [];
  document.getElementById("score-notes").innerHTML = notes.length
    ? notes.map((note) => `<div>${escapeHtml(note)}</div>`).join("")
    : "No score notes yet.";
}

function editJob(id) {
  const job = state.jobs.find((item) => item.id === id);
  if (job) fillJobForm(job);
}

async function followUp(id) {
  const job = state.jobs.find((item) => item.id === id);
  if (!job) return;
  try {
    const result = await api.send("/api/follow-up", "POST", job);
    state.generatedText = result.message;
    document.getElementById("generated-output").classList.remove("empty");
    document.getElementById("generated-output").innerHTML = `
      <section>
        <h3>Follow-up message</h3>
        <textarea id="follow-up-edit" rows="9">${escapeHtml(result.message)}</textarea>
        <div class="actions compact">
          <button class="button small ghost" type="button" onclick="copyElement('follow-up-edit')">Copy follow-up</button>
        </div>
      </section>
    `;
    document.querySelector('[data-tab="tracker"]').click();
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (error) {
    toast(error.message);
  }
}

async function deleteJob(id) {
  const job = state.jobs.find((item) => item.id === id);
  if (!job || !confirm(`Delete ${job.company} - ${job.title}?`)) return;
  try {
    await api.send(`/api/jobs/${id}`, "DELETE", {});
    toast("Job deleted");
    await loadAll();
  } catch (error) {
    toast(error.message);
  }
}

async function saveEditedVersion(kind, elementId) {
  const id = value("job-id");
  if (!id) return toast("Save the job first");
  try {
    await api.send(`/api/jobs/${id}/versions`, "POST", { kind, content: value(elementId) });
    toast("Version saved");
  } catch (error) {
    toast(error.message);
  }
}

function applyDiscoverySearchDefaults() {
  setValue("discovery-search-depth", "standard");
  setValue("discovery-date-window", "14d");
  setValue("discovery-sort-mode", "best_match");
  setValue("discovery-distance", "");
  setValue("discovery-per-source-cap", 100);
  setValue("discovery-total-cap", 200);
  setChecked("discovery-bypass-cache", false);
}

function syncDiscoveryDepthDefaults() {
  const depth = value("discovery-search-depth") || "standard";
  const preset = {
    quick: { date_window: "3d", per_source_cap: 25, total_cap: 50 },
    standard: { date_window: "14d", per_source_cap: 100, total_cap: 200 },
    thorough: { date_window: "30d", per_source_cap: 250, total_cap: 500 },
  }[depth] || { date_window: "14d", per_source_cap: 100, total_cap: 200 };
  setValue("discovery-date-window", preset.date_window);
  setValue("discovery-per-source-cap", preset.per_source_cap);
  setValue("discovery-total-cap", preset.total_cap);
}

function discoverySearchCriteriaFromControls() {
  return {
    keywords: value("discovery-keywords"),
    location: value("discovery-location"),
    enabled_sources: selectedDiscoverySources(),
    remote_preference: value("discovery-remote-preference"),
    distance: value("discovery-distance"),
    search_depth: value("discovery-search-depth") || "standard",
    date_window: value("discovery-date-window") || "14d",
    per_source_cap: value("discovery-per-source-cap") || 100,
    total_cap: value("discovery-total-cap") || 200,
    bypass_cache: checked("discovery-bypass-cache"),
  };
}

function setDiscoveryControlsEnabled(enabled) {
  ["discovery-sort-mode", "discovery-filter-toggle", "discovery-clear-filters", "discovery-show-all", "discovery-view-cards", "discovery-view-table"].forEach((id) => {
    const element = document.getElementById(id);
    if (element) element.disabled = !enabled;
  });
  const filterPanel = document.getElementById("discovery-filter-panel");
  if (!enabled && filterPanel) filterPanel.hidden = true;
  updateDiscoveryFilterToggleLabel();
}

function discoverySortPreferencesFromMode(mode) {
  const sortMode = mode || "best_match";
  const sortMap = {
    best_match: { field: "overall_score", direction: "desc" },
    overall_score: { field: "overall_score", direction: "desc" },
    salary_desc: { field: "salary", direction: "desc", unknown_salary_position: "last" },
    salary_asc: { field: "salary", direction: "asc", unknown_salary_position: "last" },
    distance: { field: "distance", direction: "asc", remote_rule: "remote_after_local" },
    posted_date: { field: "posted_date", direction: "desc" },
    company: { field: "company", direction: "asc" },
  };
  return {
    field: "overall_score",
    direction: "desc",
    secondary_field: "",
    secondary_direction: "asc",
    unknown_salary_position: "last",
    remote_rule: "remote_after_local",
    ...(sortMap[sortMode] || sortMap.best_match),
  };
}

function discoverySortModeFromPreferences(sort = {}) {
  const field = sort.field || "overall_score";
  const direction = sort.direction || "desc";
  if (field === "salary" && direction === "asc") return "salary_asc";
  if (field === "salary" && direction === "desc") return "salary_desc";
  if (field === "distance" && direction === "asc") return "distance";
  if (field === "posted_date" && direction === "desc") return "posted_date";
  if (field === "company" && direction === "asc") return "company";
  if (field === "overall_score" && direction === "desc") return "overall_score";
  return "best_match";
}

function discoveryPreferencesFromControls() {
  return {
    sort: discoverySortPreferencesFromMode(value("discovery-sort-mode")),
    filters: {
      salary_min: value("discovery-filter-salary-min"),
      max_distance: value("discovery-filter-max-distance"),
      overall_score_min: value("discovery-filter-overall-score-min"),
      posted_within: value("discovery-filter-posted-within"),
      remote_type: value("discovery-filter-remote"),
      source: value("discovery-filter-source"),
      job_field: value("discovery-filter-job-field"),
      seniority: value("discovery-filter-seniority"),
      known_salary_only: checked("discovery-filter-known-salary"),
      known_location_only: checked("discovery-filter-known-location"),
      exact_date_only: checked("discovery-filter-exact-date"),
      company: value("discovery-filter-company"),
      title_keywords: value("discovery-filter-title-keywords"),
    },
  };
}

function applyDiscoveryPreferencesToControls(preferences = {}) {
  const sort = preferences.sort || {};
  const filters = preferences.filters || {};
  setValue("discovery-sort-mode", discoverySortModeFromPreferences(sort));
  setValue("discovery-filter-salary-min", filters.salary_min || "");
  setValue("discovery-filter-max-distance", filters.max_distance || "");
  setValue("discovery-filter-overall-score-min", filters.overall_score_min || "");
  setValue("discovery-filter-posted-within", filters.posted_within || "");
  setValue("discovery-filter-remote", filters.remote_type || "");
  setValue("discovery-filter-source", filters.source || "");
  setValue("discovery-filter-job-field", filters.job_field || "");
  setValue("discovery-filter-seniority", filters.seniority || "");
  setChecked("discovery-filter-known-salary", Boolean(filters.known_salary_only));
  setChecked("discovery-filter-known-location", Boolean(filters.known_location_only));
  setChecked("discovery-filter-exact-date", Boolean(filters.exact_date_only));
  setValue("discovery-filter-company", filters.company || "");
  setValue("discovery-filter-title-keywords", filters.title_keywords || "");
  updateDiscoveryFilterToggleLabel();
}

function updateDiscoveryFilterToggleLabel() {
  const button = document.getElementById("discovery-filter-toggle");
  if (!button) return;
  const filters = discoveryPreferencesFromControls().filters || {};
  const count = [
    filters.salary_min,
    filters.max_distance,
    filters.overall_score_min,
    filters.posted_within,
    filters.remote_type,
    filters.source,
    filters.job_field,
    filters.seniority,
    filters.known_salary_only,
    filters.known_location_only,
    filters.exact_date_only,
    filters.company,
    filters.title_keywords,
  ].filter((value) => value !== "" && value !== false && value != null).length;
  button.textContent = count ? `Filter (${count})` : "Filter";
}

function toggleDiscoveryFilters() {
  const panel = document.getElementById("discovery-filter-panel");
  if (!panel) return;
  panel.hidden = !panel.hidden;
  updateDiscoveryFilterToggleLabel();
}

function persistDiscoveryPreferences() {
  if (!state.discoverySearchKey) return Promise.resolve();
  return api.send("/api/discovery/preferences", "POST", {
    search_key: state.discoverySearchKey,
    preferences: discoveryPreferencesFromControls(),
  }).catch(() => null);
}

function handleDiscoveryControlsChanged() {
  state.discoveryPreferences = discoveryPreferencesFromControls();
  if (state.discoverySearchKey) persistDiscoveryPreferences();
  updateDiscoveryFilterToggleLabel();
  renderDiscoveryResults(state.discoveryMeta || {});
}

function setDiscoveryView(view) {
  state.discoveryView = view === "table" ? "table" : "cards";
  renderDiscoveryResults(state.discoveryMeta || {});
}

async function searchDiscovery(event) {
  event.preventDefault();
  const button = document.getElementById("discovery-submit");
  const status = document.getElementById("discovery-status");
  const criteria = discoverySearchCriteriaFromControls();
  button.disabled = true;
  status.textContent = `Searching jobs from ${criteria.enabled_sources.map(sourceLabel).join(", ")}...`;
  try {
    const result = await api.send("/api/discovery/jobspy", "POST", criteria);
    state.discoveryResults = result.jobs || [];
    state.discoverySearchKey = result.search_key || "";
    state.discoveryPreferences = result.preferences || discoveryPreferencesFromControls();
    state.discoverySearchCriteria = result.search || criteria;
    applyDiscoveryPreferencesToControls(state.discoveryPreferences);
    state.discoveryMeta = {
      total: result.total || 0,
      visible_total: result.visible_total || (result.jobs || []).length,
      duplicates: result.duplicates || 0,
      source_counts: result.source_counts || {},
      errors: result.errors || {},
      diagnostics: result.diagnostics || {},
      cap_reached: Boolean(result.cap_reached),
    };
    renderDiscoveryResults(state.discoveryMeta);
    if (state.discoveryResults.length) {
      document.getElementById("discovery-results").scrollIntoView({ behavior: "smooth", block: "start" });
    }
    setDiscoveryControlsEnabled(Boolean(state.discoveryResults.length));
    status.textContent = result.visible_total
      ? `Fetched ${result.total || 0} jobs and showing ${result.visible_total}.`
      : result.total
        ? `Fetched ${result.total} jobs; local filters are hiding all of them.`
        : "No jobs were fetched from the selected sources.";
  } catch (error) {
    toast(error.message);
    status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function testJobSources(event) {
  event.preventDefault();
  const button = document.getElementById("discovery-test-sources");
  const status = document.getElementById("discovery-status");
  const output = document.getElementById("discovery-source-test-output");
  const criteria = {
    keywords: "software developer",
    location: "Toronto, ON",
    enabled_sources: selectedDiscoverySources(),
    bypass_cache: checked("discovery-bypass-cache"),
  };
  button.disabled = true;
  status.textContent = `Testing sources: ${criteria.enabled_sources.map(sourceLabel).join(", ")}...`;
  output.textContent = "";
  try {
    const result = await api.send("/api/discovery/jobspy/test-sources", "POST", criteria);
    output.innerHTML = renderSourceTestResult(result);
    status.textContent = "Source smoke test completed.";
  } catch (error) {
    output.textContent = "";
    status.textContent = error.message;
    toast(error.message);
  } finally {
    button.disabled = false;
  }
}

function selectedDiscoverySources() {
  return [...document.querySelectorAll('input[name="discovery-source"]:checked')].map((input) => input.value);
}

function sourceLabel(source) {
  return {
    linkedin: "LinkedIn",
    indeed: "Indeed",
    google: "Google Jobs",
    zip_recruiter: "ZipRecruiter",
  }[source] || source;
}

function renderSourceTestResult(result) {
  const diagnostics = result.source_diagnostics || {};
  const snapshots = result.source_snapshots || {};
  const rows = Object.entries(diagnostics).map(([source, info]) => {
    const count = Number(info?.raw_records_row_count || 0);
    const title = snapshots[source]?.[0]?.title || "No title";
    const company = snapshots[source]?.[0]?.company || "Unknown company";
    const location = snapshots[source]?.[0]?.location || "Unknown location";
    const error = info?.error ? ` — ${escapeHtml(info.error)}` : "";
    return `<li><strong>${escapeHtml(sourceLabel(source))}:</strong> ${count} raw rows; ${escapeHtml(title)} / ${escapeHtml(company)} / ${escapeHtml(location)}${error}</li>`;
  });
  return `
    <details class="score-details" open>
      <summary>Source smoke test</summary>
      <ul class="score-breakdown-list">
        <li><strong>Query:</strong> ${escapeHtml(result.keywords || "")} @ ${escapeHtml(result.location_context?.discovery_location || result.input_location || "")}</li>
        <li><strong>Raw results:</strong> ${Number(result.total || 0)}</li>
        ${rows.join("")}
      </ul>
    </details>
  `;
}

function renderDiscoveryResults(result) {
  const container = document.getElementById("discovery-results");
  container.classList.remove("empty");
  const counts = result.source_counts || state.discoveryMeta.source_counts || {};
  const errors = result.errors || state.discoveryMeta.errors || {};
  const diagnostics = result.diagnostics || state.discoveryMeta.diagnostics || {};
  const sourceDiagnostics = diagnostics.source_diagnostics || {};
  const countText = Object.keys(counts).map((source) => `${sourceLabel(source)}: ${counts[source]}`).join(" | ");
  const errorText = Object.keys(errors).length
    ? `<div class="discovery-errors">${Object.entries(errors).map(([source, message]) => `<p><strong>${escapeHtml(sourceLabel(source))}:</strong> ${escapeHtml(message)}</p>`).join("")}</div>`
    : "";
  const prefs = state.discoveryPreferences || discoveryPreferencesFromControls();
  const jobs = applyDiscoveryClientFiltersAndSort(state.discoveryResults || [], prefs);
  const visibleCount = jobs.length;
  const totalCount = Number(result.total || state.discoveryMeta.total || state.discoveryResults.length || 0);
  document.getElementById("discovery-active-state").textContent = describeDiscoveryState(prefs, visibleCount, totalCount);
  renderDiscoveryOriginSummary();
  let body = state.discoveryView === "table" ? renderDiscoveryTable(jobs) : renderDiscoveryCards(jobs);
  if (visibleCount === 0 && totalCount > 0) {
    body = `<div class="empty-state">
      <p>No jobs are visible with the current filters.</p>
      <p class="muted">Raw fetches were completed, but local filters may be hiding results.</p>
      <ul class="score-breakdown-list">
        <li>Try a broader title keyword.</li>
        <li>Increase the date range.</li>
        <li>Increase the distance limit.</li>
        <li>Use a city or region instead of a postal code.</li>
      </ul>
    </div>${renderSourceDiagnostics(sourceDiagnostics)}`;
  }
  if (!hasDiscoveryOrigin() && Number(prefs.filters?.max_distance || 0) > 0) {
    body = "<p>Distance filter unavailable - save a postal code or location in Profile.</p>" + body;
  }
  const rawSummary = renderDiscoveryDiagnostics(diagnostics, visibleCount, totalCount);
  container.innerHTML = `
    <div class="discovery-summary">
      <p><strong>${totalCount}</strong> raw jobs | <strong>${Number(result.duplicates || state.discoveryMeta.duplicates || 0)}</strong> duplicates | <strong>${visibleCount}</strong> visible</p>
      <p class="muted">${escapeHtml(countText || "No source counts returned")}</p>
      ${errorText}
    </div>
    ${rawSummary}
    ${body}
  `;
}

function renderDiscoveryOriginSummary() {
  const element = document.getElementById("discovery-distance-origin");
  if (!element) return;
  const profile = state.profile || {};
  if (!hasDiscoveryOrigin()) {
    element.textContent = "Distance calculated from: not configured. Save a home postal code or location in Profile.";
    return;
  }
  const normalized = profile.home_location_normalized || profile.location || "saved location";
  const precision = profile.home_location_precision || "approximate";
  element.textContent = `Distance calculated from: ${normalized} (${precision})`;
}

function renderDiscoveryDiagnostics(diagnostics, visibleCount, totalCount) {
  if (!diagnostics || !Object.keys(diagnostics).length) return "";
  const details = [];
  const searchCriteria = diagnostics.search_criteria || state.discoverySearchCriteria || {};
  const sourceCounts = diagnostics.source_counts || {};
  const sourceErrors = diagnostics.source_errors || {};
  const sourceDiagnostics = diagnostics.source_diagnostics || {};
  const origin = diagnostics.saved_origin || {};
  const fetched = Number(diagnostics.raw_jobs_returned || totalCount || 0);
  const hiddenByLocalFilters = Math.max(0, Number(totalCount || 0) - Number(visibleCount || 0));
  const capReached = diagnostics.cap_reached ? "Yes" : "No";
  details.push(`<li><strong>Search:</strong> ${escapeHtml([
    searchCriteria.keywords ? `keywords=${searchCriteria.keywords}` : "",
    searchCriteria.location ? `location=${searchCriteria.location}` : "",
    searchCriteria.search_depth ? `depth=${searchCriteria.search_depth}` : "",
    searchCriteria.date_window ? `date=${searchCriteria.date_window}` : "",
    searchCriteria.per_source_cap ? `per-source cap=${searchCriteria.per_source_cap}` : "",
    searchCriteria.total_cap ? `total cap=${searchCriteria.total_cap}` : "",
    searchCriteria.remote_preference ? `remote=${searchCriteria.remote_preference}` : "",
    searchCriteria.distance ? `radius=${searchCriteria.distance}` : "",
  ].filter(Boolean).join("; "))}</li>`);
  details.push(`<li><strong>Cache:</strong> ${escapeHtml([
    diagnostics.cache_hit === true ? "hit" : diagnostics.cache_hit === false ? "miss" : "unknown",
    diagnostics.cache_created_at ? `created=${diagnostics.cache_created_at}` : "",
    diagnostics.cached_raw_result_count !== undefined ? `cached raw=${diagnostics.cached_raw_result_count}` : "",
    diagnostics.bypass_cache ? "bypassed" : "",
  ].filter(Boolean).join("; ") || "not available")}</li>`);
  details.push(`<li><strong>Discovery location:</strong> ${escapeHtml([
    diagnostics.original_location ? `input=${diagnostics.original_location}` : "",
    diagnostics.normalized_location ? `normalized=${diagnostics.normalized_location}` : "",
    diagnostics.discovery_location ? `search=${diagnostics.discovery_location}` : "",
    diagnostics.distance_origin ? `origin=${diagnostics.distance_origin}` : "",
    diagnostics.location_resolution_method ? `method=${diagnostics.location_resolution_method}` : "",
  ].filter(Boolean).join("; ") || "not configured")}</li>`);
  details.push(`<li><strong>Origin:</strong> ${escapeHtml([
    origin.original_input ? `input=${origin.original_input}` : "",
    origin.normalized ? `normalized=${origin.normalized}` : "",
    diagnostics.origin_geocode_status ? `status=${diagnostics.origin_geocode_status}` : "",
    diagnostics.origin_precision ? `precision=${diagnostics.origin_precision}` : "",
  ].filter(Boolean).join("; ") || "not configured")}</li>`);
  details.push(`<li><strong>Raw fetched:</strong> ${fetched}</li>`);
  details.push(`<li><strong>Visible after local filters:</strong> ${Number(visibleCount || 0)}</li>`);
  details.push(`<li><strong>Hidden by local filters:</strong> ${hiddenByLocalFilters}</li>`);
  details.push(`<li><strong>Duplicates removed:</strong> ${Number(diagnostics.duplicates_removed || 0)}</li>`);
  details.push(`<li><strong>Cap reached:</strong> ${capReached}</li>`);
  details.push(`<li><strong>Geocoding:</strong> success ${Number(diagnostics.jobs_geocoded_successfully || 0)} | cached ${Number(diagnostics.jobs_using_cached_coordinates || 0)} | unknown ${Number(diagnostics.jobs_with_unknown_distance || 0)} | radius excluded ${Number(diagnostics.jobs_excluded_by_radius || 0)}</li>`);
  if (Object.keys(sourceCounts).length) {
    details.push(`<li><strong>By source:</strong> ${escapeHtml(Object.entries(sourceCounts).map(([source, count]) => `${sourceLabel(source)}=${count}`).join(" | "))}</li>`);
  }
  if (Object.keys(sourceErrors).length) {
    details.push(`<li><strong>Source errors:</strong> ${escapeHtml(Object.entries(sourceErrors).map(([source, message]) => `${sourceLabel(source)}=${message}`).join(" | "))}</li>`);
  }
  if (Object.keys(sourceDiagnostics).length) {
    details.push(`<li>${renderSourceDiagnostics(sourceDiagnostics)}</li>`);
  }
  if (Array.isArray(diagnostics.geocoding_errors) && diagnostics.geocoding_errors.length) {
    const rateLimited = diagnostics.geocoding_errors.some((error) => String(error).toLowerCase().includes("rate limited"));
    details.push(`<li><strong>Location enrichment:</strong> ${rateLimited ? "The public location service is temporarily rate limited. Jobs were kept; distance is unknown until cached data or a later retry is available." : "Some locations could not be enriched. Jobs were kept with unknown distance."}</li>`);
  }
  if (totalCount > 0 && visibleCount === 0) {
    details.push("<li><strong>Local filters:</strong> Jobs were fetched, but the current local filters hide all visible results.</li>");
  }
  return `
    <details class="score-details" open>
      <summary>Discovery diagnostics</summary>
      <ul class="score-breakdown-list">${details.join("")}</ul>
    </details>
  `;
}

function renderSourceDiagnostics(sourceDiagnostics) {
  const entries = Object.entries(sourceDiagnostics || {});
  if (!entries.length) return "";
  return `
    <details class="score-details">
      <summary>Source diagnostics</summary>
      <ul class="score-breakdown-list">
        ${entries
          .map(([source, info]) => {
            const status = info?.attempted ? (info.success ? "success" : "failed") : `skipped${info?.skipped_reason ? ` (${info.skipped_reason})` : ""}`;
            const pieces = [
              `attempted=${info?.attempted ? "yes" : "no"}`,
              `result_count=${Number(info?.result_count || 0)}`,
              `status=${status}`,
            ];
            if (info?.error) pieces.push(`error=${info.error}`);
            if (info?.duration_ms !== undefined) pieces.push(`duration=${Number(info.duration_ms)}ms`);
            if (info?.effective_country_indeed) pieces.push(`Indeed country=${info.effective_country_indeed}`);
            return `<li><strong>${escapeHtml(sourceLabel(source))}:</strong> ${escapeHtml(pieces.join("; "))}</li>`;
          })
          .join("")}
      </ul>
    </details>
  `;
}

function renderDiscoveryCards(jobs) {
  if (!jobs.length) return "<p>No live jobs are available from the selected sources.</p>";
  return jobs.map((job, index) => renderDiscoveryCard(job, index)).join("");
}

function renderDiscoveryTable(jobs) {
  if (!jobs.length) return "<p>No live jobs are available from the selected sources.</p>";
  const headers = [
    ["title", "Title"],
    ["company", "Company"],
    ["location", "Location"],
    ["distance", "Distance"],
    ["salary", "Salary"],
    ["posted_date", "Posted date"],
    ["work_arrangement", "Work arrangement"],
    ["overall_score", "Job Priority"],
    ["source", "Source"],
  ];
  return `
    <div class="table-wrap discovery-table-wrap">
      <table>
        <thead>
          <tr>
            ${headers
              .map(([field, label]) => `<th><button class="table-sort" type="button" onclick="setDiscoverySort('${field}')">${escapeHtml(label)}</button></th>`)
              .join("")}
          </tr>
        </thead>
        <tbody>
          ${jobs.map((job, index) => renderDiscoveryRow(job, index)).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderDiscoveryRow(job, index) {
  const applicationUrl = job.application_url && job.application_url !== job.url ? job.application_url : "";
  return `
    <tr>
      <td>
        <strong>${escapeHtml(job.title || "Untitled role")}</strong>
        ${renderDiscoveryWhy(job)}
      </td>
      <td>${escapeHtml(job.company || "Unknown company")}</td>
      <td>${escapeHtml(job.location || "Location unavailable")}<br><span class="muted">${escapeHtml(job.normalized_location || "")}</span></td>
      <td>${escapeHtml(distanceBadge(job))}</td>
      <td>${escapeHtml(job.salary || "Salary unavailable")}</td>
      <td>${escapeHtml(job.posted_date || "Unknown")}</td>
      <td>${escapeHtml(job.work_arrangement || job.remote_type || "Unknown")}</td>
      <td><strong>Job Priority</strong><br>${scorePill(job.overall_score || job.fit_score || 0)}</td>
      <td>${escapeHtml(job.source || "JobSpy")}</td>
    </tr>
    <tr>
      <td colspan="9">
        <div class="row-actions">
          <button class="button small" type="button" onclick="saveDiscoveryJob(${index})">Save to shortlist</button>
          <button class="button small ghost" type="button" onclick="hideDiscoveryJob(${index})">Ignore</button>
          ${job.url ? `<a class="button small ghost" href="${escapeAttribute(job.url)}" target="_blank" rel="noreferrer">Open job</a>` : ""}
          ${applicationUrl ? `<a class="button small ghost" href="${escapeAttribute(applicationUrl)}" target="_blank" rel="noreferrer">Application</a>` : ""}
        </div>
      </td>
    </tr>
  `;
}

function renderDiscoveryCard(job, index) {
  const applicationUrl = job.application_url && job.application_url !== job.url ? job.application_url : "";
  const warnings = job.warnings?.length
    ? `<div class="warning-list">${job.warnings.map((warning) => `<span>${escapeHtml(warning)}</span>`).join("")}</div>`
    : "";
  const savedStatus = String(job.saved_job_status || job.status || "").toLowerCase();
  const alreadySaved = Boolean(job.already_saved || savedStatus);
  const buttonLabel = alreadySaved && savedStatus !== "shortlisted" ? "Add to shortlist again" : alreadySaved ? "Shortlisted" : "Save to shortlist";
  const buttonDisabled = alreadySaved && savedStatus === "shortlisted" ? "disabled" : "";
  const saved = alreadySaved ? `<span class="risk low">${escapeHtml(job.saved_job_status || job.status || "Saved")}</span>` : "";
  return `
    <section class="discovery-card" data-index="${index}">
      <div class="discovery-card-main">
        <div>
          <h3>${escapeHtml(job.title || "Untitled role")}</h3>
          <p><strong>${escapeHtml(job.company || "Unknown company")}</strong> · ${escapeHtml(job.location || "Location unavailable")}</p>
          <p class="muted">${escapeHtml(job.source || "JobSpy")} · ${escapeHtml(job.work_arrangement || job.remote_type || "Remote unspecified")} · ${escapeHtml(job.salary || "Salary unavailable")} · Posted ${escapeHtml(job.posted_date || "unknown")}</p>
          <p class="muted">Normalized location: ${escapeHtml(job.normalized_location || "Unavailable")} · ${escapeHtml(distanceBadge(job))}</p>
          <div class="badge-row">
            ${badge("Distance", distanceBadge(job))}
            ${badge("Salary", job.salary || "Unavailable")}
            ${badge("Job Priority", Number(job.overall_score || job.fit_score || 0))}
            ${badge("Match", Number(job.match_score || 0))}
            ${badge("Source", job.source || "JobSpy")}
            ${badge("Posted", job.posted_date || "Unknown")}
            ${badge("Work", job.work_arrangement || job.remote_type || "Unknown")}
          </div>
        </div>
        <div><strong>Job Priority</strong><br>${scorePill(job.overall_score || job.fit_score || 0)}${saved}</div>
      </div>
      ${warnings}
      <div class="mini-breakdown">${miniBreakdown(job)}</div>
      ${renderDiscoveryWhy(job)}
      <div class="row-actions">
        <button class="button small" type="button" onclick="saveDiscoveryJob(${index})" ${buttonDisabled}>${buttonLabel}</button>
        <button class="button small ghost" type="button" onclick="hideDiscoveryJob(${index})">Ignore</button>
        ${job.url ? `<a class="button small ghost" href="${escapeAttribute(job.url)}" target="_blank" rel="noreferrer">Open job</a>` : ""}
        ${applicationUrl ? `<a class="button small ghost" href="${escapeAttribute(applicationUrl)}" target="_blank" rel="noreferrer">Application</a>` : ""}
      </div>
    </section>
  `;
}

function badge(label, value) {
  const rendered = value === undefined || value === null ? "" : String(value);
  return `<span class="badge"><strong>${escapeHtml(label)}:</strong> ${escapeHtml(rendered)}</span>`;
}

function distanceBadge(job) {
  if (job.distance_label === "remote") return "Remote";
  if (job.distance_km === undefined || job.distance_km === null) return "Unknown";
  if (Number(job.distance_km) >= 9999) return "Unknown";
  return job.distance_note ? `${job.distance_note} · ${Number(job.distance_km)} km` : `${Number(job.distance_km)} km`;
}

function describeDiscoveryState(preferences, visibleCount, totalCount) {
  const sort = preferences.sort || {};
  const filters = preferences.filters || {};
  const parts = [`Sort: ${labelDiscoveryField(sort.field || "overall_score")} ${sort.direction === "asc" ? "ascending" : "descending"}`];
  if (sort.secondary_field) {
    parts.push(`Then ${labelDiscoveryField(sort.secondary_field)} ${sort.secondary_direction === "desc" ? "descending" : "ascending"}`);
  }
  const activeFilters = [];
  if (filters.salary_min) activeFilters.push(`salary >= ${filters.salary_min}`);
  if (filters.max_distance) activeFilters.push(`distance <= ${filters.max_distance} km`);
  if (filters.overall_score_min) activeFilters.push(`score >= ${filters.overall_score_min}`);
  if (filters.posted_within) activeFilters.push(`posted within ${filters.posted_within} days`);
  if (filters.remote_type) activeFilters.push(filters.remote_type);
  if (filters.source) activeFilters.push(filters.source);
  if (filters.job_field) activeFilters.push(filters.job_field);
  if (filters.seniority) activeFilters.push(filters.seniority);
  if (filters.company) activeFilters.push(filters.company);
  if (filters.title_keywords) activeFilters.push(filters.title_keywords);
  if (filters.known_salary_only) activeFilters.push("known salary only");
  if (filters.known_location_only) activeFilters.push("known location only");
  if (filters.exact_date_only) activeFilters.push("exact date only");
  parts.push(activeFilters.length ? `Filters: ${activeFilters.join("; ")}` : "Filters: none");
  parts.push(`${visibleCount}/${totalCount} visible`);
  return parts.join(" | ");
}

function labelDiscoveryField(field) {
  return {
    overall_score: "Overall score",
    salary: "Salary",
    distance: "Distance",
    posted_date: "Posted date",
    company: "Company",
    title: "Job title",
    source: "Source",
    work_arrangement: "Work arrangement",
    seniority: "Experience level",
    match_score: "Match score",
    deadline: "Deadline",
  }[field] || field;
}

function discoveryFieldValue(job, field, preferences) {
  const salaryKnown = Number(job.salary_listed || 0) > 0;
  const salaryValue = Number(job.salary_midpoint || job.salary_max || job.salary_min || 0);
  const distanceValue = Number(job.distance_km || 9999);
  const distanceConfidence = Number(job.distance_confidence || 0);
  const remoteRule = preferences?.sort?.remote_rule || "remote_after_local";
  const unknownSalaryPosition = preferences?.sort?.unknown_salary_position || "last";
  const remoteLabel = job.work_arrangement || job.remote_type || "";
  switch (field) {
    case "salary":
      return salaryKnown ? [0, salaryValue] : [unknownSalaryPosition === "first" ? -1 : 1, 0];
    case "distance":
      if (String(remoteLabel).toLowerCase().includes("remote")) {
        if (remoteRule === "remote_first") return [0, -1, -distanceConfidence];
        if (remoteRule === "remote_zero") return [0, 0, -distanceConfidence];
        return [1, 9999, -distanceConfidence];
      }
      return [distanceValue >= 9999 ? 1 : 0, distanceValue, -distanceConfidence];
    case "posted_date":
      return [job.posted_date || "9999-12-31"];
    case "company":
      return [String(job.company || "").toLowerCase()];
    case "title":
      return [String(job.title || "").toLowerCase()];
    case "source":
      return [String(job.source || "").toLowerCase()];
    case "work_arrangement":
      return [String(job.work_arrangement || job.remote_type || "Unknown").toLowerCase()];
    case "seniority":
      return [String(job.seniority_level || "").toLowerCase()];
    case "match_score":
      return [Number(job.match_score || job.overall_score || 0)];
    case "deadline":
      return [job.deadline || "9999-12-31"];
    case "overall_score":
    default:
      return [Number(job.overall_score || job.fit_score || 0)];
  }
}

function compareDiscoveryValues(aValue, bValue, direction) {
  const asc = direction !== "desc";
  const maxLength = Math.max(aValue.length, bValue.length);
  for (let i = 0; i < maxLength; i += 1) {
    const a = aValue[i];
    const b = bValue[i];
    if (a === b) continue;
    if (a == null) return asc ? 1 : -1;
    if (b == null) return asc ? -1 : 1;
    if (typeof a === "number" && typeof b === "number") return asc ? a - b : b - a;
    const comparison = String(a).localeCompare(String(b));
    return asc ? comparison : -comparison;
  }
  return 0;
}

function compareDiscoveryJobs(a, b, preferences) {
  const sort = preferences?.sort || {};
  const primary = sort.field || "overall_score";
  const secondary = sort.secondary_field || "";
  const primaryDirection = sort.direction || "desc";
  const secondaryDirection = sort.secondary_direction || "asc";
  const primaryDiff = compareDiscoveryValues(discoveryFieldValue(a, primary, preferences), discoveryFieldValue(b, primary, preferences), primaryDirection);
  if (primaryDiff !== 0) return primaryDiff;
  if (secondary) {
    const secondaryDiff = compareDiscoveryValues(discoveryFieldValue(a, secondary, preferences), discoveryFieldValue(b, secondary, preferences), secondaryDirection);
    if (secondaryDiff !== 0) return secondaryDiff;
  }
  return String(a.company || "").localeCompare(String(b.company || "")) || String(a.title || "").localeCompare(String(b.title || ""));
}

function passesDiscoveryFilters(job, filters = {}) {
  if (filters.salary_min && Number(job.salary_max || 0) < Number(filters.salary_min)) return false;
  if (filters.max_distance && Number(job.distance_km || 9999) > Number(filters.max_distance)) return false;
  if (filters.overall_score_min && Number(job.overall_score || 0) < Number(filters.overall_score_min)) return false;
  if (filters.posted_within) {
    const posted = job.posted_date ? new Date(job.posted_date) : null;
    if (!posted || Number.isNaN(posted.getTime())) return false;
    const days = Math.floor((Date.now() - posted.getTime()) / 86400000);
    if (days > Number(filters.posted_within)) return false;
  }
  const remoteFilter = String(filters.remote_type || "").toLowerCase();
  if (remoteFilter && remoteFilter !== "any") {
    const arrangement = String(job.work_arrangement || job.remote_type || "").toLowerCase();
    if (!arrangement.includes(remoteFilter.toLowerCase())) return false;
  }
  const source = String(filters.source || "").toLowerCase();
  if (source && source !== "any" && !String(job.source || "").toLowerCase().includes(source)) return false;
  const jobField = String(filters.job_field || "").toLowerCase();
  if (jobField && !`${job.title || ""} ${job.job_description || ""} ${job.required_skills || ""} ${job.preferred_skills || ""}`.toLowerCase().includes(jobField)) return false;
  const seniority = String(filters.seniority || "").toLowerCase();
  if (seniority && seniority !== "any" && !String(job.seniority_level || "").toLowerCase().includes(seniority)) return false;
  if (filters.known_salary_only && !Number(job.salary_listed || 0)) return false;
  if (filters.known_location_only && !String(job.location || "").trim()) return false;
  if (filters.exact_date_only && !String(job.posted_date || "").trim()) return false;
  const company = String(filters.company || "").toLowerCase();
  if (company && !String(job.company || "").toLowerCase().includes(company)) return false;
  const titleKeywords = String(filters.title_keywords || "").toLowerCase();
  if (titleKeywords && !String(job.title || "").toLowerCase().includes(titleKeywords)) return false;
  return true;
}

function applyDiscoveryClientFiltersAndSort(jobs, preferences = {}) {
  const filtered = (jobs || []).filter((job) => !job.hidden && passesDiscoveryFilters(job, preferences.filters || {}));
  return filtered.sort((a, b) => compareDiscoveryJobs(a, b, preferences));
}

function renderDiscoveryWhy(job) {
  const breakdown = job.score_breakdown || {};
  const components = Array.isArray(breakdown.components) ? breakdown.components : [];
  const penalties = Array.isArray(breakdown.penalties) ? breakdown.penalties : [];
  const total = Number(breakdown.overall_score || job.overall_score || 0);
  const lines = [
    ...components.map((item) => `<li>${escapeHtml(item.label || "Component")}: ${Number(item.score || 0)}/${Number(item.max || 0)}</li>`),
    ...penalties.map((item) => `<li class="risk medium">${escapeHtml(item.label || "Penalty")}: -${Number(item.points || 0)} (${escapeHtml((item.items || []).join(", ") || "")})</li>`),
    `<li><strong>Total: ${total}/100</strong></li>`,
  ];
  return `
    <details class="score-details">
      <summary>Why this score?</summary>
      <ul class="score-breakdown-list">${lines.join("")}</ul>
    </details>
  `;
}

function setDiscoverySort(field) {
  const current = value("discovery-sort-mode") || "best_match";
  const next = {
    salary: current === "salary_desc" ? "salary_asc" : "salary_desc",
    distance: "distance",
    posted_date: "posted_date",
    company: "company",
    overall_score: "overall_score",
  }[field] || "best_match";
  setValue("discovery-sort-mode", next);
  handleDiscoveryControlsChanged();
}

function clearDiscoveryFilters() {
  [
    "discovery-filter-salary-min",
    "discovery-filter-max-distance",
    "discovery-filter-overall-score-min",
    "discovery-filter-posted-within",
    "discovery-filter-remote",
    "discovery-filter-source",
    "discovery-filter-job-field",
    "discovery-filter-seniority",
    "discovery-filter-company",
    "discovery-filter-title-keywords",
  ].forEach((id) => setValue(id, ""));
  setChecked("discovery-filter-known-salary", false);
  setChecked("discovery-filter-known-location", false);
  setChecked("discovery-filter-exact-date", false);
  const panel = document.getElementById("discovery-filter-panel");
  if (panel) panel.hidden = true;
  handleDiscoveryControlsChanged();
}

function resetDiscoverySorting() {
  setValue("discovery-sort-mode", "best_match");
  handleDiscoveryControlsChanged();
}

function showAllFetchedDiscoveryJobs() {
  state.discoveryResults = state.discoveryResults.map((job) => ({ ...job, hidden: false }));
  clearDiscoveryFilters();
  resetDiscoverySorting();
  const panel = document.getElementById("discovery-filter-panel");
  if (panel) panel.hidden = true;
  handleDiscoveryControlsChanged();
}

async function saveDiscoveryJob(index) {
  const job = state.discoveryResults[index];
  if (!job) return;
  if (String(job.saved_job_status || job.status || "").toLowerCase() === "shortlisted") return;
  try {
    const saved = await api.send("/api/shortlist", "POST", job);
    job.already_saved = true;
    job.id = saved.id;
    job.saved_job_status = saved.status || job.saved_job_status || job.status || "shortlisted";
    toast(saved.restored ? "Restored to shortlist" : saved.duplicate ? "Already shortlisted" : `${saved.company || "Job"} shortlisted`);
    await loadAll();
    document.querySelector('[data-tab="shortlist"]').click();
    renderDiscoveryResults({
      jobs: state.discoveryResults,
      total: state.discoveryResults.filter((item) => !item.hidden).length,
      duplicates: state.discoveryResults.filter((item) => item.already_saved).length,
      source_counts: countDiscoverySources(state.discoveryResults),
      errors: {},
    });
  } catch (error) {
    toast(error.message);
  }
}

function renderShortlist() {
  const container = document.getElementById("shortlist-results");
  if (!state.shortlist.length) {
    container.classList.add("empty");
    container.innerHTML = "Shortlisted jobs will appear here.";
    return;
  }
  container.classList.remove("empty");
  container.innerHTML = state.shortlist.map(renderShortlistCard).join("");
}

async function refreshShortlistKeywordScores() {
  await Promise.all(state.shortlist.map(async (job) => {
    const selection = generationSelection(job.id);
    selection.keywordScoreLoading = true;
    selection.keywordScoreError = "";
    try {
      const result = await api.send(`/api/shortlist/${job.id}/keyword-score`, "POST", generationPayload(job.id));
      selection.keywordScore = result.keywords_score || null;
    } catch (error) {
      selection.keywordScore = null;
      selection.keywordScoreError = error.message;
    } finally {
      selection.keywordScoreLoading = false;
    }
  }));
  renderShortlist();
}

async function hydrateGenerationSelections() {
  await Promise.all(state.shortlist.map(async (job) => {
    const selection = generationSelection(job.id);
    if (!selection.profileId || selection.documents.resumes?.length || selection.documents.cover_letter_templates?.length) return;
    try {
      selection.documents = await api.get(`/api/candidate-profiles/${selection.profileId}/documents`);
      selection.resumeId = String(selection.documents.resumes?.find((item) => item.is_default)?.id || selection.documents.resumes?.[0]?.id || "");
      selection.coverLetterTemplateId = String(selection.documents.cover_letter_templates?.find((item) => item.is_default)?.id || selection.documents.cover_letter_templates?.[0]?.id || "");
    } catch (error) {
      // The shortlist remains usable if a candidate profile was removed while it was open.
    }
  }));
}

function renderTailoringChanges(job) {
  const changes = job.tailoring_changes || {};
  const resume = changes.resume || {};
  const cover = changes.cover_letter || {};
  const renderEntries = (label, changeLog) => {
    const applied = Array.isArray(changeLog.applied) ? changeLog.applied : [];
    const summary = changeLog.summary || {};
    const templateMode = changeLog.template_mode ? `<span class="muted">${escapeHtml(changeLog.template_mode)}</span>` : "";
    if (!applied.length) {
      return `<div><strong>${escapeHtml(label)}</strong>${templateMode ? ` ${templateMode}` : ""}<p class="muted">No applied changes recorded yet.</p></div>`;
    }
    const items = applied
      .slice(0, 3)
      .map(
        (item) => `
          <li>
            <strong>${escapeHtml(item.matched_job_requirement || item.kind || "Tailored change")}</strong>
            <div>${escapeHtml(item.replacement || item.original || "")}</div>
            ${item.supporting_evidence ? `<div class="muted">${escapeHtml(item.supporting_evidence)}</div>` : ""}
          </li>
        `,
      )
      .join("");
    const appliedCount = Number(summary.total_applied_changes || applied.length || 0);
    return `
      <div>
        <strong>${escapeHtml(label)}</strong> ${templateMode} <span class="muted">${appliedCount} applied change${appliedCount === 1 ? "" : "s"}</span>
        <ul class="warning-list">${items}</ul>
      </div>
    `;
  };
  return `
    <details class="score-details" open>
      <summary>Tailoring changes</summary>
      <div class="note-list">
        ${renderEntries("Resume", resume)}
        ${renderEntries("Cover letter", cover)}
      </div>
    </details>
  `;
}

async function markShortlistApplied(id) {
  try {
    await api.send(`/api/shortlist/${id}/applied`, "POST", {});
    toast("Marked applied");
    await loadAll();
  } catch (error) {
    toast(error.message);
  }
}

async function removeShortlist(id) {
  try {
    await api.send(`/api/shortlist/${id}`, "DELETE", {});
    toast("Removed from shortlist");
    await loadAll();
  } catch (error) {
    toast(error.message);
  }
}

function generationSelection(jobId) {
  if (!state.generationSelections[jobId]) {
    const first = state.candidateProfiles[0];
    state.generationSelections[jobId] = { profileId: first ? String(first.id) : "", resumeId: "", coverLetterTemplateId: "", documents: { resumes: [], cover_letter_templates: [] }, keywordScore: null, keywordScoreError: "", keywordScoreLoading: false };
  }
  return state.generationSelections[jobId];
}

function generationPayload(jobId) {
  const selection = generationSelection(jobId);
  if (!selection.profileId) return {};
  return {
    candidate_profile_id: Number(selection.profileId),
    ...(selection.resumeId ? { resume_id: Number(selection.resumeId) } : {}),
    ...(selection.coverLetterTemplateId ? { cover_letter_template_id: Number(selection.coverLetterTemplateId) } : {}),
  };
}

async function selectGenerationProfile(jobId, profileId) {
  const selection = generationSelection(jobId);
  selection.profileId = String(profileId || "");
  selection.resumeId = "";
  selection.coverLetterTemplateId = "";
  selection.documents = { resumes: [], cover_letter_templates: [] };
  selection.keywordScore = null;
  if (selection.profileId) {
    try {
      selection.documents = await api.get(`/api/candidate-profiles/${selection.profileId}/documents`);
      selection.resumeId = String(selection.documents.resumes?.find((item) => item.is_default)?.id || selection.documents.resumes?.[0]?.id || "");
      selection.coverLetterTemplateId = String(selection.documents.cover_letter_templates?.find((item) => item.is_default)?.id || selection.documents.cover_letter_templates?.[0]?.id || "");
    } catch (error) {
      toast(error.message);
    }
  }
  renderShortlist();
  await refreshShortlistKeywordScores();
}

async function selectGenerationDocument(jobId, kind, value) {
  const selection = generationSelection(jobId);
  if (kind === "resume") selection.resumeId = String(value || "");
  if (kind === "cover") selection.coverLetterTemplateId = String(value || "");
  selection.keywordScore = null;
  selection.keywordScoreError = "";
  renderShortlist();
  await refreshShortlistKeywordScores();
}

async function previewShortlist(id) {
  const target = document.getElementById(`document-preview-${id}`);
  if (!target) return;
  try {
    const preview = await api.get(`/api/shortlist/${id}/preview`);
    target.classList.remove("empty");
    target.innerHTML = `<h4>Generated preview</h4><h5>Résumé</h5><pre>${escapeHtml(preview.resume || "No résumé preview is available.")}</pre><h5>Cover letter</h5><pre>${escapeHtml(preview.cover_letter || "No cover letter preview is available.")}</pre>`;
  } catch (error) {
    target.textContent = error.message;
  }
}

function documentSelectorOptions(items, selectedId, emptyLabel) {
  if (!items.length) return `<option value="">${emptyLabel}</option>`;
  return items.map((item) => `<option value="${escapeAttribute(item.id)}" ${String(item.id) === String(selectedId) ? "selected" : ""}>${escapeHtml(item.name || "Unnamed document")}</option>`).join("");
}

function renderShortlistCard(job) {
  const selection = generationSelection(job.id);
  const profileOptions = [`<option value="" ${selection.profileId ? "" : "selected"}>Use active profile</option>`, ...state.candidateProfiles.map((profile) => `<option value="${escapeAttribute(profile.id)}" ${String(profile.id) === String(selection.profileId) ? "selected" : ""}>${escapeHtml(profile.name)}</option>`)].join("");
  const resumeAvailable = Boolean(job.resume_docx_path);
  const coverAvailable = Boolean(job.cover_letter_docx_path);
  const resumeStatus = job.resume_generation_status || "pending";
  const coverStatus = job.cover_letter_generation_status || "pending";
  const resumePrevious = resumeStatus !== "generated" && resumeAvailable ? " · previous résumé available" : "";
  const coverPrevious = coverStatus !== "generated" && coverAvailable ? " · previous cover letter available" : "";
  const resumeError = job.resume_generation_error ? `<p class="risk high">Resume error: ${escapeHtml(job.resume_generation_error)}</p>` : "";
  const coverError = job.cover_letter_generation_error ? `<p class="risk high">Cover letter error: ${escapeHtml(job.cover_letter_generation_error)}</p>` : "";
  const coverWarning = job.cover_letter_generation_warning ? `<p class="warning">Cover letter warning: ${escapeHtml(job.cover_letter_generation_warning)}</p>` : "";
  const keywordScorePanel = selection.keywordScoreLoading
    ? `<section class="keywords-score-panel"><h3>Keywords Score</h3><p class="muted">Reviewing the selected résumé…</p></section>`
    : selection.keywordScoreError
      ? `<section class="keywords-score-panel"><h3>Keywords Score</h3><p class="risk medium">${escapeHtml(selection.keywordScoreError)}</p></section>`
      : selection.keywordScore
        ? renderKeywordCoverage({ keywords_score: selection.keywordScore, eligibility_concerns: [] })
        : `<section class="keywords-score-panel"><h3>Keywords Score</h3><p class="muted">Select a candidate profile and base résumé to inspect keyword coverage. This does not generate documents.</p></section>`;
  const salaryLabel = job.salary_source === "estimated" ? `${job.salary} (estimated)` : job.salary || "Salary unavailable";
  return `
    <section class="discovery-card shortlist-card">
      <div class="discovery-card-main">
        <div>
          <h3>${escapeHtml(job.title || "Untitled role")}</h3>
          <p><strong>${escapeHtml(job.company || "Unknown company")}</strong> · ${escapeHtml(job.location || "Location unavailable")}</p>
          <p class="muted">${escapeHtml(job.source || "")} · ${escapeHtml(salaryLabel)} · Shortlisted ${escapeHtml(job.date_shortlisted || job.date_added || "")}</p>
          <p class="muted">Résumé: ${escapeHtml(resumeStatus)}${resumePrevious}</p>
          ${resumeError}
          <p class="muted">Cover letter: ${escapeHtml(coverStatus)}${coverPrevious}</p>
          ${coverError}${coverWarning}
          <div class="document-selection panel nested-panel">
            <h4>Document selection</h4>
            <label>Candidate profile<select onchange="selectGenerationProfile(${job.id}, this.value)">${profileOptions}</select></label>
            <label>Base résumé<select onchange="selectGenerationDocument(${job.id}, 'resume', this.value)">${documentSelectorOptions(selection.documents.resumes || [], selection.resumeId, "Select a profile first")}</select></label>
            <label>Cover letter template<select onchange="selectGenerationDocument(${job.id}, 'cover', this.value)">${documentSelectorOptions(selection.documents.cover_letter_templates || [], selection.coverLetterTemplateId, "Select a profile first")}</select></label>
          </div>
          ${keywordScorePanel}
          <div id="document-preview-${job.id}" class="generated-output empty">Preview is available after generation.</div>
        </div>
      </div>
      <div class="row-actions">
        ${job.url ? `<a class="button small ghost" href="${escapeAttribute(job.url)}" target="_blank" rel="noreferrer">Open job</a>` : ""}
        <a class="button small ghost ${resumeAvailable ? "" : "disabled-link"}" href="/api/shortlist/${job.id}/resume">Download résumé</a>
        <a class="button small ghost ${coverAvailable ? "" : "disabled-link"}" href="/api/shortlist/${job.id}/cover-letter">Download cover letter</a>
        <button class="button small ghost" type="button" onclick="previewShortlist(${job.id})">Preview documents</button>
        <button class="button small ghost" type="button" onclick="regenerateShortlistResume(${job.id})">Regenerate résumé</button>
        <button class="button small ghost" type="button" onclick="regenerateShortlistCoverLetter(${job.id})">Regenerate cover letter</button>
        <button class="button small ghost" type="button" onclick="regenerateShortlist(${job.id})">Regenerate both</button>
        <button class="button small ghost" type="button" onclick="markShortlistApplied(${job.id})">Mark applied</button>
        <button class="button small ghost danger" type="button" onclick="removeShortlist(${job.id})">Remove</button>
      </div>
    </section>
  `;
}

async function regenerateShortlist(id) {
  try { showGenerationOutcome(await api.send(`/api/shortlist/${id}/regenerate`, "POST", generationPayload(id)), ["resume", "cover_letter"]); await loadAll(); }
  catch (error) { toast(error.message); await loadAll(); }
}

async function regenerateShortlistResume(id) {
  try { showGenerationOutcome(await api.send(`/api/shortlist/${id}/regenerate-resume`, "POST", generationPayload(id)), ["resume"]); await loadAll(); }
  catch (error) { toast(error.message); await loadAll(); }
}

async function regenerateShortlistCoverLetter(id) {
  try { showGenerationOutcome(await api.send(`/api/shortlist/${id}/regenerate-cover-letter`, "POST", generationPayload(id)), ["cover_letter"]); await loadAll(); }
  catch (error) { toast(error.message); await loadAll(); }
}

function showGenerationOutcome(result, requestedKinds) {
  const payload = result?.generation || result || {};
  const statuses = requestedKinds.map((kind) => payload[kind] || payload[`${kind}_generation_status`] || "failed");
  const generated = statuses.filter((status) => status === "generated").length;
  const previous = requestedKinds.some((kind) => Boolean(payload[`${kind === "resume" ? "resume" : "cover_letter"}_docx_path`]));
  if (generated === requestedKinds.length) {
    toast(requestedKinds.length > 1 ? "Résumé and cover letter generated" : `${requestedKinds[0] === "resume" ? "Résumé" : "Cover letter"} generated`);
  } else if (generated > 0) {
    toast(`Partial generation: ${generated}/${requestedKinds.length} document generated${previous ? "; previous successful document remains available" : ""}`);
  } else {
    toast(`Generation failed${previous ? "; previous successful document remains available" : ""}`);
  }
}

function hideDiscoveryJob(index) {
  if (!state.discoveryResults[index]) return;
  state.discoveryResults[index].hidden = true;
  renderDiscoveryResults({
    jobs: state.discoveryResults,
    total: state.discoveryResults.filter((item) => !item.hidden).length,
    duplicates: state.discoveryResults.filter((item) => item.already_saved).length,
    source_counts: countDiscoverySources(state.discoveryResults),
    errors: {},
  });
}

function countDiscoverySources(jobs) {
  return jobs.reduce((counts, job) => {
    const key = String(job.source || "jobspy").toLowerCase().replaceAll(" ", "_");
    counts[key] = (counts[key] || 0) + 1;
    return counts;
  }, {});
}

async function importCsv(event) {
  event.preventDefault();
  const file = document.getElementById("csv-file").files[0];
  if (!file) return toast("Choose a CSV file first");
  const data = new FormData();
  data.append("file", file);
  try {
    const result = await api.upload("/api/jobs/import-csv", data);
    toast(`Imported ${result.imported} jobs`);
    await loadAll();
  } catch (error) {
    toast(error.message);
  }
}

function resetForm() {
  setValue("job-id", "");
  jobFields.forEach((id) => setValue(id, ""));
  setValue("fit-score", 0);
  setValue("status", "Saved");
  setValue("role-type", "other");
  document.getElementById("score-notes").textContent = "Save or generate to calculate detailed scoring.";
}

async function copyOutput() {
  if (!state.generatedText) return toast("Nothing to copy yet");
  await navigator.clipboard.writeText(state.generatedText);
  toast("Copied");
}

async function copyElement(id) {
  await navigator.clipboard.writeText(value(id));
  toast("Copied");
}

function value(id) {
  const element = document.getElementById(id);
  if (!element) return "";
  if (element.type === "checkbox") return element.checked;
  if (element.multiple) return Array.from(element.selectedOptions).map((option) => option.value);
  return element.value.trim();
}

function setValue(id, nextValue) {
  const element = document.getElementById(id);
  if (!element) return;
  if (element.type === "checkbox") {
    element.checked = nextValue === true || String(nextValue).toLowerCase() === "true";
    return;
  }
  if (element.multiple) {
    const values = Array.isArray(nextValue) ? nextValue : String(nextValue || "").split(",");
    Array.from(element.options).forEach((option) => {
      option.selected = values.includes(option.value);
    });
    return;
  }
  element.value = nextValue || "";
}

function checked(id) {
  const element = document.getElementById(id);
  return Boolean(element && element.checked);
}

function setChecked(id, nextValue) {
  const element = document.getElementById(id);
  if (!element) return;
  element.checked = Boolean(nextValue);
}

function setText(id, nextValue) {
  document.getElementById(id).textContent = nextValue ?? "";
}

function toSnake(value) {
  return value.replaceAll("-", "_");
}

function toKebab(value) {
  return value.replaceAll("_", "-");
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttribute(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}

function toast(message) {
  const existing = document.querySelector(".toast");
  if (existing) existing.remove();
  const item = document.createElement("div");
  item.className = "toast";
  item.textContent = message;
  document.body.appendChild(item);
  setTimeout(() => item.remove(), 2600);
}
