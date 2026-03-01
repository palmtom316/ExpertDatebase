<template>
  <div>
    <div class="bg-layer bg-layer-a" aria-hidden="true"></div>
    <div class="bg-layer bg-layer-b" aria-hidden="true"></div>

    <header class="shell topbar">
      <div>
        <p class="top-eyebrow">ExpertDatebase</p>
        <h1>上线测试控制台</h1>
      </div>
      <div class="top-actions">
        <label class="top-select">
          分类
          <select v-model="selectedUploadDocType">
            <option v-for="item in docTypeOptions" :key="item" :value="item">{{ item }}</option>
          </select>
        </label>
        <button class="btn btn-primary" type="button" :disabled="isUploading" @click="triggerUpload">上传 PDF</button>
        <button class="btn btn-primary" type="button" @click="startEvalRun">启动评测</button>
        <button class="btn btn-secondary" type="button" @click="settingsDrawerOpen = true">API 设置</button>
      </div>
    </header>

    <input ref="pdfInputRef" class="hidden-input" type="file" accept=".pdf,application/pdf" @change="onFileChange" />

    <main class="shell cockpit-layout">
      <section class="workspace-main" @click="collapseCopilotIfNarrow">
        <section class="card upload-card" aria-live="polite">
          <div class="section-head">
            <h2>上传与任务状态</h2>
            <button class="btn btn-secondary" type="button" @click="retryFailed">重试失败任务</button>
          </div>
          <p class="status-message" :data-mode="uploadMessageMode">{{ uploadMessage }}</p>
          <div class="meta-grid">
            <p><b>doc_id</b> <span>{{ uploadMeta.docId || "-" }}</span></p>
            <p><b>version_id</b> <span>{{ uploadMeta.versionId || "-" }}</span></p>
            <p><b>object_key</b> <span>{{ uploadMeta.objectKey || "-" }}</span></p>
            <p><b>状态</b> <span>{{ uploadMeta.versionStatus || "-" }}</span></p>
            <p><b>分类</b> <span>{{ uploadMeta.docType || "-" }}</span></p>
          </div>
        </section>

        <section class="card docs-card">
          <h2>文档工作区</h2>
          <div class="toolbar">
            <input v-model.trim="searchQuery" placeholder="按文档名或ID检索" @focus="collapseCopilotIfNarrow" />
            <select v-model="docTypeFilter" @focus="collapseCopilotIfNarrow">
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
                @click="
                  activeFilter = chip.value;
                  collapseCopilotIfNarrow();
                "
              >
                {{ chip.label }}
              </button>
            </div>
          </div>
          <p class="hint">{{ filteredDocs.length }} 条结果</p>
          <ul class="doc-list">
            <li
              v-for="item in filteredDocs"
              :key="item.version_id || item.doc_id"
              class="doc-row"
              :class="{ 'is-selected': selectedDocId === (item.version_id || item.doc_id) }"
              @click="selectDocRow(item)"
            >
              <div class="doc-main">
                <h3>{{ item.doc_name || "unknown.pdf" }}</h3>
                <p>doc={{ item.doc_id || "-" }} · ver={{ item.version_id || "-" }} · 分类={{ item.doc_type || "-" }}</p>
              </div>
              <span class="status" :class="`status-${statusToView(item.status).state}`">
                {{ statusToView(item.status).label }}
              </span>
              <div class="doc-actions">
                <button class="btn btn-secondary" type="button" @click.stop="loadArtifacts(item)">查看证据</button>
                <button class="btn btn-ghost" type="button" @click.stop="addToEvalDataset(item)">加入评测集</button>
                <button class="btn btn-secondary" type="button" :disabled="!canReprocess(item)" @click.stop="reprocessDoc(item)">
                  重新解析
                </button>
                <button
                  class="btn btn-danger"
                  type="button"
                  :disabled="deletingVersionId === item.version_id"
                  @click.stop="deleteDoc(item)"
                >
                  {{ deletingVersionId === item.version_id ? "删除中..." : "删除" }}
                </button>
              </div>
            </li>
          </ul>
        </section>

        <section class="card quality-card">
          <h2>抽取质量趋势</h2>
          <div class="quality-metrics">
            <div><span>综合等级</span><strong>{{ quality.grade }}</strong></div>
            <div><span>综合分</span><strong>{{ quality.score }}</strong></div>
            <div><span>样本数</span><strong>{{ quality.count }}</strong></div>
          </div>
          <div class="quality-table-wrap">
            <table class="quality-table">
              <thead>
                <tr>
                  <th>sample_id</th>
                  <th>provider/model</th>
                  <th>score</th>
                  <th>时间</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in quality.rows" :key="row.id || row.sample_id">
                  <td>{{ row.sample_id || "-" }}</td>
                  <td>{{ `${row.provider || "-"} / ${row.model || "-"}` }}</td>
                  <td>{{ Math.round(Number(row.score_total || 0)) }}</td>
                  <td>{{ row.created_at || "-" }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </section>
    </main>

    <aside
      class="copilot-dock group transition-all duration-300"
      :class="{ 'is-collapsed': copilotCollapsed }"
      aria-label="Copilot 侧边栏"
    >
      <button
        class="copilot-rail opacity-85 transition-all duration-300 group-hover:opacity-100"
        type="button"
        @click="toggleCopilot"
        aria-label="切换 Copilot"
      >
        <span>COPILOT</span>
      </button>

      <section class="copilot-panel opacity-90 transition-all duration-300 group-hover:opacity-100">
        <header class="copilot-head">
          <div>
            <p class="copilot-eyebrow">ASSISTANT</p>
            <h2>Copilot</h2>
          </div>
          <div class="copilot-head-actions">
            <button class="segment-btn" type="button" @click="clearCopilotHistory">清除</button>
            <button class="segment-btn" type="button" @click="collapseCopilot">收起</button>
          </div>
        </header>

        <div class="copilot-body">
          <section class="chat-section">
            <h3>对话</h3>
            <div class="chat-timeline">
              <article
                v-for="message in chatMessages"
                :key="message.id"
                class="chat-bubble"
                :class="`chat-${message.role}`"
              >
                <p>{{ message.text }}</p>
                <small v-if="message.meta">{{ message.meta }}</small>
              </article>
            </div>
            <div class="chat-compose">
              <input
                v-model.trim="chatQuestion"
                placeholder="问：例如 合同金额是多少？"
                :disabled="chatSending"
                @keyup.enter="sendChat"
              />
              <button class="btn btn-primary" type="button" :disabled="chatSending" @click="sendChat">
                {{ chatSending ? "发送中..." : "发送" }}
              </button>
            </div>
          </section>

          <section class="evidence-section">
            <div class="evidence-head">
              <h3>引用证据</h3>
              <span class="evidence-badge" :class="`evidence-badge-${evidenceQuality.level}`">
                {{ evidenceQuality.label }}
              </span>
            </div>
            <p class="hint">{{ reviewTitle }}</p>
            <p v-if="evidenceQuality.level === 'low'" class="hint evidence-hint-warn">
              证据可读性较低，建议在设置中启用 VL 增强并对该文档执行“重新解析”。
            </p>
            <ul class="evidence-list">
              <li v-for="asset in pagedReviewEvidence" :key="asset.id">
                <strong>{{ asset.asset_type || "asset" }}</strong>
                <small v-if="Number(asset.merged_count || 1) > 1">合并 {{ Number(asset.merged_count) }} 条</small>
                <span>第 {{ asset.source_page || 1 }} 页</span>
                <p>{{ asset.source_excerpt || "" }}</p>
              </li>
              <li v-if="reviewEvidence.length === 0">暂无证据资产</li>
            </ul>
            <div v-if="reviewEvidence.length > EVIDENCE_PAGE_SIZE" class="evidence-pagination">
              <button class="segment-btn" type="button" :disabled="evidencePage <= 1" @click="prevEvidencePage">上一页</button>
              <span>{{ evidencePage }} / {{ evidencePageCount }}</span>
              <button class="segment-btn" type="button" :disabled="evidencePage >= evidencePageCount" @click="nextEvidencePage">
                下一页
              </button>
            </div>
          </section>

          <footer class="copilot-foot">
            <button class="segment-btn" type="button" @click="settingsDrawerOpen = true">设置</button>
            <span>⌘/Ctrl + J</span>
          </footer>
        </div>
      </section>
    </aside>

    <div v-if="settingsDrawerOpen" class="settings-overlay" @click.self="settingsDrawerOpen = false">
      <section class="settings-drawer" role="dialog" aria-modal="true" aria-label="运行时配置">
        <header class="settings-drawer-head">
          <div>
            <h2>运行时配置</h2>
            <p class="hint">全部采用 BYOK：所有模型调用仅使用你在此页面填写的 Key，不读取服务端预置密钥。</p>
          </div>
          <button class="segment-btn" type="button" @click="settingsDrawerOpen = false">关闭</button>
        </header>

        <div class="settings-grid">
          <p class="settings-subtitle">MinerU</p>
          <p class="settings-subtitle">文档解析</p>
          <label>
            MinerU API Base
            <input v-model.trim="settings.mineru_api_base" placeholder="https://mineru.net/api/v4/extract/task" />
          </label>
          <label>
            MinerU API Token
            <input v-model.trim="settings.mineru_api_key" type="password" placeholder="官网控制台 token" />
          </label>

          <p class="settings-subtitle">QA / Chat LLM</p>
          <p class="settings-subtitle">问答生成</p>
          <label>
            QA Provider
            <select v-model="settings.llm_provider">
              <option value="stub">stub</option>
              <option value="openai">openai</option>
              <option value="anthropic">anthropic</option>
            </select>
          </label>
          <label>
            QA Model
            <input v-model.trim="settings.llm_model" placeholder="gpt-4o-mini" />
          </label>
          <label>
            QA API Base
            <input v-model.trim="settings.llm_base_url" placeholder="https://api.openai.com/v1" />
          </label>
          <label>
            QA API Key
            <input v-model.trim="settings.llm_api_key" type="password" placeholder="llm-key" />
          </label>

          <p class="settings-subtitle">Embedding</p>
          <p class="settings-subtitle">向量化</p>
          <label>
            Embedding Provider
            <select v-model="settings.embedding_provider">
              <option value="stub">stub</option>
              <option value="openai">openai</option>
            </select>
          </label>
          <label>
            Embedding Model
            <input v-model.trim="settings.embedding_model" placeholder="text-embedding-3-small" />
          </label>
          <label>
            Embedding API Base
            <input v-model.trim="settings.embedding_base_url" placeholder="https://api.openai.com/v1" />
          </label>
          <label>
            Embedding API Key
            <input v-model.trim="settings.embedding_api_key" type="password" placeholder="embedding-key" />
          </label>

          <p class="settings-subtitle">Rerank</p>
          <p class="settings-subtitle">重排(可选)</p>
          <label>
            Rerank Provider
            <select v-model="settings.rerank_provider">
              <option value="stub">stub</option>
              <option value="openai">openai</option>
              <option value="local">local</option>
            </select>
          </label>
          <label>
            Rerank Model
            <input v-model.trim="settings.rerank_model" placeholder="BAAI/bge-reranker-v2-m3" />
          </label>
          <label>
            Rerank API Base
            <input v-model.trim="settings.rerank_base_url" placeholder="https://api.openai.com/v1" />
          </label>
          <label>
            Rerank API Key
            <input v-model.trim="settings.rerank_api_key" type="password" placeholder="rerank-key" />
          </label>

          <p class="settings-subtitle">VL 增强</p>
          <p class="settings-subtitle">图像/表格识别(可选)</p>
          <label>
            VL Provider
            <select v-model="settings.vl_provider">
              <option value="stub">stub</option>
              <option value="openai">openai</option>
            </select>
          </label>
          <label>
            VL Model
            <input v-model.trim="settings.vl_model" placeholder="gpt-4o-mini" />
          </label>
          <label>
            VL API Base
            <input v-model.trim="settings.vl_base_url" placeholder="https://api.openai.com/v1" />
          </label>
          <label>
            VL API Key
            <input v-model.trim="settings.vl_api_key" type="password" placeholder="vl-key" />
          </label>
        </div>

        <div class="settings-actions">
          <button class="btn btn-primary" type="button" @click="saveSettings">保存配置</button>
          <span class="hint">{{ settingsStatus }}</span>
        </div>

        <div class="connectivity-grid">
          <div class="connectivity-item">
            <button class="btn btn-secondary" type="button" :disabled="mineruConn.loading" @click="testMineruConnectivity">
              {{ mineruConn.loading ? "测试中..." : "测试 MinerU 联通" }}
            </button>
            <span class="conn-state" :class="connClass(mineruConn.ok)">{{ mineruConn.message }}</span>
          </div>
          <div class="connectivity-item">
            <button class="btn btn-secondary" type="button" :disabled="llmConn.loading" @click="testLLMConnectivity">
              {{ llmConn.loading ? "测试中..." : "测试 LLM 联通" }}
            </button>
            <span class="conn-state" :class="connClass(llmConn.ok)">{{ llmConn.message }}</span>
          </div>
          <div class="connectivity-item">
            <button class="btn btn-secondary" type="button" :disabled="embeddingConn.loading" @click="testEmbeddingConnectivity">
              {{ embeddingConn.loading ? "测试中..." : "测试 Embedding 联通" }}
            </button>
            <span class="conn-state" :class="connClass(embeddingConn.ok)">{{ embeddingConn.message }}</span>
          </div>
          <div class="connectivity-item">
            <button class="btn btn-secondary" type="button" :disabled="rerankConn.loading" @click="testRerankConnectivity">
              {{ rerankConn.loading ? "测试中..." : "测试 Rerank 联通" }}
            </button>
            <span class="conn-state" :class="connClass(rerankConn.ok)">{{ rerankConn.message }}</span>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";

const API_BASE = (window.EXPERTDB_API_BASE || "").trim().replace(/\/$/, "");
const SETTINGS_KEY = "expertdb_runtime_settings_v1";

const chips = [
  { value: "all", label: "全部" },
  { value: "indexed", label: "已索引" },
  { value: "processing", label: "处理中" },
  { value: "review", label: "失败/复核" },
];
const docTypeOptions = ["规范规程", "投标文件", "公司资质", "公司业绩", "公司资产", "人员资质", "人员业绩", "优秀标书"];

const pdfInputRef = ref(null);
const isUploading = ref(false);
const chatSending = ref(false);
const deletingVersionId = ref("");
const copilotCollapsed = ref(true);
const settingsDrawerOpen = ref(false);
const settingsStatus = ref("尚未保存");
const uploadMessage = ref("等待上传 PDF。");
const uploadMessageMode = ref("info");
const docsState = ref([]);
const activeFilter = ref("all");
const docTypeFilter = ref("all");
const selectedUploadDocType = ref("规范规程");
const searchQuery = ref("");
const selectedDocId = ref("");
const selectedDocVersionId = ref("");
const selectedDocDocId = ref("");
const reviewTitle = ref("在文档列表点击“查看证据”后，内容会显示到这里。");
const reviewEvidence = ref([]);
const evidencePage = ref(1);
const chatQuestion = ref("");
const chatMessages = ref([]);

const uploadMeta = reactive({
  docId: "-",
  versionId: "-",
  objectKey: "-",
  versionStatus: "-",
  docType: "规范规程",
});

const quality = reactive({
  grade: "-",
  score: 0,
  count: 0,
  rows: [],
});

const settings = reactive({
  mineru_api_base: "",
  mineru_api_key: "",
  llm_provider: "stub",
  llm_model: "gpt-4o-mini",
  llm_base_url: "https://api.openai.com/v1",
  llm_api_key: "",
  embedding_provider: "stub",
  embedding_model: "text-embedding-3-small",
  embedding_base_url: "https://api.openai.com/v1",
  embedding_api_key: "",
  rerank_provider: "stub",
  rerank_model: "BAAI/bge-reranker-v2-m3",
  rerank_base_url: "https://api.openai.com/v1",
  rerank_api_key: "",
  vl_provider: "stub",
  vl_model: "gpt-4o-mini",
  vl_base_url: "https://api.openai.com/v1",
  vl_api_key: "",
});

const mineruConn = reactive({ loading: false, ok: null, message: "未测试" });
const llmConn = reactive({ loading: false, ok: null, message: "未测试" });
const embeddingConn = reactive({ loading: false, ok: null, message: "未测试" });
const rerankConn = reactive({ loading: false, ok: null, message: "未测试" });

let pollToken = 0;
let messageSeq = 0;
const EVIDENCE_PAGE_SIZE = 8;
const EVIDENCE_MAX_ITEMS = 80;

function nextMessageId() {
  messageSeq += 1;
  return `m-${Date.now()}-${messageSeq}`;
}

function collapseCopilot() {
  copilotCollapsed.value = true;
}

function expandCopilot() {
  copilotCollapsed.value = false;
}

function toggleCopilot() {
  copilotCollapsed.value = !copilotCollapsed.value;
}

function collapseCopilotIfNarrow() {
  collapseCopilot();
}

function clearCopilotHistory() {
  chatMessages.value = [];
  reviewEvidence.value = [];
  reviewTitle.value = "历史对话已清除。";
  evidencePage.value = 1;
  pushAssistantMessage("历史对话与引用证据已清除。");
}

function setUploadMessage(text, mode = "info") {
  uploadMessage.value = text;
  uploadMessageMode.value = mode;
}

function pushAssistantMessage(text, meta = "") {
  chatMessages.value.push({ id: nextMessageId(), role: "assistant", text, meta });
}

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

function normalizeText(value) {
  const raw = String(value || "");
  const cleaned = raw
    .replace(/[\u0000-\u0008\u000B-\u001F\u007F]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned;
}

function normalizeDocMatchKey(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/\.pdf$/i, "")
    .replace(/[\s\-_/\\.,，。:：;；"'“”‘’()（）[\]【】<>《》|]+/g, "")
    .trim();
}

function parseDeleteCommand(question) {
  const text = String(question || "").trim();
  if (!text) return "";
  const direct = text.match(/^(?:请)?删除(?:文档|文件)?\s*[:：]?\s*(.+)$/);
  if (!direct) return "";
  return String(direct[1] || "")
    .replace(/[。！!]+$/g, "")
    .trim();
}

function findDeleteCandidates(target, docs = null) {
  const sourceDocs = Array.isArray(docs) ? docs : docsState.value;
  const rawTarget = String(target || "").trim();
  if (!rawTarget) return [];
  const lowerTarget = rawTarget.toLowerCase();
  const keyTarget = normalizeDocMatchKey(rawTarget);

  const scored = [];
  for (const item of sourceDocs) {
    const versionId = String(item?.version_id || "");
    const docId = String(item?.doc_id || "");
    const docName = String(item?.doc_name || "");
    const lowerName = docName.toLowerCase();
    const keyName = normalizeDocMatchKey(docName);
    let score = 0;

    if (lowerTarget.startsWith("version_id=") && versionId === lowerTarget.split("=", 2)[1]) score = 120;
    else if (lowerTarget.startsWith("doc_id=") && docId === lowerTarget.split("=", 2)[1]) score = 120;
    else if (rawTarget === versionId || rawTarget === docId) score = 110;
    else if (keyTarget && keyName === keyTarget) score = 100;
    else if (keyTarget && keyName.includes(keyTarget)) score = 80;
    else if (keyTarget && keyTarget.includes(keyName)) score = 60;
    else if (lowerName.includes(lowerTarget)) score = 40;

    if (score > 0) scored.push({ item, score });
  }

  scored.sort((a, b) => b.score - a.score);
  return scored.map((x) => x.item);
}

function denoiseEvidenceText(value) {
  let text = normalizeText(value);
  if (!text) return "";
  text = text
    .replace(/\$[^$]{0,200}\$/g, " ")
    .replace(/\\[a-zA-Z]+\s*\{[^}]*\}/g, " ")
    .replace(/\\[a-zA-Z]+/g, " ")
    .replace(/[{}]/g, " ")
    .replace(/\b\d{1,2}\.\d{1,2}(?:\.\d+)?\s*[A-Za-z][^；。]{0,100}\(\d{1,3}\)/g, " ")
    .replace(/[.…]{2,}\s*\(?\d{1,3}\)?/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return text;
}

function isTocLikeText(value) {
  const text = String(value || "").trim();
  if (!text) return true;
  const lower = text.toLowerCase();
  if (/(^|\s)contents?(\s|$)/.test(lower)) return true;
  if (/\b\d{1,2}\.\d{1,2}(?:\.\d+)?\s*[a-z]/.test(lower) && /\(\s*\d{1,3}\s*\)/.test(lower)) return true;
  if (/[.…]{2,}\s*\(?\d{1,3}\)?\s*$/.test(text)) return true;
  return false;
}

function readableRatio(text) {
  const s = String(text || "");
  if (!s) return 0;
  let good = 0;
  for (const ch of s) {
    if (/[A-Za-z0-9]/.test(ch)) {
      good += 1;
      continue;
    }
    if (/[\u4E00-\u9FFF]/.test(ch)) {
      good += 1;
      continue;
    }
    if ("，。！？；：、（）()[]【】《》“”‘’+-*/%=._:;,\"' ".includes(ch)) {
      good += 1;
    }
  }
  return good / s.length;
}

function cleanExcerpt(value, maxLen = 220) {
  const text = denoiseEvidenceText(value);
  if (!text) return "";
  const lower = text.toLowerCase();
  // Filter common PDF binary/object-stream noise.
  if (lower.includes("%pdf-") || lower.includes("obj<</filter/flatedecode") || lower.includes("endstream")) {
    return "";
  }
  if (isTocLikeText(text)) return "";
  if (text.length > 80 && readableRatio(text) < 0.55) return "";
  if (text.length > maxLen) return `${text.slice(0, maxLen)}...`;
  return text;
}

function summarizeAssetData(dataJson) {
  if (!dataJson || typeof dataJson !== "object") return "";
  const pairs = [
    ["standard_name", "标准"],
    ["project_name", "项目"],
    ["owner_unit", "业主"],
    ["contract_amount_original", "金额"],
    ["contract_amount_rmb", "金额(元)"],
    ["contract_sign_date", "签订日期"],
    ["voltage_level_kv", "电压等级(kV)"],
    ["substation_capacity_mva", "变电容量(MVA)"],
    ["line_length_km", "线路长度(km)"],
    ["transformer_capacity_mva", "主变容量(MVA)"],
    ["cable_type", "电缆类型"],
    ["name", "名称"],
  ];
  const parts = [];
  for (const [key, label] of pairs) {
    const v = dataJson[key];
    if (v === null || v === undefined) continue;
    const text = denoiseEvidenceText(v);
    if (!text || text === "-" || text.toLowerCase() === "null") continue;
    parts.push(`${label}: ${text}`);
  }
  return parts.join("；");
}

function mergeEvidenceAssets(assets) {
  const grouped = new Map();
  for (const raw of assets) {
    const asset = raw || {};
    const assetType = String(asset.asset_type || "asset");
    const sourcePage = Number(asset.source_page || 1);
    const key = `${assetType}|${sourcePage}`;

    const excerpt = cleanExcerpt(asset.source_excerpt || "", 180);
    const dataSummary = cleanExcerpt(summarizeAssetData(asset.data_json), 120);
    const displayText = dataSummary || excerpt;
    if (!displayText) continue;

    const current = grouped.get(key);
    if (!current) {
      grouped.set(key, {
        ...asset,
        source_page: sourcePage,
        source_excerpt: displayText,
        merged_count: 1,
      });
      continue;
    }

    if (!current.source_excerpt.includes(displayText)) {
      const merged = `${current.source_excerpt}；${displayText}`;
      current.source_excerpt = merged.length > 240 ? `${merged.slice(0, 240)}...` : merged;
    }
    current.merged_count = Number(current.merged_count || 1) + 1;
  }

  const out = Array.from(grouped.values());
  out.sort((a, b) => {
    if ((a.source_page || 0) !== (b.source_page || 0)) return (a.source_page || 0) - (b.source_page || 0);
    return String(a.asset_type || "").localeCompare(String(b.asset_type || ""));
  });
  return out;
}

function readSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function applySettings(payload) {
  if (!payload || typeof payload !== "object") return;
  settings.mineru_api_base = payload.mineru_api_base || "";
  settings.mineru_api_key = payload.mineru_api_key || "";
  settings.llm_provider = payload.llm_provider || "stub";
  settings.llm_model = payload.llm_model || "gpt-4o-mini";
  settings.llm_base_url = payload.llm_base_url || "https://api.openai.com/v1";
  settings.llm_api_key = payload.llm_api_key || "";
  settings.embedding_provider = payload.embedding_provider || "stub";
  settings.embedding_model = payload.embedding_model || "text-embedding-3-small";
  settings.embedding_base_url = payload.embedding_base_url || "https://api.openai.com/v1";
  settings.embedding_api_key = payload.embedding_api_key || "";
  settings.rerank_provider = payload.rerank_provider || "stub";
  settings.rerank_model = payload.rerank_model || "BAAI/bge-reranker-v2-m3";
  settings.rerank_base_url = payload.rerank_base_url || "https://api.openai.com/v1";
  settings.rerank_api_key = payload.rerank_api_key || "";
  settings.vl_provider = payload.vl_provider || "stub";
  settings.vl_model = payload.vl_model || "gpt-4o-mini";
  settings.vl_base_url = payload.vl_base_url || "https://api.openai.com/v1";
  settings.vl_api_key = payload.vl_api_key || "";
}

function hasRuntimeSettings(payload) {
  if (!payload || typeof payload !== "object") return false;
  return Boolean(
    String(payload.mineru_api_base || "").trim() ||
      String(payload.mineru_api_key || "").trim() ||
      String(payload.llm_api_key || "").trim() ||
      String(payload.embedding_api_key || "").trim()
  );
}

function collectSettings() {
  return {
    mineru_api_base: settings.mineru_api_base.trim(),
    mineru_api_key: settings.mineru_api_key.trim(),
    llm_provider: settings.llm_provider.trim(),
    llm_model: settings.llm_model.trim(),
    llm_base_url: settings.llm_base_url.trim(),
    llm_api_key: settings.llm_api_key.trim(),
    embedding_provider: settings.embedding_provider.trim(),
    embedding_model: settings.embedding_model.trim(),
    embedding_base_url: settings.embedding_base_url.trim(),
    embedding_api_key: settings.embedding_api_key.trim(),
    rerank_provider: settings.rerank_provider.trim(),
    rerank_model: settings.rerank_model.trim(),
    rerank_base_url: settings.rerank_base_url.trim(),
    rerank_api_key: settings.rerank_api_key.trim(),
    vl_provider: settings.vl_provider.trim(),
    vl_model: settings.vl_model.trim(),
    vl_base_url: settings.vl_base_url.trim(),
    vl_api_key: settings.vl_api_key.trim(),
  };
}

function saveSettings() {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(collectSettings()));
  settingsStatus.value = "已保存并生效";
  pushAssistantMessage("运行时配置已保存。");
}

function connClass(ok) {
  if (ok === true) return "conn-ok";
  if (ok === false) return "conn-fail";
  return "";
}

async function runConnectivityTest(target, state) {
  const runtime = collectSettings();
  state.loading = true;
  state.ok = null;
  state.message = "测试中...";

  try {
    const resp = await fetch(`${API_BASE}/api/admin/connectivity/test`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        target,
        mineru_api_base: runtime.mineru_api_base,
        mineru_api_key: runtime.mineru_api_key,
        llm_provider: runtime.llm_provider,
        llm_api_key: runtime.llm_api_key,
        llm_model: runtime.llm_model,
        llm_base_url: runtime.llm_base_url,
        embedding_provider: runtime.embedding_provider,
        embedding_api_key: runtime.embedding_api_key,
        embedding_model: runtime.embedding_model,
        embedding_base_url: runtime.embedding_base_url,
        rerank_provider: runtime.rerank_provider,
        rerank_api_key: runtime.rerank_api_key,
        rerank_model: runtime.rerank_model,
        rerank_base_url: runtime.rerank_base_url,
        vl_provider: runtime.vl_provider,
        vl_api_key: runtime.vl_api_key,
        vl_model: runtime.vl_model,
        vl_base_url: runtime.vl_base_url,
      }),
    });
    const payload = await resp.json();
    state.ok = !!payload.ok;
    state.message = payload.message || (payload.ok ? "联通成功" : "联通失败");
    pushAssistantMessage(`[${target.toUpperCase()}] ${state.message}`);
  } catch (error) {
    state.ok = false;
    state.message = `联通失败: ${error.message}`;
    pushAssistantMessage(`[${target.toUpperCase()}] ${state.message}`);
  } finally {
    state.loading = false;
  }
}

