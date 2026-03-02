import * as pdfjsLib from "/vendor/pdfjs/pdf.min.mjs";

pdfjsLib.GlobalWorkerOptions.workerSrc = "/vendor/pdfjs/pdf.worker.min.mjs";

const params = new URLSearchParams(window.location.search);
let fileUrl = params.get("file") || "";
const pageParam = Number(params.get("page") || 1);
let targetPage = Number.isFinite(pageParam) && pageParam > 0 ? Math.floor(pageParam) : 1;

const wrap = document.getElementById("wrap");
const canvas = document.getElementById("pdf-canvas");
const bootError = document.getElementById("boot-error");

let currentDoc = null;
let currentDocUrl = "";
let renderVersion = 0;

function showError(message) {
  const text = String(message || "PDF render failed");
  if (wrap) {
    wrap.innerHTML = "";
    const box = document.createElement("div");
    box.className = "error";
    box.textContent = text;
    wrap.appendChild(box);
  }
  if (bootError) {
    bootError.style.display = "none";
  }
}

function clearBootError() {
  if (!bootError) return;
  bootError.style.display = "none";
  bootError.textContent = "";
}

async function renderPage(doc, version) {
  const pageNo = Math.min(Math.max(1, targetPage), Number(doc.numPages || 1));
  const page = await doc.getPage(pageNo);
  if (version !== renderVersion) return;

  const baseViewport = page.getViewport({ scale: 1 });
  const maxWidth = Math.max(240, Math.floor((wrap?.clientWidth || 0) - 24));
  const scale = maxWidth / Math.max(1, baseViewport.width);
  const viewport = page.getViewport({ scale });
  const dpr = window.devicePixelRatio || 1;
  const ctx = canvas?.getContext("2d");
  if (!ctx || !canvas) {
    showError("PDF viewer DOM 未就绪。");
    return;
  }

  canvas.width = Math.max(1, Math.floor(viewport.width * dpr));
  canvas.height = Math.max(1, Math.floor(viewport.height * dpr));
  canvas.style.width = `${Math.floor(viewport.width)}px`;
  canvas.style.height = `${Math.floor(viewport.height)}px`;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, Math.floor(viewport.width), Math.floor(viewport.height));
  await page.render({ canvasContext: ctx, viewport }).promise;
  clearBootError();
}

async function applyState(nextFileUrl, nextPage) {
  if (typeof nextPage === "number" && Number.isFinite(nextPage) && nextPage > 0) {
    targetPage = Math.floor(nextPage);
  }
  if (typeof nextFileUrl === "string" && nextFileUrl.trim()) {
    fileUrl = nextFileUrl.trim();
  }

  if (!wrap || !canvas) {
    showError("PDF viewer DOM 未就绪。");
    return;
  }
  if (!fileUrl) {
    showError("等待 PDF 地址...");
    return;
  }

  if (currentDoc && currentDocUrl === fileUrl) {
    const version = renderVersion + 1;
    renderVersion = version;
    try {
      await renderPage(currentDoc, version);
    } catch (error) {
      showError(`PDF 渲染失败：${String(error?.message || error || "unknown")}`);
    }
    return;
  }

  try {
    const loadingTask = pdfjsLib.getDocument({ url: fileUrl, withCredentials: true });
    const version = renderVersion + 1;
    renderVersion = version;
    const doc = await loadingTask.promise;
    if (version !== renderVersion) return;
    currentDoc = doc;
    currentDocUrl = fileUrl;
    await renderPage(doc, version);
  } catch (error) {
    showError(`PDF 渲染失败：${String(error?.message || error || "unknown")}`);
  }
}

let resizeTimer = null;
window.addEventListener("resize", () => {
  if (resizeTimer) window.clearTimeout(resizeTimer);
  resizeTimer = window.setTimeout(() => {
    void applyState(fileUrl, targetPage);
  }, 120);
});

window.addEventListener("message", (event) => {
  if (event.origin !== window.location.origin) return;
  const data = event.data || {};
  if (data.type !== "expert-pdf-viewer-state") return;
  void applyState(String(data.fileUrl || ""), Number(data.page || targetPage));
});

void applyState(fileUrl, targetPage);
