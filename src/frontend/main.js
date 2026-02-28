const input = document.getElementById("search-input");
const searchBtn = document.getElementById("search-btn");
const resultCount = document.getElementById("result-count");
const filterChips = Array.from(document.querySelectorAll(".filter-chip"));
const rowList = document.querySelector(".doc-list");
const uploadTrigger = document.getElementById("upload-trigger");
const pdfInput = document.getElementById("pdf-input");
const uploadMessage = document.getElementById("upload-message");
const uploadDocId = document.getElementById("upload-doc-id");
const uploadVersionId = document.getElementById("upload-version-id");
const uploadObjectKey = document.getElementById("upload-object-key");
const uploadVersionStatus = document.getElementById("upload-version-status");
const reviewTitle = document.getElementById("review-title");
const reviewEvidenceList = document.getElementById("review-evidence-list");
const retryFailedBtn = document.getElementById("retry-failed-btn");
const startEvalBtn = document.getElementById("start-eval-btn");

const trendFailureRate = document.getElementById("trend-failure-rate");
const trendQualityScore = document.getElementById("trend-quality-score");
const trendTotalResults = document.getElementById("trend-total-results");

let activeFilter = "all";
let pollToken = 0;
let docsState = [];

const API_BASE =
  window.EXPERTDB_API_BASE ||
  `${window.location.protocol}//${window.location.hostname || "localhost"}:8080`;

function statusToView(status) {
  const normalized = String(status || "").toLowerCase();
  if (normalized === "processed") {
    return { state: "indexed", label: "✓ 已索引" };
  }
  if (normalized === "processing" || normalized === "uploaded" || normalized === "retry_queued") {
    return { state: "processing", label: "↻ 处理中" };
  }
  if (normalized === "failed" || normalized === "failed_archived") {
    return { state: "review", label: "! 失败/需复核" };
  }
  return { state: "review", label: `! ${status || "未知状态"}` };
}

function setUploadMessage(message, mode) {
  uploadMessage.textContent = message;
  uploadMessage.dataset.mode = mode || "info";
}

function writeUploadMeta(payload) {
  uploadDocId.textContent = payload.doc_id || "-";
  uploadVersionId.textContent = payload.version_id || "-";
  uploadObjectKey.textContent = payload.object_key || "-";
}

function matchesFilter(item, query) {
  const view = statusToView(item.status);
  const matchesState = activeFilter === "all" || view.state === activeFilter;
  const text = `${item.doc_name || ""} ${item.version_id || ""} ${item.doc_id || ""}`.toLowerCase();
  return matchesState && text.includes(query);
}

function renderDocs() {
  const query = (input.value || "").trim().toLowerCase();
  const filtered = docsState.filter((item) => matchesFilter(item, query));

  rowList.innerHTML = "";
  filtered.forEach((item) => {
    const li = document.createElement("li");
    li.className = "doc-row";
    const view = statusToView(item.status);

    li.innerHTML = [
      "<div class='doc-main'>",
      `<h3>${item.doc_name || "(unknown)"}</h3>`,
      `<p>version: ${item.version_id || "-"} · doc: ${item.doc_id || "-"}</p>`,
      "</div>",
      `<span class='status status-${view.state}'>${view.label}</span>`,
      "<div class='doc-actions'></div>",
    ].join("");

    const actions = li.querySelector(".doc-actions");

    const inspectBtn = document.createElement("button");
    inspectBtn.className = "btn-jelly btn-ghost";
    inspectBtn.type = "button";
    inspectBtn.textContent = "查看证据";
    inspectBtn.addEventListener("click", () => loadArtifacts(item));
    actions.appendChild(inspectBtn);

    const addEvalBtn = document.createElement("button");
    addEvalBtn.className = "btn-jelly btn-secondary";
    addEvalBtn.type = "button";
    addEvalBtn.textContent = "加入评测集";
    addEvalBtn.addEventListener("click", () => addToEvalDataset(item));
    actions.appendChild(addEvalBtn);

    rowList.appendChild(li);
  });

  resultCount.textContent = `${filtered.length} 条结果`;
}

async function loadDocuments() {
  try {
    const resp = await fetch(`${API_BASE}/api/docs`);
    if (!resp.ok) {
      throw new Error(`${resp.status}`);
    }
    const data = await resp.json();
    docsState = Array.isArray(data.items) ? data.items : [];
    renderDocs();
  } catch (error) {
    setUploadMessage(`加载文档列表失败：${error.message}`, "error");
  }
}

async function loadEvalTrends() {
  try {
    const resp = await fetch(`${API_BASE}/api/admin/eval/trends`);
    if (!resp.ok) {
      return;
    }
    const data = await resp.json();
    const item = data.item || {};
    trendFailureRate.textContent = `${Math.round((item.failure_rate || 0) * 100)}%`;
    trendQualityScore.textContent = `${Math.round(item.quality_score_avg || 0)}`;
    trendTotalResults.textContent = `${item.total_results || 0}`;
  } catch (_err) {
    // Keep UI silent for trend polling errors.
  }
}