async function testMineruConnectivity() {
  const runtime = collectSettings();
  if (!runtime.mineru_api_base) {
    mineruConn.ok = false;
    mineruConn.message = "请先填写 MinerU API Base";
    return;
  }
  await runConnectivityTest("mineru", mineruConn);
}

async function testLLMConnectivity() {
  const runtime = collectSettings();
  if (!runtime.llm_provider) {
    llmConn.ok = false;
    llmConn.message = "请先选择 LLM Provider";
    return;
  }
  await runConnectivityTest("llm", llmConn);
}

async function testEmbeddingConnectivity() {
  const runtime = collectSettings();
  if (!runtime.embedding_provider) {
    embeddingConn.ok = false;
    embeddingConn.message = "请先选择 Embedding Provider";
    return;
  }
  await runConnectivityTest("embedding", embeddingConn);
}

async function testRerankConnectivity() {
  const runtime = collectSettings();
  if (!runtime.rerank_provider) {
    rerankConn.ok = false;
    rerankConn.message = "请先选择 Rerank Provider";
    return;
  }
  await runConnectivityTest("rerank", rerankConn);
}

const filteredDocs = computed(() => {
  const query = searchQuery.value.toLowerCase();
  return docsState.value.filter((item) => {
    const state = statusToView(item.status).state;
    if (activeFilter.value !== "all" && state !== activeFilter.value) return false;
    const rowType = String(item.doc_type || "").trim();
    if (docTypeFilter.value !== "all" && rowType !== docTypeFilter.value) return false;
    const raw = `${item.doc_name || ""} ${item.doc_id || ""} ${item.version_id || ""}`.toLowerCase();
    return raw.includes(query);
  });
});

