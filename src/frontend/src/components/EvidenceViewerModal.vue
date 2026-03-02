<template>
  <div v-if="open" class="modal-overlay evidence-viewer-overlay" @click.self="$emit('close')">
    <div class="modal-dialog evidence-viewer-dialog" role="dialog" aria-modal="true" aria-label="证据定位">
      <header class="modal-header">
        <div>
          <h2>证据定位</h2>
          <p class="hint">{{ title || "原文预览" }}</p>
        </div>
        <button class="btn btn-ghost btn-icon" type="button" @click="$emit('close')" aria-label="关闭">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
        </button>
      </header>

      <div class="evidence-viewer-body">
        <aside class="evidence-nav">
          <div class="evidence-nav-title">证据片段</div>
          <div class="evidence-nav-list">
            <button
              v-for="asset in evidence"
              :key="asset.id"
              class="evidence-nav-item"
              :class="{ 'is-active': Number(asset.source_page || 1) === currentPage }"
              type="button"
              @click="jumpToPage(asset.source_page)"
            >
              <span class="evidence-nav-item-top">
                <strong>P{{ Number(asset.source_page || 1) }}</strong>
                <small>{{ asset.asset_type || "asset" }}</small>
              </span>
              <span class="evidence-nav-item-text">{{ asset.source_excerpt || "" }}</span>
            </button>
            <div v-if="!evidence.length" class="empty-state">暂无可定位证据</div>
          </div>
        </aside>

        <section class="evidence-pdf-pane">
          <div class="evidence-pdf-toolbar">
            <span>当前页：{{ currentPage }}<template v-if="totalPages > 0"> / {{ totalPages }}</template></span>
            <div class="evidence-pdf-toolbar-actions">
              <small class="hint">状态: 内置viewer</small>
              <small class="hint">渲染: PDF.js</small>
              <a v-if="pdfUrl" class="btn btn-secondary btn-sm" :href="newWindowHref" target="_blank" rel="noopener noreferrer">新窗口打开</a>
            </div>
          </div>
          <div v-if="effectiveLoading" class="evidence-pdf-loading">正在加载证据和原文...</div>
          <iframe
            v-else-if="pdfUrl"
            ref="viewerFrameRef"
            :key="viewerKey"
            class="evidence-pdf-frame"
            :src="viewerSrc"
            title="PDF 预览"
            @load="onViewerLoad"
          ></iframe>
          <div v-else class="empty-state">原文地址不可用</div>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from "vue";

const props = defineProps({
  open: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  title: { type: String, default: "" },
  pdfUrl: { type: String, default: "" },
  evidence: { type: Array, default: () => [] },
  initialPage: { type: Number, default: 1 },
});

defineEmits(["close"]);

const currentPage = ref(1);
const viewerNonce = ref(0);
const viewerFrameRef = ref(null);
const effectiveLoading = computed(() => Boolean(props.loading));
const totalPages = computed(() => {
  const pages = props.evidence.map((item) => Number(item?.source_page || 0)).filter((x) => Number.isFinite(x) && x > 0);
  return pages.length ? Math.max(...pages) : 0;
});

const viewerSrc = computed(() => {
  const base = String(props.pdfUrl || "").trim();
  if (!base) return "";
  const file = encodeURIComponent(base);
  return `/vendor/pdfjs/simple-viewer.html?file=${file}&nonce=${viewerNonce.value}`;
});

const viewerKey = computed(() => `${String(props.pdfUrl || "").trim()}|${viewerNonce.value}`);
const newWindowHref = computed(() => {
  const base = String(props.pdfUrl || "").trim();
  if (!base) return "";
  const page = Math.max(1, Number(currentPage.value || 1));
  return `${base}#page=${page}&zoom=page-width`;
});

function jumpToPage(pageNo) {
  const next = Math.max(1, Number(pageNo || 1));
  const upper = totalPages.value > 0 ? totalPages.value : next;
  currentPage.value = Math.min(next, upper);
}

function postViewerState() {
  const frameWindow = viewerFrameRef.value?.contentWindow;
  if (!frameWindow) return;
  frameWindow.postMessage(
    {
      type: "expert-pdf-viewer-state",
      fileUrl: String(props.pdfUrl || "").trim(),
      page: Math.max(1, Number(currentPage.value || 1)),
    },
    window.location.origin
  );
}

function onViewerLoad() {
  postViewerState();
}

watch(
  () => [props.open, props.initialPage, props.pdfUrl],
  ([open]) => {
    if (!open) return;
    currentPage.value = Math.max(1, Number(props.initialPage || 1));
    viewerNonce.value += 1;
  },
  { immediate: true }
);

watch(
  () => [props.open, props.pdfUrl, currentPage.value],
  ([open]) => {
    if (!open) return;
    window.setTimeout(() => {
      postViewerState();
    }, 0);
  }
);
</script>
