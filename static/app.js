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
  document.getElementById("csv-import-form").addEventListener("submit", importCsv);
  document.getElementById("refresh-shortlist").addEventListener("click", loadAll);
  document.getElementById("generate").addEventListener("click", generateMaterials);
  document.getElementById("analyse-resume-match").addEventListener("click", analyseResumeMatch);
  document.getElementById("generate-local-draft").addEventListener("click", generateLocalDraft);
  document.getElementById("rescore-current").addEventListener("click", rescoreCurrent);
  document.getElementById("rescore-all").addEventListener("click", rescoreAll);
  document.getElementById("reset-form").addEventListener("click", resetForm);
  document.getElementById("copy-output").addEventListener("click", copyOutput);
  document.getElementById("extract-description").addEventListener("click", extractDescription);
  document.getElementById("extract-url").addEventListener("click", extractUrl);
  document.getElementById("resume-upload").addEventListener("change", uploadResume);
  document.getElementById("cover-letter-template-upload").addEventListener("change", uploadCoverLetterTemplate);
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
});

async function loadAll() {
  try {
    const [jobs, dashboard, profile, ollamaHealth, evidence] = await Promise.all([
      api.get("/api/jobs"),
      api.get("/api/dashboard"),
      api.get("/api/profile"),
      api.get("/api/ollama/health").catch((error) => ({ status: "error", summary: error.message })),
      api.get("/api/evidence").catch(() => []),
    ]);
    const shortlist = await api.get("/api/shortlist");
    state.jobs = jobs;
    state.profile = profile;
    state.evidence = evidence;
    state.shortlist = shortlist;
    renderDashboard(dashboard);
    renderProfile(profile);
    renderTemplateStatus(profile);
    renderOllamaHealth(ollamaHealth);
    renderEvidenceLibrary(evidence);
    renderJobs();
    renderShortlist();
  } catch (error) {
    toast(error.message);
  }
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

function renderProfile(profile) {
  profileFields.forEach((field) => setValue(`profile-${field}`, profile[toSnake(field)] || ""));
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

async function saveProfile(event) {
  event.preventDefault();
  try {
    state.profile = await api.send("/api/profile", "POST", getProfilePayload());
    try {
      renderOllamaHealth(await api.get("/api/ollama/health"));
    } catch (healthError) {
      renderOllamaHealth({ status: "error", summary: healthError.message, failure_reason: healthError.message });
    }
    state.evidence = await api.get("/api/evidence").catch(() => state.evidence);
    renderEvidenceLibrary(state.evidence);
    toast("Profile saved");
  } catch (error) {
    toast(error.message);
  }
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
        <h3>${escapeHtml(output.draft.label)}</h3>
        <pre>${escapeHtml(output.draft.text)}</pre>
        <div class="export-row">
          <a class="button small ghost" href="/export/${id}/resume.txt">Draft .txt</a>
          <a class="button small ghost" href="/export/${id}/resume.docx">Draft .docx</a>
        </div>
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
  const exportLinks = jobId
    ? `<div class="export-row">
        <a class="button small ghost" href="/export/${jobId}/cover_letter.txt">Cover .txt</a>
        <a class="button small ghost" href="/export/${jobId}/cover_letter.docx">Cover .docx</a>
        <a class="button small ghost" href="/export/${jobId}/resume.txt">Resume .txt</a>
        <a class="button small ghost" href="/export/${jobId}/resume.docx">Resume .docx</a>
      </div>`
    : `<p class="muted">Save the job first to enable version history and document exports.</p>`;
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
      <h3>Resume suggestions</h3>
      ${output.local_tailored_text ? `<pre>${escapeHtml(output.local_tailored_text)}</pre>` : ""}
      <pre>${escapeHtml(output.resume_text)}</pre>
      ${exportLinks}
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

function renderDiscoveryResults(result) {
  const container = document.getElementById("discovery-results");
  container.classList.remove("empty");
  const counts = result.source_counts || state.discoveryMeta.source_counts || {};
  const errors = result.errors || state.discoveryMeta.errors || {};
  const diagnostics = result.diagnostics || state.discoveryMeta.diagnostics || {};
  const countText = Object.keys(counts).map((source) => `${sourceLabel(source)}: ${counts[source]}`).join(" | ");
  const errorText = Object.keys(errors).length
    ? `<div class="discovery-errors">${Object.entries(errors).map(([source, message]) => `<p><strong>${escapeHtml(sourceLabel(source))}:</strong> ${escapeHtml(message)}</p>`).join("")}</div>`
    : "";
  const prefs = state.discoveryPreferences || discoveryPreferencesFromControls();
  const jobs = applyDiscoveryClientFiltersAndSort(state.discoveryResults || [], prefs);
  const visibleCount = jobs.length;
  const totalCount = Number(result.total || state.discoveryMeta.total || state.discoveryResults.length || 0);
  document.getElementById("discovery-active-state").textContent = describeDiscoveryState(prefs, visibleCount, totalCount);
  let body = state.discoveryView === "table" ? renderDiscoveryTable(jobs) : renderDiscoveryCards(jobs);
  if (visibleCount === 0 && totalCount > 0) {
    body = "<p>No jobs are visible with the current filters. Clear filters to show the fetched results.</p>";
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

function renderDiscoveryDiagnostics(diagnostics, visibleCount, totalCount) {
  if (!diagnostics || !Object.keys(diagnostics).length) return "";
  const details = [];
  const searchCriteria = diagnostics.search_criteria || state.discoverySearchCriteria || {};
  const sourceCounts = diagnostics.source_counts || {};
  const sourceErrors = diagnostics.source_errors || {};
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
  ].filter(Boolean).join("; "))}</li>`);
  details.push(`<li><strong>Raw fetched:</strong> ${fetched}</li>`);
  details.push(`<li><strong>Visible after local filters:</strong> ${Number(visibleCount || 0)}</li>`);
  details.push(`<li><strong>Hidden by local filters:</strong> ${hiddenByLocalFilters}</li>`);
  details.push(`<li><strong>Duplicates removed:</strong> ${Number(diagnostics.duplicates_removed || 0)}</li>`);
  details.push(`<li><strong>Cap reached:</strong> ${capReached}</li>`);
  if (Object.keys(sourceCounts).length) {
    details.push(`<li><strong>By source:</strong> ${escapeHtml(Object.entries(sourceCounts).map(([source, count]) => `${sourceLabel(source)}=${count}`).join(" | "))}</li>`);
  }
  if (Object.keys(sourceErrors).length) {
    details.push(`<li><strong>Source errors:</strong> ${escapeHtml(Object.entries(sourceErrors).map(([source, message]) => `${sourceLabel(source)}=${message}`).join(" | "))}</li>`);
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
          <p class="muted">${escapeHtml(job.source || "JobSpy")} · ${escapeHtml(job.remote_type || "Remote unspecified")} · ${escapeHtml(job.salary || "Salary unavailable")} · Posted ${escapeHtml(job.posted_date || "unknown")}</p>
          <p class="muted">Description: ${job.description_available ? "Yes" : "No"}</p>
        </div>
        <div>${scorePill(job.fit_score)}${saved}</div>
      </div>
      ${warnings}
      <div class="mini-breakdown">${miniBreakdown(job)}</div>
      <div class="row-actions">
        <button class="button small" type="button" onclick="saveDiscoveryJob(${index})" ${buttonDisabled}>${buttonLabel}</button>
        <button class="button small ghost" type="button" onclick="hideDiscoveryJob(${index})">Ignore</button>
        ${job.url ? `<a class="button small ghost" href="${escapeAttribute(job.url)}" target="_blank" rel="noreferrer">Open job</a>` : ""}
        ${applicationUrl ? `<a class="button small ghost" href="${escapeAttribute(applicationUrl)}" target="_blank" rel="noreferrer">Application</a>` : ""}
      </div>
    </section>
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
    ["overall_score", "Overall score"],
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
      <td>${escapeHtml(job.location || "Location unavailable")}</td>
      <td>${escapeHtml(distanceBadge(job))}</td>
      <td>${escapeHtml(job.salary || "Salary unavailable")}</td>
      <td>${escapeHtml(job.posted_date || "Unknown")}</td>
      <td>${escapeHtml(job.work_arrangement || job.remote_type || "Unknown")}</td>
      <td>${scorePill(job.overall_score || job.fit_score || 0)}</td>
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
          <p><strong>${escapeHtml(job.company || "Unknown company")}</strong> Â· ${escapeHtml(job.location || "Location unavailable")}</p>
          <p class="muted">${escapeHtml(job.source || "JobSpy")} Â· ${escapeHtml(job.work_arrangement || job.remote_type || "Remote unspecified")} Â· ${escapeHtml(job.salary || "Salary unavailable")} Â· Posted ${escapeHtml(job.posted_date || "unknown")}</p>
          <div class="badge-row">
            ${badge("Distance", distanceBadge(job))}
            ${badge("Salary", job.salary || "Unavailable")}
            ${badge("Score", Number(job.overall_score || job.fit_score || 0))}
            ${badge("Match", Number(job.match_score || 0))}
            ${badge("Source", job.source || "JobSpy")}
            ${badge("Posted", job.posted_date || "Unknown")}
            ${badge("Work", job.work_arrangement || job.remote_type || "Unknown")}
          </div>
        </div>
        <div>${scorePill(job.overall_score || job.fit_score || 0)}${saved}</div>
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
  return `${Number(job.distance_km)} km`;
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

function renderShortlistCard(job) {
  const resumeReady = job.resume_generation_status === "generated";
  const coverReady = job.cover_letter_generation_status === "generated";
  const salaryLabel = job.salary_source === "estimated" ? `${job.salary} (estimated)` : job.salary || "Salary unavailable";
  const error = job.generation_error ? `<p class="risk high">${escapeHtml(job.generation_error)}</p>` : "";
  return `
    <section class="discovery-card">
      <div class="discovery-card-main">
        <div>
          <h3>${escapeHtml(job.title || "Untitled role")}</h3>
          <p><strong>${escapeHtml(job.company || "Unknown company")}</strong> · ${escapeHtml(job.location || "Location unavailable")}</p>
          <p class="muted">${escapeHtml(job.source || "")} · ${escapeHtml(salaryLabel)} · Shortlisted ${escapeHtml(job.date_shortlisted || job.date_added || "")}</p>
          <p>${scorePill(job.fit_score)} <span class="muted">${miniBreakdown(job)}</span></p>
          <p class="muted">Resume: ${escapeHtml(job.resume_generation_status || "pending")} · Cover letter: ${escapeHtml(job.cover_letter_generation_status || "pending")}</p>
          ${error}
          ${renderTailoringChanges(job)}
        </div>
      </div>
      <div class="row-actions">
        ${job.url ? `<a class="button small ghost" href="${escapeAttribute(job.url)}" target="_blank" rel="noreferrer">Open job</a>` : ""}
        <a class="button small ghost ${resumeReady ? "" : "disabled-link"}" href="/api/shortlist/${job.id}/resume">Download resume</a>
        <a class="button small ghost ${coverReady ? "" : "disabled-link"}" href="/api/shortlist/${job.id}/cover-letter">Download cover letter</a>
        <button class="button small ghost" type="button" onclick="regenerateShortlist(${job.id})">Regenerate documents</button>
        <button class="button small ghost" type="button" onclick="markShortlistApplied(${job.id})">Mark applied</button>
        <button class="button small ghost danger" type="button" onclick="removeShortlist(${job.id})">Remove</button>
      </div>
    </section>
  `;
}

async function regenerateShortlist(id) {
  try {
    await api.send(`/api/shortlist/${id}/regenerate`, "POST", {});
    toast("Documents regenerated");
    await loadAll();
  } catch (error) {
    toast(error.message);
  }
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

function renderShortlistCard(job) {
  const resumeReady = job.resume_generation_status === "generated";
  const coverReady = job.cover_letter_generation_status === "generated";
  const salaryLabel = job.salary_source === "estimated" ? `${job.salary} (estimated)` : job.salary || "Salary unavailable";
  const resumeStatus = job.resume_generation_status || "pending";
  const coverStatus = job.cover_letter_generation_status || "pending";
  const resumeError = job.resume_generation_error ? `<p class="risk high">Resume error: ${escapeHtml(job.resume_generation_error)}</p>` : "";
  const coverError = job.cover_letter_generation_error ? `<p class="risk high">Cover letter error: ${escapeHtml(job.cover_letter_generation_error)}</p>` : "";
  const coverWarning = job.cover_letter_generation_warning ? `<p class="warning">Cover letter warning: ${escapeHtml(job.cover_letter_generation_warning)}</p>` : "";
  return `
    <section class="discovery-card">
      <div class="discovery-card-main">
        <div>
          <h3>${escapeHtml(job.title || "Untitled role")}</h3>
          <p><strong>${escapeHtml(job.company || "Unknown company")}</strong> Â· ${escapeHtml(job.location || "Location unavailable")}</p>
          <p class="muted">${escapeHtml(job.source || "")} Â· ${escapeHtml(salaryLabel)} Â· Shortlisted ${escapeHtml(job.date_shortlisted || job.date_added || "")}</p>
          <p>${scorePill(job.fit_score)} <span class="muted">${miniBreakdown(job)}</span></p>
          <p class="muted">Resume: ${escapeHtml(resumeStatus)}${resumeReady ? " (ready)" : ""}</p>
          ${resumeError}
          <p class="muted">Cover letter: ${escapeHtml(coverStatus)}${coverReady ? " (ready)" : ""}</p>
          ${coverError}
          ${coverWarning}
        </div>
      </div>
      <div class="row-actions">
        ${job.url ? `<a class="button small ghost" href="${escapeAttribute(job.url)}" target="_blank" rel="noreferrer">Open job</a>` : ""}
        <a class="button small ghost ${resumeReady ? "" : "disabled-link"}" href="/api/shortlist/${job.id}/resume">Download resume</a>
        <a class="button small ghost ${coverReady ? "" : "disabled-link"}" href="/api/shortlist/${job.id}/cover-letter">Download cover letter</a>
        <button class="button small ghost" type="button" onclick="regenerateShortlistResume(${job.id})">Regenerate resume</button>
        <button class="button small ghost" type="button" onclick="regenerateShortlistCoverLetter(${job.id})">Regenerate cover letter</button>
        <button class="button small ghost" type="button" onclick="regenerateShortlist(${job.id})">Regenerate both</button>
        <button class="button small ghost" type="button" onclick="markShortlistApplied(${job.id})">Mark applied</button>
        <button class="button small ghost danger" type="button" onclick="removeShortlist(${job.id})">Remove</button>
      </div>
    </section>
  `;
}

async function regenerateShortlist(id) {
  try {
    await api.send(`/api/shortlist/${id}/regenerate`, "POST", {});
    toast("Documents regenerated");
    await loadAll();
  } catch (error) {
    toast(error.message);
  }
}

async function regenerateShortlistResume(id) {
  try {
    await api.send(`/api/shortlist/${id}/regenerate-resume`, "POST", {});
    toast("Resume regenerated");
    await loadAll();
  } catch (error) {
    toast(error.message);
  }
}

async function regenerateShortlistCoverLetter(id) {
  try {
    await api.send(`/api/shortlist/${id}/regenerate-cover-letter`, "POST", {});
    toast("Cover letter regenerated");
    await loadAll();
  } catch (error) {
    toast(error.message);
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