const evidencePageCount = computed(() => Math.max(1, Math.ceil(reviewEvidence.value.length / EVIDENCE_PAGE_SIZE)));
const pagedReviewEvidence = computed(() => {
  const page = Math.min(evidencePage.value, evidencePageCount.value);
  const start = (page - 1) * EVIDENCE_PAGE_SIZE;
  return reviewEvidence.value.slice(start, start + EVIDENCE_PAGE_SIZE);
});
const evidenceQuality = computed(() => {
  if (reviewEvidence.value.length === 0) {
    return { level: "empty", label: "待加载", score: 0 };
  }
  const scores = reviewEvidence.value.map((item) => {
    const text = String(item?.source_excerpt || "").trim();
    if (!text) return 0;
    let score = readableRatio(text);
    if (isTocLikeText(text)) score *= 0.2;
    if (/\\[a-zA-Z]+/.test(text) || /\$[^$]{0,120}\$/.test(text)) score *= 0.5;
    if (text.length < 18) score *= 0.7;
    return Math.max(0, Math.min(1, score));
  });
  const avg = scores.reduce((acc, x) => acc + x, 0) / Math.max(1, scores.length);
  if (avg >= 0.78) return { level: "good", label: "可读", score: avg };
  if (avg >= 0.6) return { level: "medium", label: "一般", score: avg };
  return { level: "low", label: "低可读", score: avg };
});

