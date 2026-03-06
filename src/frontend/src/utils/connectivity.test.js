import test from "node:test";
import assert from "node:assert/strict";
import { buildConnectivityRequest, resolveConnectivityMessage } from "./connectivity.js";

test("buildConnectivityRequest uses draft OCR settings for api check", () => {
  const request = buildConnectivityRequest({
    target: "mineru",
    draftSettings: {
      ocr_provider: "mineru",
      ocr_model: "vlm",
      ocr_base_url: "https://mineru.net/api/v4/extract/task",
      ocr_api_key: "new-token",
    },
  });

  assert.equal(request.target, "mineru");
  assert.equal(request.ocr_api_key, "new-token");
  assert.equal(request.mineru_api_key, "new-token");
  assert.equal(request.mineru_api_base, "https://mineru.net/api/v4/extract/task");
});

test("buildConnectivityRequest keeps siliconflow OCR separate from mineru fields", () => {
  const request = buildConnectivityRequest({
    target: "mineru",
    draftSettings: {
      ocr_provider: "siliconflow",
      ocr_model: "deepseek-ai/DeepSeek-OCR",
      ocr_base_url: "https://api.siliconflow.cn/v1",
      ocr_api_key: "sf-key",
    },
  });

  assert.equal(request.target, "mineru");
  assert.equal(request.ocr_api_key, "sf-key");
  assert.equal(request.mineru_api_key, "");
  assert.equal(request.mineru_api_base, "");
});

test("resolveConnectivityMessage falls back to detail when message is absent", () => {
  const text = resolveConnectivityMessage({
    ok: false,
    payload: { detail: "forbidden: missing role" },
    status: 403,
  });

  assert.equal(text, "forbidden: missing role");
});
