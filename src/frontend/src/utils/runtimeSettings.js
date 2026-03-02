const DEFAULT_SETTINGS = {
  ocr_provider: "openai",
  ocr_model: "vlm",
  ocr_base_url: "",
  ocr_api_key: "",
  mineru_api_base: "",
  mineru_api_key: "",
  mineru_model_version: "vlm",
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
};

function clean(value) {
  return String(value || "").trim();
}

function firstNonEmpty(...values) {
  for (const value of values) {
    if (clean(value)) return clean(value);
  }
  return "";
}

function normalizeProvider(value, fallback) {
  const provider = clean(value).toLowerCase();
  return provider || fallback;
}

export function normalizeRuntimeSettings(payload) {
  const source = payload && typeof payload === "object" ? payload : {};
  const legacyMineruBase = clean(source.mineru_api_base);
  const legacyMineruKey = clean(source.mineru_api_key);
  const legacyMineruModel = clean(source.mineru_model_version);

  const ocrBase = firstNonEmpty(source.ocr_base_url, legacyMineruBase);
  const ocrKey = firstNonEmpty(source.ocr_api_key, legacyMineruKey);
  const ocrModel = firstNonEmpty(source.ocr_model, legacyMineruModel, DEFAULT_SETTINGS.ocr_model);

  return {
    ...DEFAULT_SETTINGS,
    ocr_provider: normalizeProvider(source.ocr_provider, DEFAULT_SETTINGS.ocr_provider),
    ocr_model: ocrModel,
    ocr_base_url: ocrBase,
    ocr_api_key: ocrKey,
    // Keep legacy mineru_* fields synced with OCR fields; OCR input must win.
    mineru_api_base: firstNonEmpty(ocrBase, legacyMineruBase),
    mineru_api_key: firstNonEmpty(ocrKey, legacyMineruKey),
    mineru_model_version: firstNonEmpty(ocrModel, legacyMineruModel, DEFAULT_SETTINGS.mineru_model_version),
    llm_provider: normalizeProvider(source.llm_provider, DEFAULT_SETTINGS.llm_provider),
    llm_model: firstNonEmpty(source.llm_model, DEFAULT_SETTINGS.llm_model),
    llm_base_url: firstNonEmpty(source.llm_base_url, DEFAULT_SETTINGS.llm_base_url),
    llm_api_key: clean(source.llm_api_key),
    embedding_provider: normalizeProvider(source.embedding_provider, DEFAULT_SETTINGS.embedding_provider),
    embedding_model: firstNonEmpty(source.embedding_model, DEFAULT_SETTINGS.embedding_model),
    embedding_base_url: firstNonEmpty(source.embedding_base_url, DEFAULT_SETTINGS.embedding_base_url),
    embedding_api_key: clean(source.embedding_api_key),
    rerank_provider: normalizeProvider(source.rerank_provider, DEFAULT_SETTINGS.rerank_provider),
    rerank_model: firstNonEmpty(source.rerank_model, DEFAULT_SETTINGS.rerank_model),
    rerank_base_url: firstNonEmpty(source.rerank_base_url, DEFAULT_SETTINGS.rerank_base_url),
    rerank_api_key: clean(source.rerank_api_key),
    vl_provider: normalizeProvider(source.vl_provider, DEFAULT_SETTINGS.vl_provider),
    vl_model: firstNonEmpty(source.vl_model, DEFAULT_SETTINGS.vl_model),
    vl_base_url: firstNonEmpty(source.vl_base_url, DEFAULT_SETTINGS.vl_base_url),
    vl_api_key: clean(source.vl_api_key),
  };
}

export function toRuntimePayload(settings) {
  const normalized = normalizeRuntimeSettings(settings);
  return {
    ocr_provider: normalized.ocr_provider,
    ocr_model: normalized.ocr_model,
    ocr_base_url: normalized.ocr_base_url,
    ocr_api_key: normalized.ocr_api_key,
    mineru_api_base: normalized.ocr_base_url || normalized.mineru_api_base,
    mineru_api_key: normalized.ocr_api_key || normalized.mineru_api_key,
    mineru_model_version: normalized.ocr_model || normalized.mineru_model_version,
    llm_provider: normalized.llm_provider,
    llm_model: normalized.llm_model,
    llm_base_url: normalized.llm_base_url,
    llm_api_key: normalized.llm_api_key,
    embedding_provider: normalized.embedding_provider,
    embedding_model: normalized.embedding_model,
    embedding_base_url: normalized.embedding_base_url,
    embedding_api_key: normalized.embedding_api_key,
    rerank_provider: normalized.rerank_provider,
    rerank_model: normalized.rerank_model,
    rerank_base_url: normalized.rerank_base_url,
    rerank_api_key: normalized.rerank_api_key,
    vl_provider: normalized.vl_provider,
    vl_model: normalized.vl_model,
    vl_base_url: normalized.vl_base_url,
    vl_api_key: normalized.vl_api_key,
  };
}

export function hasRuntimeSettings(payload) {
  const normalized = normalizeRuntimeSettings(payload);
  return Boolean(normalized.ocr_base_url || normalized.ocr_api_key || normalized.llm_api_key || normalized.embedding_api_key);
}
