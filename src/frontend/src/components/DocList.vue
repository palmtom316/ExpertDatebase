<template>
  <section class="card docs-card">
    <div class="section-head">
      <h3>文档工作区</h3>
      <span class="hint">{{ filteredDocs.length }} 条结果</span>
    </div>
    <div class="toolbar">
      <input class="search-input" v-model.trim="searchQueryLocal" placeholder="按文档名或ID检索" />
      <select class="filter-select" v-model="docTypeFilterLocal">
        <option value="all">全部分类</option>
        <option v-for="item in docTypeOptions" :key="item" :value="item">{{ item }}</option>
      </select>
      <div class="segments" role="tablist" aria-label="文档过滤">
        <button
          v-for="chip in chips"
          :key="chip.value"
          class="segment-btn"
          :class="{ 'is-active': activeFilter === chip.value }"
          type="button"
          @click="activeFilter = chip.value"
        >
          {{ chip.label }}
        </button>
      </div>
    </div>
    <div class="table-container">
      <table class="data-table doc-list">
        <thead>
          <tr>
            <th>文档</th>
            <th>状态</th>
            <th class="text-right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in filteredDocs"
            :key="item.version_id || item.doc_id"
            class="doc-row"
            :class="{ 'is-selected': selectedDocId === (item.version_id || item.doc_id) }"
            @click="$emit('selectDoc', item)"
          >
            <td>
              <div class="doc-main">
                <div class="doc-title">{{ item.doc_name || "unknown.pdf" }}</div>
                <div class="doc-meta">doc={{ item.doc_id || "-" }} · ver={{ item.version_id || "-" }} · 分类={{ item.doc_type || "-" }}</div>
              </div>
            </td>
            <td>
              <span class="status-badge" :class="`status-${statusToView(item.status).state}`">
                {{ statusToView(item.status).label }}
              </span>
            </td>
            <td>
              <div class="doc-actions">
                <button class="btn btn-secondary btn-sm" type="button" @click.stop="$emit('loadArtifacts', item)">查看证据</button>
                <button class="btn btn-secondary btn-sm" type="button" @click.stop="$emit('openEvidenceViewer', item)">证据定位</button>
                <button class="btn btn-ghost btn-sm" type="button" @click.stop="$emit('addToEval', item)">试评</button>
                <button class="btn btn-secondary btn-sm" type="button" :disabled="!canReprocess(item)" @click.stop="$emit('reprocess', item)">解析</button>
                <button class="btn btn-danger btn-sm" type="button" :disabled="deletingVersionId === item.version_id" @click.stop="$emit('deleteDoc', item)">
                  {{ deletingVersionId === item.version_id ? "删除中..." : "删除" }}
                </button>
              </div>
            </td>
          </tr>
          <tr v-if="filteredDocs.length === 0">
            <td colspan="3" class="empty-state">未找到匹配文档</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from "vue";

const props = defineProps({
  docs: { type: Array, default: () => [] },
  selectedDocId: { type: String, default: "" },
  deletingVersionId: { type: String, default: "" },
  docTypeOptions: { type: Array, required: true },
});

const emit = defineEmits(["selectDoc", "loadArtifacts", "openEvidenceViewer", "addToEval", "reprocess", "deleteDoc", "docTypeFilterChange"]);

const chips = [
  { value: "all", label: "全部" },
  { value: "indexed", label: "已索引" },
  { value: "processing", label: "处理中" },
  { value: "review", label: "失败/复核" },
];

const searchQueryLocal = ref("");
const docTypeFilterLocal = ref("all");
const activeFilter = ref("all");

function statusToView(status) {
  const normalized = String(status || "").toLowerCase();
  if (normalized === "processed") return { state: "indexed", label: "已索引" };
  if (["processing", "uploaded", "retry_queued"].includes(normalized)) return { state: "processing", label: "处理中" };
  if (["failed", "failed_archived"].includes(normalized)) return { state: "review", label: "失败/复核" };
  return { state: "review", label: status || "未知" };
}

function canReprocess(item) {
  const status = String(item?.status || "").toLowerCase();
  return !["processing", "uploaded", "retry_queued"].includes(status);
}

const filteredDocs = computed(() => {
  const query = searchQueryLocal.value.toLowerCase();
  return props.docs.filter((item) => {
    const state = statusToView(item.status).state;
    if (activeFilter.value !== "all" && state !== activeFilter.value) return false;
    const rowType = String(item.doc_type || "").trim();
    if (docTypeFilterLocal.value !== "all" && rowType !== docTypeFilterLocal.value) return false;
    const raw = `${item.doc_name || ""} ${item.doc_id || ""} ${item.version_id || ""}`.toLowerCase();
    return raw.includes(query);
  });
});

watch(docTypeFilterLocal, (val) => {
  emit("docTypeFilterChange", val);
});
</script>
