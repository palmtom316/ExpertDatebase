import test from "node:test";
import assert from "node:assert/strict";
import { hasRuntimeSettings, normalizeRuntimeSettings, toRuntimePayload } from "./runtimeSettings.js";

test("uses siliconflow runtime defaults for ocr embedding and rerank", () => {
  const normalized = normalizeRuntimeSettings({});

  assert.equal(normalized.ocr_provider, "siliconflow");
  assert.equal(normalized.ocr_model, "deepseek-ai/DeepSeek-OCR");
  assert.equal(normalized.ocr_base_url, "https://api.siliconflow.cn/v1");
  assert.equal(normalized.embedding_provider, "siliconflow");
  assert.equal(normalized.embedding_model, "Qwen/Qwen3-Embedding-8B");
  assert.equal(normalized.embedding_base_url, "https://api.siliconflow.cn/v1");
  assert.equal(normalized.embedding_dimensions, "4096");
  assert.equal(normalized.rerank_provider, "siliconflow");
  assert.equal(normalized.rerank_model, "Qwen/Qwen3-Reranker-8B");
  assert.equal(normalized.rerank_base_url, "https://api.siliconflow.cn/v1");
});

test("normalizes ocr openai-compatible fields without overwriting legacy mineru fields", () => {
  const normalized = normalizeRuntimeSettings({
    ocr_provider: "openai",
    ocr_model: "gpt-4o-mini",
    ocr_base_url: "https://ocr.example.com/v1",
    ocr_api_key: "ocr-key",
  });

  assert.equal(normalized.ocr_provider, "openai");
  assert.equal(normalized.ocr_model, "gpt-4o-mini");
  assert.equal(normalized.mineru_api_base, "");
  assert.equal(normalized.mineru_api_key, "");
});

test("normalizes legacy mineru fields into ocr fields for backward compatibility", () => {
  const normalized = normalizeRuntimeSettings({
    mineru_api_base: "https://mineru.net/api/v4/extract/task",
    mineru_api_key: "legacy-token",
    mineru_model_version: "vlm",
  });

  assert.equal(normalized.ocr_provider, "mineru");
  assert.equal(normalized.ocr_base_url, "https://mineru.net/api/v4/extract/task");
  assert.equal(normalized.ocr_api_key, "legacy-token");
  assert.equal(normalized.ocr_model, "vlm");
});

test("builds runtime payload without forcing mineru compatibility for openai-compatible ocr", () => {
  const payload = toRuntimePayload(
    normalizeRuntimeSettings({
      ocr_provider: "openai",
      ocr_model: "gpt-4o-mini",
      ocr_base_url: "https://ocr.example.com/v1",
      ocr_api_key: "ocr-key",
      llm_provider: "openai",
      llm_model: "gpt-4o-mini",
      llm_base_url: "https://api.openai.com/v1",
      llm_api_key: "llm-key",
      embedding_dimensions: "1024",
    })
  );

  assert.equal(payload.ocr_provider, "openai");
  assert.equal(payload.ocr_model, "gpt-4o-mini");
  assert.equal(payload.ocr_base_url, "https://ocr.example.com/v1");
  assert.equal(payload.ocr_api_key, "ocr-key");
  assert.equal(payload.mineru_api_base, "");
  assert.equal(payload.mineru_api_key, "");
  assert.equal(payload.embedding_dimensions, "1024");
});

test("prefers OCR fields over stale legacy mineru fields when provider is mineru", () => {
  const normalized = normalizeRuntimeSettings({
    ocr_provider: "mineru",
    ocr_model: "vlm-new",
    ocr_base_url: "https://mineru.net/api/v4/extract/task",
    ocr_api_key: "new-token",
    mineru_api_base: "https://mineru.net/api/v4/extract/task",
    mineru_api_key: "old-token",
    mineru_model_version: "vlm-old",
  });
  const payload = toRuntimePayload(normalized);

  assert.equal(payload.ocr_api_key, "new-token");
  assert.equal(payload.mineru_api_key, "new-token");
  assert.equal(payload.mineru_model_version, "vlm-new");
});

test("keeps siliconflow ocr separate from legacy mineru payload", () => {
  const payload = toRuntimePayload(
    normalizeRuntimeSettings({
      ocr_provider: "siliconflow",
      ocr_model: "deepseek-ai/DeepSeek-OCR",
      ocr_base_url: "https://api.siliconflow.cn/v1",
      ocr_api_key: "sf-key",
      mineru_api_base: "https://mineru.net/api/v4/extract/task",
      mineru_api_key: "legacy-token",
    })
  );

  assert.equal(payload.ocr_provider, "siliconflow");
  assert.equal(payload.mineru_api_base, "https://mineru.net/api/v4/extract/task");
  assert.equal(payload.mineru_api_key, "legacy-token");
});

test("hasRuntimeSettings checks ocr and model API keys", () => {
  assert.equal(hasRuntimeSettings({}), false);
  assert.equal(hasRuntimeSettings({ ocr_api_key: "ocr-key" }), true);
  assert.equal(hasRuntimeSettings({ llm_api_key: "llm-key" }), true);
  assert.equal(hasRuntimeSettings({ embedding_api_key: "emb-key" }), true);
});
