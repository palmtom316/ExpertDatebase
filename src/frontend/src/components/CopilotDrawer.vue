<template>
  <aside
    class="copilot-drawer"
    :class="{ 'is-open': !collapsed }"
    aria-label="Copilot Drawer"
  >
    <div class="drawer-content">
      <header class="drawer-header">
        <div class="drawer-title-group">
          <div class="copilot-eyebrow">ASSISTANT</div>
          <h2>AI Copilot</h2>
        </div>
        <div class="drawer-actions">
          <button class="btn btn-ghost btn-sm" type="button" @click="$emit('clearHistory')" title="清除历史记录">
            <svg viewBox="0 0 24 24" fill="none" class="icon-sm" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
          </button>
          <button class="btn btn-ghost btn-sm" type="button" @click="$emit('close')" title="收起面板 (Esc)">
            <svg viewBox="0 0 24 24" fill="none" class="icon-sm" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
          </button>
        </div>
      </header>

      <div class="drawer-body">
        <!-- Chat Section -->
        <section class="chat-section">
          <h3 class="section-subtitle">对话</h3>
          <div class="chat-timeline">
            <div v-if="messages.length === 0" class="empty-chat">
              你想了解文档的哪些信息？
            </div>
            <article
              v-for="message in messages"
              :key="message.id"
              class="chat-bubble"
              :class="`chat-${message.role}`"
            >
              <div class="bubble-content">{{ message.text }}</div>
              <div v-if="message.meta" class="bubble-meta">{{ message.meta }}</div>
            </article>
          </div>
          <div class="chat-compose">
            <textarea
              class="chat-input"
              v-model.trim="questionLocal"
              placeholder="问：例如 合同金额是多少？"
              :disabled="sending"
              @keydown.enter.prevent="submitChat"
              rows="2"
            ></textarea>
            <button class="btn btn-primary send-btn" type="button" :disabled="sending" @click="submitChat">
              <svg v-if="!sending" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path stroke-linecap="round" stroke-linejoin="round" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/></svg>
              <svg v-else class="spinner" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
            </button>
          </div>
        </section>

        <!-- Evidence Section -->
        <section class="evidence-section">
          <div class="evidence-header">
            <h3 class="section-subtitle">引用证据</h3>
            <span class="evidence-badge" :class="`evidence-badge-${evidenceQuality.level}`">
              {{ evidenceQuality.label }}
            </span>
          </div>
          <p class="evidence-title-hint">{{ evidenceTitle }}</p>
          <p v-if="evidenceQuality.level === 'low'" class="evidence-warn">
            证据可读性较低，建议在 API 设置中启用 VL 增强并对该文档执行"重新解析"。
          </p>
          <div class="evidence-list-container">
            <ul class="evidence-list">
              <li v-for="asset in pagedEvidence" :key="asset.id" class="evidence-card">
                <div class="evidence-card-head">
                  <span class="evidence-type">{{ asset.asset_type || "asset" }}</span>
                  <span class="evidence-page">第 {{ asset.source_page || 1 }} 页</span>
                </div>
                <div class="evidence-card-body">{{ asset.source_excerpt || "" }}</div>
                <div class="evidence-card-actions">
                  <button class="btn btn-ghost btn-sm" type="button" @click="$emit('openEvidenceSource', asset)">定位原文</button>
                </div>
                <div v-if="Number(asset.merged_count || 1) > 1" class="evidence-card-foot">
                  合并 {{ Number(asset.merged_count) }} 条片段
                </div>
              </li>
              <li v-if="evidence.length === 0" class="empty-state">暂无证据资产提取</li>
            </ul>
          </div>
          <div v-if="evidence.length > pageSize" class="evidence-pagination">
            <button class="btn btn-ghost btn-sm" type="button" :disabled="page <= 1" @click="page--">上一页</button>
            <span class="page-current">{{ page }} / {{ pageCount }}</span>
            <button class="btn btn-ghost btn-sm" type="button" :disabled="page >= pageCount" @click="page++">下一页</button>
          </div>
        </section>
      </div>
    </div>
  </aside>
</template>

<script setup>
import { computed, ref, watch } from "vue";

const props = defineProps({
  collapsed: { type: Boolean, default: true },
  messages: { type: Array, default: () => [] },
  sending: { type: Boolean, default: false },
  evidence: { type: Array, default: () => [] },
  evidenceTitle: { type: String, default: "" },
  evidenceQuality: { type: Object, default: () => ({ level: "empty", label: "待加载" }) },
});

const emit = defineEmits(["close", "clearHistory", "sendChat", "openEvidenceSource"]);

const pageSize = 8;
const page = ref(1);
const questionLocal = ref("");

const pageCount = computed(() => Math.max(1, Math.ceil(props.evidence.length / pageSize)));
const pagedEvidence = computed(() => {
  const p = Math.min(page.value, pageCount.value);
  const start = (p - 1) * pageSize;
  return props.evidence.slice(start, start + pageSize);
});

watch(
  () => props.evidence,
  () => {
    page.value = 1;
  },
  { deep: true }
);

function submitChat() {
  const q = questionLocal.value.trim();
  if (!q || props.sending) return;
  emit("sendChat", q);
  questionLocal.value = "";
}
</script>
