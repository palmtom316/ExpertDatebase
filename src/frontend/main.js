const input = document.getElementById("search-input");
const searchBtn = document.getElementById("search-btn");
const resultCount = document.getElementById("result-count");
const filterChips = Array.from(document.querySelectorAll(".filter-chip"));
const rowList = document.querySelector(".doc-list");
const jellyButtons = Array.from(document.querySelectorAll(".btn-jelly"));
const uploadTrigger = document.getElementById("upload-trigger");
const pdfInput = document.getElementById("pdf-input");
const uploadMessage = document.getElementById("upload-message");
const uploadDocId = document.getElementById("upload-doc-id");
const uploadVersionId = document.getElementById("upload-version-id");
const uploadObjectKey = document.getElementById("upload-object-key");
const uploadVersionStatus = document.getElementById("upload-version-status");

let activeFilter = "all";
let pollToken = 0;

const API_BASE =
  window.EXPERTDB_API_BASE ||
  `${window.location.protocol}//${window.location.hostname || "localhost"}:8080`;

function getRows() {
  return Array.from(document.querySelectorAll(".doc-row"));
}

function rowMatches(row, query) {
  const matchesFilter = activeFilter === "all" || row.dataset.state === activeFilter;
  const matchesKeyword = row.textContent.toLowerCase().includes(query);
  return matchesFilter && matchesKeyword;
}

function renderList() {
  const query = input.value.trim().toLowerCase();
  let visible = 0;

  getRows().forEach((row) => {
    const show = rowMatches(row, query);
    row.classList.toggle("is-hidden", !show);
    if (show) {
      visible += 1;
    }
  });

  resultCount.textContent = `${visible} 条结果`;
}

filterChips.forEach((chip) => {
  chip.addEventListener("click", () => {
    activeFilter = chip.dataset.filter;
    filterChips.forEach((item) => {
      const isActive = item === chip;
      item.classList.toggle("is-active", isActive);
      item.setAttribute("aria-pressed", String(isActive));
    });
    renderList();
  });
});

searchBtn.addEventListener("click", renderList);
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    renderList();
  }
});

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

function upsertDocumentRow(filename, status, noteText) {
  const key = `upload:${filename}`;
  let row = rowList.querySelector(`.doc-row[data-doc-key="${key}"]`);
  if (!row) {
    row = document.createElement("li");
    row.className = "doc-row";
    row.dataset.docKey = key;
    row.innerHTML = [
      '<div class="doc-main">',
      `<h3>${filename}</h3>`,
      `<p>${noteText}</p>`,
      "</div>",
      '<span class="status"></span>',
      '<button class="btn-jelly btn-ghost" type="button">查看任务</button>',
    ].join("");
    rowList.prepend(row);
  }

  const view = statusToView(status);
  row.dataset.state = view.state;

  const desc = row.querySelector(".doc-main p");
  if (desc) {
    desc.textContent = noteText;
  }
  const statusNode = row.querySelector(".status");
  if (statusNode) {
    statusNode.textContent = view.label;
    statusNode.className = `status status-${view.state}`;
  }
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

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function pollVersionStatus(versionId, filename, token, attemptsLeft) {
  if (token !== pollToken || attemptsLeft <= 0) {
    return;
  }

  try {
    const response = await fetch(`${API_BASE}/api/admin/docs/${encodeURIComponent(versionId)}/artifacts`);
    if (response.ok) {
      const payload = await response.json();
      const status = payload?.intermediate?.status || payload?.version?.status || "unknown";
      uploadVersionStatus.textContent = status;
      upsertDocumentRow(filename, status, `最近更新：${new Date().toLocaleString()}`);
      renderList();

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
  await pollVersionStatus(versionId, filename, token, attemptsLeft - 1);
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
    upsertDocumentRow(file.name, "uploaded", `最近更新：${new Date().toLocaleString()}`);
    renderList();

    await pollVersionStatus(payload.version_id, file.name, token, 90);
  } catch (error) {
    uploadVersionStatus.textContent = "upload_failed";
    setUploadMessage(`上传失败：${error.message}`, "error");
  } finally {
    uploadTrigger.disabled = false;
    pdfInput.value = "";
  }
}

uploadTrigger.addEventListener("click", () => pdfInput.click());
pdfInput.addEventListener("change", () => {
  const file = pdfInput.files && pdfInput.files[0];
  if (file) {
    uploadPdf(file);
  }
});

jellyButtons.forEach((btn) => {
  btn.addEventListener("pointerdown", () => btn.classList.add("is-pressed"));
  btn.addEventListener("pointerup", () => btn.classList.remove("is-pressed"));
  btn.addEventListener("pointerleave", () => btn.classList.remove("is-pressed"));
});

renderList();