async function loadArtifacts(item) {
  const versionId = item.version_id;
  if (!versionId) {
    return;
  }

  reviewTitle.textContent = `证据预览：${item.doc_name || versionId}`;
  reviewEvidenceList.innerHTML = "<li>加载中...</li>";

  try {
    const resp = await fetch(`${API_BASE}/api/admin/docs/${encodeURIComponent(versionId)}/artifacts`);
    if (!resp.ok) {
      throw new Error(`${resp.status}`);
    }
    const data = await resp.json();
    const assets = Array.isArray(data.assets) ? data.assets : [];
    if (!assets.length) {
      reviewEvidenceList.innerHTML = "<li>暂无证据资产</li>";
      return;
    }

    reviewEvidenceList.innerHTML = "";
    assets.slice(0, 20).forEach((asset) => {
      const li = document.createElement("li");
      const page = asset.source_page || 1;
      const excerpt = asset.source_excerpt || "";
      li.innerHTML = [
        `<strong>${asset.asset_type || "asset"}</strong>`,
        `<span>第 ${page} 页</span>`,
        `<p>${excerpt}</p>`,
        `<a href="#page=${page}">跳转到 PDF 第 ${page} 页</a>`,
      ].join("");
      reviewEvidenceList.appendChild(li);
    });
  } catch (error) {
    reviewEvidenceList.innerHTML = `<li>加载失败：${error.message}</li>`;
  }
}

async function addToEvalDataset(item) {
  try {
    const payload = {
      dataset_version: "v1.0",
      doc_id: item.doc_id,
      version_id: item.version_id,
      task_type: "QA",
      question: `请总结 ${item.doc_name || "该文档"} 的核心条款。`,
      truth_answer: "请人工补充标准答案",
    };
    const resp = await fetch(`${API_BASE}/api/admin/eval/datasets/add`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      throw new Error(`${resp.status}`);
    }
    const data = await resp.json();
    setUploadMessage(`已加入评测集：${data.item?.sample_id || "unknown"}`, "ok");
  } catch (error) {
    setUploadMessage(`加入评测集失败：${error.message}`, "error");
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function pollVersionStatus(versionId, token, attemptsLeft) {
  if (token !== pollToken || attemptsLeft <= 0) {
    return;
  }

  try {
    const response = await fetch(`${API_BASE}/api/admin/docs/${encodeURIComponent(versionId)}/artifacts`);
    if (response.ok) {
      const payload = await response.json();
      const status = payload?.intermediate?.status || payload?.version?.status || "unknown";
      uploadVersionStatus.textContent = status;

      await loadDocuments();
      await loadEvalTrends();

      if (status === "processed") {
        setUploadMessage("抽取与索引完成，可开始检索与问答。", "ok");
        return;
      }
      if (status === "failed" || status === "failed_archived") {
        setUploadMessage(`抽取结束，状态：${status}。可在后台重试。`, "error");
        return;
      }
    }
  } catch (error) {
    setUploadMessage(`轮询状态失败：${error.message}`, "error");
  }

  await sleep(2000);
  await pollVersionStatus(versionId, token, attemptsLeft - 1);
}

async function uploadPdf(file) {
  if (!file) {
    return;
  }

  pollToken += 1;
  const token = pollToken;
  uploadTrigger.disabled = true;
  uploadVersionStatus.textContent = "uploading";
  setUploadMessage(`正在上传 ${file.name} ...`, "info");

  try {
    const formData = new FormData();
    formData.append("file", file, file.name);

    const response = await fetch(`${API_BASE}/api/upload`, { method: "POST", body: formData });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(`${response.status} ${text}`);
    }

    const payload = await response.json();
    writeUploadMeta(payload);
    uploadVersionStatus.textContent = "uploaded";
    setUploadMessage("上传成功，已入队并开始抽取。", "ok");

    await loadDocuments();
    await pollVersionStatus(payload.version_id, token, 90);
  } catch (error) {
    uploadVersionStatus.textContent = "upload_failed";
    setUploadMessage(`上传失败：${error.message}`, "error");
  } finally {
    uploadTrigger.disabled = false;
    pdfInput.value = "";
  }
}

async function retryFailed() {
  try {
    const resp = await fetch(`${API_BASE}/api/admin/jobs/retry-failed`, { method: "POST" });
    if (!resp.ok) {
      throw new Error(`${resp.status}`);
    }
    await loadDocuments();
    setUploadMessage("已触发失败任务重试。", "ok");
  } catch (error) {
    setUploadMessage(`重试失败任务失败：${error.message}`, "error");
  }
}

async function startEvalRun() {
  try {
    const resp = await fetch(`${API_BASE}/api/admin/eval/runs/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dataset_version: "v1.0" }),
    });
    if (!resp.ok) {
      throw new Error(`${resp.status}`);
    }
    await loadEvalTrends();
    setUploadMessage("评测任务已启动。", "ok");
  } catch (error) {
    setUploadMessage(`启动评测失败：${error.message}`, "error");
  }
}

filterChips.forEach((chip) => {
  chip.addEventListener("click", () => {
    activeFilter = chip.dataset.filter;
    filterChips.forEach((item) => {
      const isActive = item === chip;
      item.classList.toggle("is-active", isActive);
      item.setAttribute("aria-pressed", String(isActive));
    });
    renderDocs();
  });
});

searchBtn.addEventListener("click", renderDocs);
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    renderDocs();
  }
});

uploadTrigger.addEventListener("click", () => pdfInput.click());
pdfInput.addEventListener("change", () => {
  const file = pdfInput.files && pdfInput.files[0];
  if (file) {
    uploadPdf(file);
  }
});

retryFailedBtn.addEventListener("click", retryFailed);
startEvalBtn.addEventListener("click", startEvalRun);

loadDocuments();
loadEvalTrends();