function prevEvidencePage() {
  evidencePage.value = Math.max(1, evidencePage.value - 1);
}

function nextEvidencePage() {
  evidencePage.value = Math.min(evidencePageCount.value, evidencePage.value + 1);
}

watch(
  () => reviewEvidence.value.length,
  () => {
    if (reviewEvidence.value.length === 0) {
      evidencePage.value = 1;
      return;
    }
    if (evidencePage.value > evidencePageCount.value) {
      evidencePage.value = evidencePageCount.value;
    }
  }
);

watch(
  () => docTypeFilter.value,
  async () => {
    await loadDocuments();
  }
);

function syncUploadMetaFromDocs(items) {
  const currentVersionId = String(uploadMeta.versionId || "");
  if (!currentVersionId || currentVersionId === "-") return;
  const matched = (Array.isArray(items) ? items : []).find((item) => String(item.version_id || "") === currentVersionId);
  if (!matched) return;
  uploadMeta.versionStatus = matched.status || uploadMeta.versionStatus;
  if (!uploadMeta.docId || uploadMeta.docId === "-") uploadMeta.docId = matched.doc_id || uploadMeta.docId;
  if (!uploadMeta.objectKey || uploadMeta.objectKey === "-") uploadMeta.objectKey = matched.storage_key || uploadMeta.objectKey;
  uploadMeta.docType = matched.doc_type || uploadMeta.docType;
}

