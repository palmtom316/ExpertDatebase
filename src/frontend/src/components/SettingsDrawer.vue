<template>
  <div v-if="open" class="modal-overlay" @click.self="$emit('close')">
    <div class="modal-dialog" role="dialog" aria-modal="true" aria-label="运行时配置">
      <header class="modal-header">
        <div>
          <h2>运行时配置</h2>
          <p class="hint">全部采用 BYOK：所有模型调用仅使用您填写的 Key。</p>
        </div>
        <button class="btn btn-ghost btn-icon" type="button" @click="$emit('close')" aria-label="关闭">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
        </button>
      </header>

      <div class="settings-tabs" role="tablist">
        <button v-for="tab in tabs" :key="tab" class="tab-btn" :class="{ 'active': activeTab === tab }" @click="activeTab = tab">{{ tab }}</button>
      </div>

      <div class="settings-content">
        <!-- OCR -->
        <article v-if="activeTab === 'OCR'" class="settings-form">
          <div class="form-header"><h3>OCR 文档解析</h3></div>
          <div class="form-grid">
            <label class="form-field"><span>Provider</span>
              <select v-model="local.ocr_provider">
                <option value="openai">openai-compatible</option>
                <option value="siliconflow">siliconflow</option>
                <option value="mineru">mineru</option>
              </select>
            </label>
            <label class="form-field"><span>Model</span><input v-model.trim="local.ocr_model" placeholder="deepseek-ai/DeepSeek-OCR / vlm" /></label>
            <label class="form-field"><span>API Base</span><input v-model.trim="local.ocr_base_url" placeholder="https://api.siliconflow.cn/v1 或 https://mineru.net/api/v4/extract/task" /></label>
            <label class="form-field"><span>API Key</span><input v-model.trim="local.ocr_api_key" type="password" placeholder="ocr-key" /></label>
          </div>
          <div class="form-actions">
            <button class="btn btn-secondary" type="button" :disabled="connState.mineru.loading" @click="triggerTestConn('mineru')">
              {{ connState.mineru.loading ? "CHECKING..." : "API CHECK" }}
            </button>
            <span class="conn-badge" :class="connClass(connState.mineru.ok)">{{ connState.mineru.message }}</span>
            <div class="spacer"></div>
            <button class="btn btn-primary" type="button" @click="save">保存应用</button>
          </div>
        </article>

        <!-- QA -->
        <article v-if="activeTab === 'QA'" class="settings-form">
          <div class="form-header"><h3>问答生成模型</h3></div>
          <div class="form-grid">
            <label class="form-field"><span>QA Provider</span>
              <select v-model="local.llm_provider"><option value="stub">stub</option><option value="openai">openai</option><option value="anthropic">anthropic</option></select>
            </label>
            <label class="form-field"><span>QA Model</span><input v-model.trim="local.llm_model" placeholder="gpt-4o-mini" /></label>
            <label class="form-field"><span>QA API Base</span><input v-model.trim="local.llm_base_url" placeholder="https://api.openai.com/v1" /></label>
            <label class="form-field"><span>QA API Key</span><input v-model.trim="local.llm_api_key" type="password" placeholder="llm-key" /></label>
          </div>
          <div class="form-actions">
            <button class="btn btn-secondary" type="button" :disabled="connState.llm.loading" @click="triggerTestConn('llm')">{{ connState.llm.loading ? "CHECKING..." : "API CHECK" }}</button>
            <span class="conn-badge" :class="connClass(connState.llm.ok)">{{ connState.llm.message }}</span>
            <div class="spacer"></div>
            <button class="btn btn-primary" type="button" @click="save">保存应用</button>
          </div>
        </article>

        <!-- EMBEDDING -->
        <article v-if="activeTab === 'EMBEDDING'" class="settings-form">
          <div class="form-header"><h3>向量化模型</h3></div>
          <div class="form-grid">
            <label class="form-field"><span>Provider</span>
              <select v-model="local.embedding_provider"><option value="auto">auto</option><option value="openai">openai</option><option value="siliconflow">siliconflow</option><option value="stub">stub</option></select>
            </label>
            <label class="form-field"><span>Model</span><input v-model.trim="local.embedding_model" placeholder="Qwen/Qwen3-Embedding-8B" /></label>
            <label class="form-field"><span>API Base</span><input v-model.trim="local.embedding_base_url" placeholder="https://api.siliconflow.cn/v1" /></label>
            <label class="form-field"><span>API Key</span><input v-model.trim="local.embedding_api_key" type="password" placeholder="embedding-key" /></label>
            <label class="form-field"><span>Dimensions</span><input v-model.trim="local.embedding_dimensions" placeholder="4096" /></label>
          </div>
          <div class="form-actions">
            <button class="btn btn-secondary" type="button" :disabled="connState.embedding.loading" @click="triggerTestConn('embedding')">{{ connState.embedding.loading ? "CHECKING..." : "API CHECK" }}</button>
            <span class="conn-badge" :class="connClass(connState.embedding.ok)">{{ connState.embedding.message }}</span>
            <div class="spacer"></div>
            <button class="btn btn-primary" type="button" @click="save">保存应用</button>
          </div>
        </article>

        <!-- RERANK -->
        <article v-if="activeTab === 'RERANK'" class="settings-form">
          <div class="form-header"><h3>重排模型 (可选)</h3></div>
          <div class="form-grid">
            <label class="form-field"><span>Provider</span>
              <select v-model="local.rerank_provider"><option value="auto">auto</option><option value="openai">openai</option><option value="siliconflow">siliconflow</option><option value="local">local</option><option value="stub">stub</option></select>
            </label>
            <label class="form-field"><span>Model</span><input v-model.trim="local.rerank_model" placeholder="Qwen/Qwen3-Reranker-8B" /></label>
            <label class="form-field"><span>API Base</span><input v-model.trim="local.rerank_base_url" placeholder="https://api.siliconflow.cn/v1" /></label>
            <label class="form-field"><span>API Key</span><input v-model.trim="local.rerank_api_key" type="password" placeholder="rerank-key" /></label>
          </div>
          <div class="form-actions">
            <button class="btn btn-secondary" type="button" :disabled="connState.rerank.loading" @click="triggerTestConn('rerank')">{{ connState.rerank.loading ? "CHECKING..." : "API CHECK" }}</button>
            <span class="conn-badge" :class="connClass(connState.rerank.ok)">{{ connState.rerank.message }}</span>
            <div class="spacer"></div>
            <button class="btn btn-primary" type="button" @click="save">保存应用</button>
          </div>
        </article>

        <!-- VL -->
        <article v-if="activeTab === 'VL'" class="settings-form">
          <div class="form-header"><h3>图像/表格识别 (可选)</h3></div>
          <div class="form-grid">
            <label class="form-field"><span>Provider</span>
              <select v-model="local.vl_provider"><option value="stub">stub</option><option value="openai">openai</option><option value="siliconflow">siliconflow</option></select>
            </label>
            <label class="form-field"><span>Model</span><input v-model.trim="local.vl_model" placeholder="Qwen/Qwen3-VL-8B-Instruct" /></label>
            <label class="form-field"><span>API Base</span><input v-model.trim="local.vl_base_url" placeholder="https://api.siliconflow.cn/v1" /></label>
            <label class="form-field"><span>API Key</span><input v-model.trim="local.vl_api_key" type="password" placeholder="vl-key" /></label>
          </div>
          <div class="form-actions">
            <button class="btn btn-secondary" type="button" :disabled="connState.vl.loading" @click="triggerTestConn('vl')">{{ connState.vl.loading ? "CHECKING..." : "API CHECK" }}</button>
            <span class="conn-badge" :class="connClass(connState.vl.ok)">{{ connState.vl.message }}</span>
            <div class="spacer"></div>
            <button class="btn btn-primary" type="button" @click="save">保存应用</button>
          </div>
        </article>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref, watch } from "vue";

const props = defineProps({
  open: { type: Boolean, default: false },
  modelValue: { type: Object, required: true },
  connState: { type: Object, required: true },
});

const emit = defineEmits(["close", "save", "testConn", "update:modelValue"]);

const tabs = ["OCR", "QA", "EMBEDDING", "RERANK", "VL"];
const activeTab = ref("OCR");

const local = reactive({ ...props.modelValue });

watch(() => props.modelValue, (val) => { Object.assign(local, val); }, { deep: true });

function connClass(ok) {
  if (ok === true) return "conn-ok";
  if (ok === false) return "conn-fail";
  return "";
}

function save() {
  emit("update:modelValue", { ...local });
  emit("save");
}

function triggerTestConn(target) {
  emit("testConn", target, { ...local });
}
</script>
