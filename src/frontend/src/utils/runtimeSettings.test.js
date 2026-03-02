import test from "node:test";
import assert from "node:assert/strict";
import { hasRuntimeSettings, normalizeRuntimeSettings, toRuntimePayload } from "./runtimeSettings.js";

test("normalizes ocr openai-compatible fields and backfills legacy mineru fields", () => {
  const normalized = normalizeRuntimeSettings({
    ocr_provider: "openai",
    ocr_model: "gpt-4o-mini",
    ocr_base_url: "https://ocr.example.com/v1",
    ocr_api_key: "ocr-key",
  });

  assert.equal(normalized.ocr_provider, "openai");
  assert.equal(normalized.ocr_model, "gpt-4o-mini");
  assert.equal(normalized.mineru_api_base, "https://ocr.example.com/v1");
  assert.equal(normalized.mineru_api_key, "ocr-key");
  assert.equal(normalized.mineru_model_version, "gpt-4o-mini");
});

test("normalizes legacy mineru fields into ocr fields for backward compatibility", () => {
  const normalized = normalizeRuntimeSettings({
    mineru_api_base: "https://mineru.net/api/v4/extract/task",
    mineru_api_key: "legacy-token",
    mineru_model_version: "vlm",
  });

  assert.equal(normalized.ocr_base_url, "https://mineru.net/api/v4/extract/task");
  assert.equal(normalized.ocr_api_key, "legacy-token");
  assert.equal(normalized.ocr_model, "vlm");
});

test("builds runtime payload with both ocr and legacy mineru keys", () => {
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
    })
  );

  assert.equal(payload.ocr_provider, "openai");
  assert.equal(payload.ocr_model, "gpt-4o-mini");
  assert.equal(payload.ocr_base_url, "https://ocr.example.com/v1");
  assert.equal(payload.ocr_api_key, "ocr-key");
  assert.equal(payload.mineru_api_base, "https://ocr.example.com/v1");
  assert.equal(payload.mineru_api_key, "ocr-key");
  assert.equal(payload.mineru_model_version, "gpt-4o-mini");
});

test("prefers OCR fields over stale legacy mineru fields", () => {
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

test("hasRuntimeSettings checks ocr and model API keys", () => {
  assert.equal(hasRuntimeSettings({}), false);
  assert.equal(hasRuntimeSettings({ ocr_api_key: "ocr-key" }), true);
  assert.equal(hasRuntimeSettings({ llm_api_key: "llm-key" }), true);
  assert.equal(hasRuntimeSettings({ embedding_api_key: "emb-key" }), true);
});
