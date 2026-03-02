import { toRuntimePayload } from "./runtimeSettings.js";

export function buildConnectivityRequest({ target, draftSettings = null, storedSettings = null } = {}) {
  const source = draftSettings && typeof draftSettings === "object" ? draftSettings : storedSettings;
  return {
    target,
    ...toRuntimePayload(source || {}),
  };
}

export function resolveConnectivityMessage({ ok, payload, status } = {}) {
  const body = payload && typeof payload === "object" ? payload : {};
  if (typeof body.message === "string" && body.message.trim()) return body.message.trim();
  if (typeof body.detail === "string" && body.detail.trim()) return body.detail.trim();
  if (body.detail && typeof body.detail === "object") {
    const detailMessage = String(body.detail.message || body.detail.detail || "").trim();
    if (detailMessage) return detailMessage;
  }
  if (Number.isFinite(status) && status >= 400) return `联通失败 (HTTP ${status})`;
  return ok ? "联通成功" : "联通失败";
}

