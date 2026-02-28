const API_BASE =
  window.EXPERTDB_API_BASE ||
  `${window.location.protocol}//${window.location.hostname || "localhost"}:8080`;

const SETTINGS_KEY = "expertdb_runtime_settings_v1";

const els = {
  uploadTrigger: document.getElementById("upload-trigger"),
  pdfInput: document.getElementById("pdf-input"),
  uploadMessage: document.getElementById("upload-message"),
  uploadDocId: document.getElementById("upload-doc-id"),
  uploadVersionId: document.getElementById("upload-version-id"),
  uploadObjectKey: document.getElementById("upload-object-key"),
  uploadVersionStatus: document.getElementById("upload-version-status"),
  retryFailedBtn: document.getElementById("retry-failed-btn"),
  startEvalBtn: document.getElementById("start-eval-btn"),
  searchInput: document.getElementById("search-input"),
  resultCount: document.getElementById("result-count"),
  docList: document.querySelector(".doc-list"),
  chips: Array.from(document.querySelectorAll(".chip")),
  reviewTitle: document.getElementById("review-title"),
  reviewEvidenceList: document.getElementById("review-evidence-list"),
  qualityGrade: document.getElementById("quality-grade"),
  qualityScore: document.getElementById("quality-score"),
  qualityCount: document.getElementById("quality-count"),
  qualityTableBody: document.getElementById("quality-table-body"),
  chatQuestion: document.getElementById("chat-question"),
  chatSendBtn: document.getElementById("chat-send-btn"),
  chatAnswer: document.getElementById("chat-answer"),
  saveSettingsBtn: document.getElementById("save-settings-btn"),
  settingsStatus: document.getElementById("settings-status"),
  mineruApiBase: document.getElementById("mineru-api-base"),
  mineruApiKey: document.getElementById("mineru-api-key"),
  llmProvider: document.getElementById("llm-provider"),
  llmModel: document.getElementById("llm-model"),
  llmBaseUrl: document.getElementById("llm-base-url"),
  llmApiKey: document.getElementById("llm-api-key"),
};

let docsState = [];
let activeFilter = "all";
let pollToken = 0;

function setUploadMessage(text, mode = "info") {
  els.uploadMessage.textContent = text;
  els.uploadMessage.dataset.mode = mode;
}

function statusToView(status) {
  const normalized = String(status || "").toLowerCase();
  if (normalized === "processed") return { state: "indexed", label: "已索引" };
  if (["processing", "uploaded", "retry_queued"].includes(normalized)) return { state: "processing", label: "处理中" };
  if (["failed", "failed_archived"].includes(normalized)) return { state: "review", label: "失败/复核" };
  return { state: "review", label: status || "未知" };
}

function readSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return {};
    return JSON.parse(raw);
  } catch (_err) {
    return {};
  }
}