async function loadDocuments() {
  try {
    const query = docTypeFilter.value !== "all" ? `?doc_type=${encodeURIComponent(docTypeFilter.value)}` : "";
    const resp = await fetch(`${API_BASE}/api/docs${query}`);
    if (!resp.ok) throw new Error(`${resp.status}`);
    const data = await resp.json();
    docsState.value = Array.isArray(data.items) ? data.items : [];
    syncUploadMetaFromDocs(docsState.value);
  } catch (error) {
    setUploadMessage(`加载文档失败：${error.message}`, "error");
  }
}

function selectDocRow(item) {
  selectedDocId.value = item.version_id || item.doc_id || "";
  selectedDocVersionId.value = item.version_id || "";
  selectedDocDocId.value = item.doc_id || "";
  expandCopilot();
  pushAssistantMessage(`已选中文档 ${item.doc_name || item.version_id || item.doc_id || "unknown"}。`);
}

async function loadArtifacts(item) {
  reviewTitle.value = `证据 - ${item.doc_name || item.version_id}`;
  reviewEvidence.value = [];
  evidencePage.value = 1;
  selectedDocId.value = item.version_id || item.doc_id || "";
  selectedDocVersionId.value = item.version_id || "";
  selectedDocDocId.value = item.doc_id || "";
  expandCopilot();
  try {
    const resp = await fetch(`${API_BASE}/api/admin/docs/${encodeURIComponent(item.version_id)}/artifacts`);
    if (!resp.ok) throw new Error(`${resp.status}`);
    const data = await resp.json();
    const assets = Array.isArray(data.assets) ? data.assets : [];
    const mergedAssets = mergeEvidenceAssets(assets).slice(0, EVIDENCE_MAX_ITEMS);
    reviewEvidence.value = mergedAssets.map((asset, idx) => ({
      ...asset,
      id: `${asset.asset_id || asset.asset_type || "asset"}-${idx}`,
    }));
    if (reviewEvidence.value.length === 0) {
      reviewEvidence.value = [
        {
          id: "empty",
          asset_type: "hint",
          source_excerpt: "当前证据文本可读性较低，建议切换解析模型后重试，或直接查看原文。",
          source_page: 1,
        },
      ];
    }
    pushAssistantMessage(`已加载 ${reviewEvidence.value.length} 条证据（已自动去重与降噪）。`);
    if (evidenceQuality.value.level === "low") {
      pushAssistantMessage("当前证据可读性偏低。建议启用 VL 增强后对该文档重新解析，以提升检索与回答质量。");
    }
  } catch (error) {
    reviewEvidence.value = [{ id: "error", asset_type: "error", source_excerpt: `加载失败：${error.message}`, source_page: 1 }];
    pushAssistantMessage(`证据加载失败：${error.message}`);
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
    pushAssistantMessage(`文档已加入评测集：${data.item?.sample_id || "unknown"}`);
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
    quality.grade = item.grade || "-";
    quality.score = `${Math.round(item.overall_score || 0)}`;
    quality.count = `${item.result_count || 0}`;
    quality.rows = Array.isArray(item.recent_results) ? item.recent_results.slice(0, 20) : [];
  } catch {
    // no-op
  }
}