function writeSettings(settings) {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

function collectSettings() {
  return {
    mineru_api_base: els.mineruApiBase.value.trim(),
    mineru_api_key: els.mineruApiKey.value.trim(),
    llm_provider: els.llmProvider.value.trim(),
    llm_model: els.llmModel.value.trim(),
    llm_base_url: els.llmBaseUrl.value.trim(),
    llm_api_key: els.llmApiKey.value.trim(),
  };
}

function applySettingsToForm(settings) {
  els.mineruApiBase.value = settings.mineru_api_base || "";
  els.mineruApiKey.value = settings.mineru_api_key || "";
  els.llmProvider.value = settings.llm_provider || "stub";
  els.llmModel.value = settings.llm_model || "gpt-4o-mini";
  els.llmBaseUrl.value = settings.llm_base_url || "https://api.openai.com/v1";
  els.llmApiKey.value = settings.llm_api_key || "";
}

function saveSettings() {
  const settings = collectSettings();
  writeSettings(settings);
  els.settingsStatus.textContent = "已保存并生效";
}

function matchesFilter(item, query) {
  const view = statusToView(item.status);
  if (activeFilter !== "all" && view.state !== activeFilter) return false;
  const raw = `${item.doc_name || ""} ${item.doc_id || ""} ${item.version_id || ""}`.toLowerCase();
  return raw.includes(query);
}

async function loadDocuments() {
  try {
    const resp = await fetch(`${API_BASE}/api/docs`);
    if (!resp.ok) throw new Error(`${resp.status}`);
    const data = await resp.json();
    docsState = Array.isArray(data.items) ? data.items : [];
    renderDocs();
  } catch (error) {
    setUploadMessage(`加载文档失败：${error.message}`, "error");
  }
}

function renderDocs() {
  const query = els.searchInput.value.trim().toLowerCase();
  const items = docsState.filter((x) => matchesFilter(x, query));
  els.docList.innerHTML = "";

  items.forEach((item) => {
    const li = document.createElement("li");
    li.className = "doc-row";
    const view = statusToView(item.status);

    li.innerHTML = [
      "<div class='doc-main'>",
      `<h3>${item.doc_name || "unknown.pdf"}</h3>`,
      `<p>doc=${item.doc_id || "-"} · ver=${item.version_id || "-"}</p>`,
      "</div>",
      `<span class='status status-${view.state}'>${view.label}</span>`,
      "<div class='doc-actions'></div>",
    ].join("");

    const actions = li.querySelector(".doc-actions");

    const reviewBtn = document.createElement("button");
    reviewBtn.className = "btn btn-secondary";
    reviewBtn.type = "button";
    reviewBtn.textContent = "查看证据";
    reviewBtn.addEventListener("click", () => loadArtifacts(item));
    actions.appendChild(reviewBtn);

    const evalBtn = document.createElement("button");
    evalBtn.className = "btn btn-ghost";
    evalBtn.type = "button";
    evalBtn.textContent = "加入评测集";
    evalBtn.addEventListener("click", () => addToEvalDataset(item));
    actions.appendChild(evalBtn);

    els.docList.appendChild(li);
  });

  els.resultCount.textContent = `${items.length} 条结果`;
}

async function loadArtifacts(item) {
  const versionId = item.version_id;
  els.reviewTitle.textContent = `证据 - ${item.doc_name || versionId}`;
  els.reviewEvidenceList.innerHTML = "<li>加载中...</li>";

  try {
    const resp = await fetch(`${API_BASE}/api/admin/docs/${encodeURIComponent(versionId)}/artifacts`);
    if (!resp.ok) throw new Error(`${resp.status}`);
    const data = await resp.json();
    const assets = Array.isArray(data.assets) ? data.assets : [];

    if (!assets.length) {
      els.reviewEvidenceList.innerHTML = "<li>暂无证据资产</li>";
      return;
    }

    els.reviewEvidenceList.innerHTML = "";
    assets.slice(0, 20).forEach((asset) => {
      const li = document.createElement("li");
      const page = asset.source_page || 1;
      li.innerHTML = [
        `<strong>${asset.asset_type || "asset"}</strong>`,
        `<span>第 ${page} 页</span>`,
        `<p>${asset.source_excerpt || ""}</p>`,
        `<a href="#page=${page}">定位到第 ${page} 页</a>`,
      ].join("");
      els.reviewEvidenceList.appendChild(li);
    });
  } catch (error) {
    els.reviewEvidenceList.innerHTML = `<li>加载失败：${error.message}</li>`;
  }
}

async function addToEvalDataset(item) {
  try {
    const payload = {
      dataset_version: "v1.0",
      doc_id: item.doc_id,
      version_id: item.version_id,
      task_type: "QA",
      question: `请概述 ${item.doc_name || "该文档"} 的关键条款。`,
      truth_answer: "请人工补充标准答案",
    };
    const resp = await fetch(`${API_BASE}/api/admin/eval/datasets/add`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) throw new Error(`${resp.status}`);
    const data = await resp.json();
    setUploadMessage(`已加入评测集：${data.item?.sample_id || "unknown"}`, "ok");
    await loadLLMQuality();
  } catch (error) {
    setUploadMessage(`加入评测集失败：${error.message}`, "error");
  }
}

async function loadLLMQuality() {
  try {
    const resp = await fetch(`${API_BASE}/api/admin/eval/llm-quality`);
    if (!resp.ok) return;
    const data = await resp.json();
    const item = data.item || {};

    els.qualityGrade.textContent = item.grade || "-";
    els.qualityScore.textContent = `${Math.round(item.overall_score || 0)}`;
    els.qualityCount.textContent = `${item.result_count || 0}`;

    const rows = Array.isArray(item.recent_results) ? item.recent_results : [];
    els.qualityTableBody.innerHTML = "";
    rows.slice(0, 12).forEach((row) => {
      const tr = document.createElement("tr");
      tr.innerHTML = [
        `<td>${row.sample_id || "-"}</td>`,
        `<td>${row.provider || "-"}/${row.model || "-"}</td>`,
        `<td>${Math.round(Number(row.score_total || 0))}</td>`,
        `<td>${row.created_at || "-"}</td>`,
      ].join("");
      els.qualityTableBody.appendChild(tr);
    });
  } catch (_error) {
    // keep quiet in polling
  }
}

async function startEvalRun() {
  try {
    const settings = collectSettings();
    const resp = await fetch(`${API_BASE}/api/admin/eval/runs/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        dataset_version: "v1.0",
        llm_provider: settings.llm_provider,
        llm_api_key: settings.llm_api_key,
        llm_model: settings.llm_model,
        llm_base_url: settings.llm_base_url,
      }),
    });
    if (!resp.ok) throw new Error(`${resp.status}`);
    setUploadMessage("评测任务已启动", "ok");
    await loadLLMQuality();
  } catch (error) {
    setUploadMessage(`启动评测失败：${error.message}`, "error");
  }
}

async function retryFailed() {
  try {
    const resp = await fetch(`${API_BASE}/api/admin/jobs/retry-failed`, { method: "POST" });
    if (!resp.ok) throw new Error(`${resp.status}`);
    setUploadMessage("已触发重试", "ok");
    await loadDocuments();
  } catch (error) {
    setUploadMessage(`重试失败：${error.message}`, "error");
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function pollVersionStatus(versionId, token, attemptsLeft) {
  if (token !== pollToken || attemptsLeft <= 0) return;
  try {
    const response = await fetch(`${API_BASE}/api/admin/docs/${encodeURIComponent(versionId)}/artifacts`);
    if (response.ok) {
      const payload = await response.json();
      const status = payload?.intermediate?.status || payload?.version?.status || "unknown";
      els.uploadVersionStatus.textContent = status;
      await loadDocuments();
      if (status === "processed") {
        setUploadMessage("抽取处理完成", "ok");
        return;
      }
      if (status === "failed" || status === "failed_archived") {
        setUploadMessage(`处理结束：${status}`, "error");
        return;
      }
    }
  } catch (error) {
    setUploadMessage(`轮询失败：${error.message}`, "error");
  }
  await sleep(2000);
  await pollVersionStatus(versionId, token, attemptsLeft - 1);
}

async function uploadPdf(file) {
  if (!file) return;
  const settings = collectSettings();

  pollToken += 1;
  const token = pollToken;
  els.uploadTrigger.disabled = true;
  els.uploadVersionStatus.textContent = "uploading";
  setUploadMessage(`正在上传 ${file.name}...`);

  try {
    const formData = new FormData();
    formData.append("file", file, file.name);

    if (settings.mineru_api_base) formData.append("mineru_api_base", settings.mineru_api_base);
    if (settings.mineru_api_key) formData.append("mineru_api_key", settings.mineru_api_key);
    if (settings.llm_provider) formData.append("llm_provider", settings.llm_provider);
    if (settings.llm_api_key) formData.append("llm_api_key", settings.llm_api_key);
    if (settings.llm_model) formData.append("llm_model", settings.llm_model);
    if (settings.llm_base_url) formData.append("llm_base_url", settings.llm_base_url);

    const response = await fetch(`${API_BASE}/api/upload`, { method: "POST", body: formData });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(`${response.status} ${text}`);
    }

    const payload = await response.json();
    els.uploadDocId.textContent = payload.doc_id || "-";
    els.uploadVersionId.textContent = payload.version_id || "-";
    els.uploadObjectKey.textContent = payload.object_key || "-";
    els.uploadVersionStatus.textContent = "uploaded";
    setUploadMessage("上传成功，已入队处理", "ok");

    await loadDocuments();
    await pollVersionStatus(payload.version_id, token, 90);
  } catch (error) {
    els.uploadVersionStatus.textContent = "upload_failed";
    setUploadMessage(`上传失败：${error.message}`, "error");
  } finally {
    els.uploadTrigger.disabled = false;
    els.pdfInput.value = "";
  }
}

async function sendChat() {
  const question = els.chatQuestion.value.trim();
  if (!question) return;

  const settings = collectSettings();
  els.chatAnswer.textContent = "请求中...";
  try {
    const resp = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        llm_provider: settings.llm_provider,
        llm_api_key: settings.llm_api_key,
        llm_model: settings.llm_model,
        llm_base_url: settings.llm_base_url,
      }),
    });
    if (!resp.ok) throw new Error(`${resp.status}`);
    const data = await resp.json();
    const summary = {
      answer: data.answer,
      llm: data.llm,
      citations: data.citations,
    };
    els.chatAnswer.textContent = JSON.stringify(summary, null, 2);
  } catch (error) {
    els.chatAnswer.textContent = `调用失败: ${error.message}`;
  }
}

els.saveSettingsBtn.addEventListener("click", saveSettings);
els.uploadTrigger.addEventListener("click", () => els.pdfInput.click());
els.pdfInput.addEventListener("change", () => {
  const file = els.pdfInput.files && els.pdfInput.files[0];
  if (file) uploadPdf(file);
});
els.retryFailedBtn.addEventListener("click", retryFailed);
els.startEvalBtn.addEventListener("click", startEvalRun);
els.chatSendBtn.addEventListener("click", sendChat);
els.searchInput.addEventListener("input", renderDocs);

els.chips.forEach((chip) => {
  chip.addEventListener("click", () => {
    activeFilter = chip.dataset.filter;
    els.chips.forEach((c) => c.classList.toggle("is-active", c === chip));
    renderDocs();
  });
});

applySettingsToForm(readSettings());
loadDocuments();
loadLLMQuality();