async function startEvalRun() {
  try {
    const config = collectSettings();
    const resp = await fetch(`${API_BASE}/api/admin/eval/runs/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        dataset_version: "v1.0",
        llm_provider: config.llm_provider,
        llm_api_key: config.llm_api_key,
        llm_model: config.llm_model,
        llm_base_url: config.llm_base_url,
      }),
    });
    if (!resp.ok) throw new Error(`${resp.status}`);
    setUploadMessage("评测任务已启动", "ok");
    pushAssistantMessage("评测任务已启动。");
    await loadLLMQuality();
  } catch (error) {
    setUploadMessage(`启动评测失败：${error.message}`, "error");
  }
}

async function retryFailed() {
  try {
    const resp = await fetch(`${API_BASE}/api/admin/jobs/retry-failed`, { method: "POST" });
    if (!resp.ok) throw new Error(`${resp.status}`);
    const payload = await resp.json();
    const retriedCount = Number(payload?.retried_count || 0);
    const retriedIds = Array.isArray(payload?.version_ids) ? payload.version_ids : [];
    setUploadMessage(retriedCount > 0 ? `已触发重试（${retriedCount} 条）` : "当前没有可重试任务", retriedCount > 0 ? "ok" : "info");
    pushAssistantMessage("已触发失败任务重试。");
    await loadDocuments();
    const currentVersionId = String(uploadMeta.versionId || "");
    if (currentVersionId && currentVersionId !== "-" && retriedIds.includes(currentVersionId)) {
      uploadMeta.versionStatus = "retry_queued";
      pollToken += 1;
      await pollVersionStatus(currentVersionId, pollToken, 90);
    }
  } catch (error) {
    setUploadMessage(`重试失败：${error.message}`, "error");
  }
}

async function reprocessDoc(item) {
  if (!item?.version_id || !canReprocess(item)) return;
  const runtime = collectSettings();
  if (!runtime.mineru_api_base || !runtime.mineru_api_key) {
    setUploadMessage("请先在 API 设置中填写 MinerU API Base 与 MinerU API Token", "error");
    pushAssistantMessage("重新解析前需要先填写 MinerU API 配置。");
    return;
  }
  try {
    const resp = await fetch(`${API_BASE}/api/admin/jobs/reprocess`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        version_id: item.version_id,
        mineru_api_base: runtime.mineru_api_base,
        mineru_api_key: runtime.mineru_api_key,
        llm_provider: runtime.llm_provider,
        llm_api_key: runtime.llm_api_key,
        llm_model: runtime.llm_model,
        llm_base_url: runtime.llm_base_url,
        embedding_provider: runtime.embedding_provider,
        embedding_api_key: runtime.embedding_api_key,
        embedding_model: runtime.embedding_model,
        embedding_base_url: runtime.embedding_base_url,
        rerank_provider: runtime.rerank_provider,
        rerank_api_key: runtime.rerank_api_key,
        rerank_model: runtime.rerank_model,
        rerank_base_url: runtime.rerank_base_url,
        vl_provider: runtime.vl_provider,
        vl_api_key: runtime.vl_api_key,
        vl_model: runtime.vl_model,
        vl_base_url: runtime.vl_base_url,
      }),
    });
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`${resp.status} ${text}`);
    }
    const payload = await resp.json();
    uploadMeta.docId = payload.doc_id || item.doc_id || "-";
    uploadMeta.versionId = payload.version_id || item.version_id || "-";
    uploadMeta.objectKey = payload.object_key || item.storage_key || "-";
    uploadMeta.versionStatus = "retry_queued";
    uploadMeta.docType = item.doc_type || uploadMeta.docType;
    setUploadMessage(`已触发重新解析：${item.doc_name || item.version_id}`, "ok");
    pushAssistantMessage(`已触发重新解析（version=${item.version_id}）。`);

    await loadDocuments();
    pollToken += 1;
    await pollVersionStatus(item.version_id, pollToken, 90);
  } catch (error) {
    setUploadMessage(`重新解析失败：${error.message}`, "error");
  }
}

async function deleteDoc(item, options = {}) {
  const versionId = String(item?.version_id || "").trim();
  if (!versionId || deletingVersionId.value) return;
  const name = item?.doc_name || versionId;
  const skipConfirm = !!options?.skipConfirm;
  const source = String(options?.source || "ui");
  if (!skipConfirm) {
    const confirmed = window.confirm(`确认删除文档：${name}？\n删除后不可恢复。`);
    if (!confirmed) return { ok: false, cancelled: true };
  }

  deletingVersionId.value = versionId;
  try {
    const resp = await fetch(`${API_BASE}/api/admin/docs/${encodeURIComponent(versionId)}`, { method: "DELETE" });
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`${resp.status} ${text}`);
    }
    await resp.json();

    if (selectedDocId.value === versionId || selectedDocId.value === String(item?.doc_id || "")) {
      selectedDocId.value = "";
      selectedDocVersionId.value = "";
      selectedDocDocId.value = "";
      reviewEvidence.value = [];
      reviewTitle.value = "文档已删除，请重新选择文档。";
      evidencePage.value = 1;
    }
    if (String(uploadMeta.versionId || "") === versionId) {
      uploadMeta.docId = "-";
      uploadMeta.versionId = "-";
      uploadMeta.objectKey = "-";
      uploadMeta.versionStatus = "-";
      uploadMeta.docType = selectedUploadDocType.value || "规范规程";
    }

    setUploadMessage(`已删除文档：${name}`, "ok");
    const suffix = source === "chat" ? "（Copilot 指令）" : "";
    pushAssistantMessage(`已删除文档 ${name}（version=${versionId}）${suffix}。`);
    await loadDocuments();
    return { ok: true, versionId, name };
  } catch (error) {
    setUploadMessage(`删除失败：${error.message}`, "error");
    pushAssistantMessage(`删除失败：${error.message}`);
    return { ok: false, error: error.message };
  } finally {
    deletingVersionId.value = "";
  }
}

async function handleDeleteCommand(question) {
  const target = parseDeleteCommand(question);
  if (!target) return false;

  let candidateDocs = Array.isArray(docsState.value) ? docsState.value : [];
  try {
    const resp = await fetch(`${API_BASE}/api/docs`);
    if (resp.ok) {
      const data = await resp.json();
      candidateDocs = Array.isArray(data.items) ? data.items : candidateDocs;
    }
  } catch {
    // fallback to in-memory list
  }
  if (!candidateDocs.length) {
    await loadDocuments();
    candidateDocs = Array.isArray(docsState.value) ? docsState.value : [];
  }
  const candidates = findDeleteCandidates(target, candidateDocs);
  if (candidates.length === 0) {
    pushAssistantMessage(`未找到匹配文档：${target}。可使用“删除 version_id=ver_xxx”精确删除。`);
    return true;
  }
  if (candidates.length > 1) {
    const lines = candidates.slice(0, 8).map((it, idx) => `${idx + 1}. ${it.doc_name || "-"}（ver=${it.version_id || "-"}）`);
    pushAssistantMessage(
      `匹配到 ${candidates.length} 个文档，请改用更精确指令：\n` +
        `- 删除 version_id=ver_xxx\n- 或输入更完整的文件名\n\n候选：\n${lines.join("\n")}`
    );
    return true;
  }

  await deleteDoc(candidates[0], { skipConfirm: true, source: "chat" });
  return true;
}

function triggerUpload() {
  if (isUploading.value) return;
  collapseCopilotIfNarrow();
  pdfInputRef.value?.click();
}

function onFileChange(event) {
  const file = event.target?.files?.[0];
  if (file) uploadPdf(file);
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
      uploadMeta.versionStatus = status;
      await loadDocuments();
      if (status === "processed") {
        setUploadMessage("抽取处理完成", "ok");
        pushAssistantMessage("文档处理完成，可以继续提问或查看证据。");
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
  pollToken += 1;
  const token = pollToken;
  const runtime = collectSettings();
  isUploading.value = true;
  uploadMeta.versionStatus = "uploading";
  setUploadMessage(`正在上传 ${file.name}...`, "info");
  expandCopilot();

  try {
    const formData = new FormData();
    formData.append("file", file, file.name);
    formData.append("doc_type", selectedUploadDocType.value || "规范规程");
    if (runtime.mineru_api_base) formData.append("mineru_api_base", runtime.mineru_api_base);
    if (runtime.mineru_api_key) formData.append("mineru_api_key", runtime.mineru_api_key);
    if (runtime.llm_provider) formData.append("llm_provider", runtime.llm_provider);
    if (runtime.llm_api_key) formData.append("llm_api_key", runtime.llm_api_key);
    if (runtime.llm_model) formData.append("llm_model", runtime.llm_model);
    if (runtime.llm_base_url) formData.append("llm_base_url", runtime.llm_base_url);
    if (runtime.embedding_provider) formData.append("embedding_provider", runtime.embedding_provider);
    if (runtime.embedding_api_key) formData.append("embedding_api_key", runtime.embedding_api_key);
    if (runtime.embedding_model) formData.append("embedding_model", runtime.embedding_model);
    if (runtime.embedding_base_url) formData.append("embedding_base_url", runtime.embedding_base_url);
    if (runtime.rerank_provider) formData.append("rerank_provider", runtime.rerank_provider);
    if (runtime.rerank_api_key) formData.append("rerank_api_key", runtime.rerank_api_key);
    if (runtime.rerank_model) formData.append("rerank_model", runtime.rerank_model);
    if (runtime.rerank_base_url) formData.append("rerank_base_url", runtime.rerank_base_url);
    if (runtime.vl_provider) formData.append("vl_provider", runtime.vl_provider);
    if (runtime.vl_api_key) formData.append("vl_api_key", runtime.vl_api_key);
    if (runtime.vl_model) formData.append("vl_model", runtime.vl_model);
    if (runtime.vl_base_url) formData.append("vl_base_url", runtime.vl_base_url);

    const response = await fetch(`${API_BASE}/api/upload`, { method: "POST", body: formData });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(`${response.status} ${text}`);
    }

    const payload = await response.json();
    uploadMeta.docId = payload.doc_id || "-";
    uploadMeta.versionId = payload.version_id || "-";
    uploadMeta.objectKey = payload.object_key || "-";
    uploadMeta.docType = payload.doc_type || selectedUploadDocType.value || "规范规程";
    if (payload.doc_type && !["all", payload.doc_type].includes(docTypeFilter.value)) {
      docTypeFilter.value = payload.doc_type;
    }
    if (payload.deduplicated) {
      uploadMeta.versionStatus = payload.status || "processed";
      if (payload.requeued) {
        setUploadMessage("文件已存在，已触发重新解析", "ok");
        pushAssistantMessage(`文档 ${file.name} 已命中去重并重新入队（version=${payload.version_id || "-"}）。`);
      } else {
        setUploadMessage("文件已存在，已复用历史任务", "ok");
        pushAssistantMessage(`文档 ${file.name} 已去重复用（version=${payload.version_id || "-"}）。`);
      }
    } else {
      uploadMeta.versionStatus = "uploaded";
      setUploadMessage("上传成功，已入队处理", "ok");
      pushAssistantMessage(`文档 ${file.name} 上传成功，正在处理。`);
    }

    await loadDocuments();
    await pollVersionStatus(payload.version_id, token, 90);
  } catch (error) {
    uploadMeta.versionStatus = "upload_failed";
    setUploadMessage(`上传失败：${error.message}`, "error");
  } finally {
    isUploading.value = false;
    if (pdfInputRef.value) pdfInputRef.value.value = "";
  }
}

async function sendChat() {
  const question = chatQuestion.value.trim();
  if (!question || chatSending.value) return;

  const runtime = collectSettings();
  chatMessages.value.push({
    id: nextMessageId(),
    role: "user",
    text: question,
    meta: "You",
  });
  chatQuestion.value = "";
  chatSending.value = true;
  expandCopilot();

  try {
    const commandHandled = await handleDeleteCommand(question);
    if (commandHandled) return;

    const resp = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        selected_doc_id: selectedDocDocId.value,
        selected_version_id: selectedDocVersionId.value,
        llm_provider: runtime.llm_provider,
        llm_api_key: runtime.llm_api_key,
        llm_model: runtime.llm_model,
        llm_base_url: runtime.llm_base_url,
        embedding_provider: runtime.embedding_provider,
        embedding_api_key: runtime.embedding_api_key,
        embedding_model: runtime.embedding_model,
        embedding_base_url: runtime.embedding_base_url,
        rerank_provider: runtime.rerank_provider,
        rerank_api_key: runtime.rerank_api_key,
        rerank_model: runtime.rerank_model,
        rerank_base_url: runtime.rerank_base_url,
      }),
    });
    if (!resp.ok) throw new Error(`${resp.status}`);
    const data = await resp.json();
    const citations = Array.isArray(data.citations) ? data.citations : [];
    const lines = [data.answer || "（无回答）", "", `引用数: ${citations.length}`];
    if (citations.length > 0) {
      citations.slice(0, 3).forEach((item, idx) => {
        lines.push(`${idx + 1}. ${item.doc_name || "unknown"} p.${item.page_start || "-"}`);
      });
    }
    pushAssistantMessage(lines.join("\n"), `${data.llm?.provider || "-"} / ${data.llm?.model || "-"}`);
  } catch (error) {
    pushAssistantMessage(`调用失败：${error.message}`);
  } finally {
    chatSending.value = false;
  }
}

function onGlobalKeydown(event) {
  const key = String(event.key || "").toLowerCase();
  if ((event.metaKey || event.ctrlKey) && key === "j") {
    event.preventDefault();
    toggleCopilot();
  }
}

function onGlobalPointerDown(event) {
  const target = event.target;
  if (!(target instanceof Element)) return;
  if (target.closest(".copilot-dock")) return;
  collapseCopilot();
}

function onGlobalFocusIn(event) {
  const target = event.target;
  if (!(target instanceof Element)) return;
  if (target.closest(".copilot-dock")) return;
  collapseCopilot();
}

onMounted(async () => {
  const savedSettings = readSettings();
  applySettings(savedSettings);
  if (!hasRuntimeSettings(savedSettings)) {
    settingsDrawerOpen.value = true;
  }
  pushAssistantMessage("你好，我在右侧栏协助你完成文档调试。快捷键：⌘/Ctrl + J");
  window.addEventListener("keydown", onGlobalKeydown);
  window.addEventListener("pointerdown", onGlobalPointerDown, true);
  window.addEventListener("focusin", onGlobalFocusIn, true);
  await Promise.all([loadDocuments(), loadLLMQuality()]);
});

onBeforeUnmount(() => {
  window.removeEventListener("keydown", onGlobalKeydown);
  window.removeEventListener("pointerdown", onGlobalPointerDown, true);
  window.removeEventListener("focusin", onGlobalFocusIn, true);
});
</script>
