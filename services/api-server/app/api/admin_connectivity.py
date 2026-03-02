"""Admin connectivity test APIs for MinerU and LLM providers."""

from __future__ import annotations

import os
from typing import Any

import requests
from fastapi import APIRouter, Depends

from app.services.auth import ROLE_SYSTEM_ADMIN, require_roles
from app.services.llm_router import LLMRouter

router = APIRouter(
    prefix="/api/admin/connectivity",
    tags=["admin-connectivity"],
    dependencies=[Depends(require_roles([ROLE_SYSTEM_ADMIN]))],
)

_TEST_PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def _s(payload: dict[str, Any], key: str) -> str:
    return str(payload.get(key) or "").strip()


def _fail(target: str, message: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "target": target,
        "message": message,
        "detail": detail or {},
    }


def _ok(target: str, message: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": True,
        "target": target,
        "message": message,
        "detail": detail or {},
    }


def _raise_for_status_with_body(resp: requests.Response) -> None:
    try:
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        body = ""
        try:
            body = str(getattr(resp, "text", "") or "").strip()
        except Exception:  # noqa: BLE001
            body = ""
        if body:
            raise RuntimeError(f"{exc} | body={body[:300]}") from exc
        raise


def _normalize_token(raw: str) -> str:
    token = str(raw or "").strip()
    if token.lower().startswith("bearer "):
        token = token.split(" ", 1)[1].strip()
    return token


def _build_mineru_headers(api_key: str, token: str, json_mode: bool = False) -> dict[str, str]:
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    # Backward-compatible fallback: many MinerU deployments require `token` header.
    token_value = token or api_key
    if token_value:
        headers["token"] = token_value
    if json_mode:
        headers["Content-Type"] = "application/json"
    return headers


def _extract_api_error(body: Any) -> str:
    if not isinstance(body, dict):
        return ""
    if body.get("success") is False:
        return str(body.get("msg") or body.get("message") or body.get("msgCode") or "request failed").strip()
    code = body.get("code")
    if code not in (None, 0, "0"):
        return str(body.get("msg") or body.get("message") or code).strip()
    return ""


def _pick_upload_url(body: Any) -> str:
    if not isinstance(body, dict):
        return ""
    data = body.get("data")
    if not isinstance(data, dict):
        return ""

    items: list[Any] = []
    for key in ("file_urls", "fileUrls", "files"):
        value = data.get(key)
        if isinstance(value, list):
            items.extend(value)

    for item in items:
        if isinstance(item, str) and item.strip():
            return item.strip()
        if isinstance(item, dict):
            for k in ("url", "upload_url", "uploadUrl", "presigned_url", "presignedUrl", "put_url", "putUrl"):
                val = str(item.get(k) or "").strip()
                if val:
                    return val
    return ""


def _test_mineru(payload: dict[str, Any]) -> dict[str, Any]:
    base = _s(payload, "mineru_api_base").rstrip("/")
    api_key = _normalize_token(_s(payload, "mineru_api_key"))
    token = _s(payload, "mineru_token")
    if not base:
        return _fail(target="mineru", message="mineru_api_base 不能为空")

    headers = _build_mineru_headers(api_key=api_key, token=token, json_mode=False)

    if "/api/v4" in base:
        json_headers = _build_mineru_headers(api_key=api_key, token=token, json_mode=True)
        api_root = f"{base.split('/api/v4', 1)[0]}/api/v4"
        # Use file-urls/batch to verify auth — allocates a pre-signed URL without
        # actually parsing anything (no quota consumed). This is the same endpoint
        # used by the actual parser (mineru_client.py → _parse_pdf_v4_cloud).
        endpoint = f"{api_root}/file-urls/batch"
        try:
            resp = requests.post(
                endpoint,
                headers=json_headers,
                json={"files": [{"name": "connectivity_test.pdf", "is_ocr": False}]},
                timeout=float(os.getenv("MINERU_HTTP_TIMEOUT_S", "30")),  # nosec B113
            )
            _raise_for_status_with_body(resp)
            body = resp.json()
            api_error = _extract_api_error(body)
            if api_error:
                raise RuntimeError(api_error)
            upload_url = _pick_upload_url(body)
            if not upload_url:
                raise RuntimeError("MinerU 返回上传地址为空")
        except Exception as exc:  # noqa: BLE001
            return _fail(
                target="mineru",
                message=f"MinerU 联通失败: {exc}",
                detail={
                    "endpoint": endpoint,
                    "mode": "cloud_v4",
                    "auth_header_present": bool(api_key),
                    "token_header_present": bool(token or api_key),
                },
            )
        return _ok(
            target="mineru",
            message="MinerU 联通成功",
            detail={
                "endpoint": endpoint,
                "mode": "cloud_v4",
                "auth_header_present": bool(api_key),
                "token_header_present": bool(token or api_key),
                "status_code": int(getattr(resp, "status_code", 200)),
            },
        )

    try:
        resp = requests.post(
            f"{base}/parse",
            headers=headers,
            files={"file": ("connectivity.pdf", _TEST_PDF_BYTES, "application/pdf")},
            timeout=float(os.getenv("MINERU_HTTP_TIMEOUT_S", "30")),  # nosec B113
        )
        _raise_for_status_with_body(resp)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            target="mineru",
            message=f"MinerU 联通失败: {exc}",
            detail={
                "endpoint": base,
                "mode": "parse_upload",
                "auth_header_present": bool(api_key),
                "token_header_present": bool(token or api_key),
            },
        )

    return _ok(
        target="mineru",
        message="MinerU 联通成功",
        detail={
            "endpoint": base,
            "mode": "parse_upload",
            "auth_header_present": bool(api_key),
            "token_header_present": bool(token or api_key),
            "status_code": int(getattr(resp, "status_code", 200)),
        },
    )


def _test_llm(payload: dict[str, Any]) -> dict[str, Any]:
    runtime_config = {
        "llm_provider": _s(payload, "llm_provider").lower(),
        "llm_api_key": _s(payload, "llm_api_key"),
        "llm_model": _s(payload, "llm_model"),
        "llm_base_url": _s(payload, "llm_base_url"),
    }
    runtime_config = {k: v for k, v in runtime_config.items() if v}

    requested_provider = str(runtime_config.get("llm_provider") or os.getenv("LLM_PROVIDER", "auto")).lower().strip()
    if requested_provider not in {"openai", "anthropic", "stub"}:
        return _fail(
            target="llm",
            message=f"llm_provider 不支持: {requested_provider or 'empty'}",
            detail={"requested_provider": requested_provider},
        )

    llm = LLMRouter()
    try:
        res = llm.route_and_generate(
            task_type="qa_generate",
            prompt="连通性测试：请仅回复 OK",
            runtime_config=runtime_config,
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(
            target="llm",
            message=f"LLM 联通失败: {exc}",
            detail={"requested_provider": requested_provider},
        )

    actual_provider = str(res.get("provider") or "").lower().strip()
    if requested_provider in {"openai", "anthropic"} and actual_provider != requested_provider:
        last_error = ""
        if llm.call_logs:
            last_error = str((llm.call_logs[-1] or {}).get("error") or "").strip()
        detail = {
            "requested_provider": requested_provider,
            "actual_provider": actual_provider or "unknown",
            "model": res.get("model"),
            "latency_ms": res.get("latency_ms"),
        }
        message = f"LLM 联通失败: 请求 {requested_provider}，实际返回 {detail['actual_provider']}"
        if last_error:
            message = f"{message} ({last_error})"
            detail["error"] = last_error
        return _fail(target="llm", message=message, detail=detail)

    return _ok(
        target="llm",
        message="LLM 联通成功",
        detail={
            "provider": actual_provider or requested_provider,
            "model": res.get("model"),
            "latency_ms": res.get("latency_ms"),
        },
    )


def _test_embedding(payload: dict[str, Any]) -> dict[str, Any]:
    provider = _s(payload, "embedding_provider").lower() or "stub"
    api_key = _normalize_token(_s(payload, "embedding_api_key") or _s(payload, "llm_api_key"))
    model = _s(payload, "embedding_model") or "text-embedding-3-small"
    base_url = (_s(payload, "embedding_base_url") or _s(payload, "llm_base_url") or "https://api.openai.com/v1").rstrip("/")

    if provider == "stub":
        return _ok(target="embedding", message="Embedding 联通成功(stub)", detail={"provider": "stub"})
    if provider != "openai":
        return _fail(target="embedding", message=f"embedding_provider 不支持: {provider}", detail={"provider": provider})
    if not api_key:
        return _fail(target="embedding", message="embedding_api_key 不能为空", detail={"provider": provider})

    try:
        resp = requests.post(
            f"{base_url}/embeddings",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "input": "connectivity-test"},
            timeout=float(os.getenv("EMBEDDING_HTTP_TIMEOUT_S", "15")),  # nosec B113
        )
        _raise_for_status_with_body(resp)
        data = resp.json()
        vector = (((data.get("data") or [{}])[0]).get("embedding") or [])
        if not isinstance(vector, list) or not vector:
            raise RuntimeError("empty embedding response")
    except Exception as exc:  # noqa: BLE001
        return _fail(
            target="embedding",
            message=f"Embedding 联通失败: {exc}",
            detail={"provider": provider, "model": model, "base_url": base_url},
        )

    return _ok(
        target="embedding",
        message="Embedding 联通成功",
        detail={"provider": provider, "model": model, "base_url": base_url, "dim": len(vector)},
    )


def _test_rerank(payload: dict[str, Any]) -> dict[str, Any]:
    provider = _s(payload, "rerank_provider").lower() or "stub"
    api_key = _normalize_token(_s(payload, "rerank_api_key") or _s(payload, "llm_api_key"))
    model = _s(payload, "rerank_model") or "BAAI/bge-reranker-v2-m3"
    base_url = (_s(payload, "rerank_base_url") or _s(payload, "llm_base_url") or "https://api.openai.com/v1").rstrip("/")

    if provider in {"stub", "local"}:
        return _ok(target="rerank", message=f"Rerank 联通成功({provider})", detail={"provider": provider})
    if provider != "openai":
        return _fail(target="rerank", message=f"rerank_provider 不支持: {provider}", detail={"provider": provider})
    if not api_key:
        return _fail(target="rerank", message="rerank_api_key 不能为空", detail={"provider": provider})

    payload_json = {
        "model": model,
        "query": "connectivity test",
        "documents": ["doc-a", "doc-b"],
        "top_n": 2,
        "return_documents": False,
    }
    endpoints = [f"{base_url}/rerank"]
    if not base_url.endswith("/v1"):
        endpoints.append(f"{base_url}/v1/rerank")

    try:
        body = {}
        for endpoint in endpoints:
            resp = requests.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload_json,
                timeout=float(os.getenv("RERANK_HTTP_TIMEOUT_S", "20")),  # nosec B113
            )
            _raise_for_status_with_body(resp)
            body = resp.json()
            results = body.get("results")
            if not isinstance(results, list):
                results = body.get("data")
            if isinstance(results, list):
                break
        else:
            raise RuntimeError("rerank 响应缺少 results/data 字段")
    except Exception as exc:  # noqa: BLE001
        return _fail(
            target="rerank",
            message=f"Rerank 联通失败: {exc}",
            detail={"provider": provider, "model": model, "base_url": base_url},
        )
    return _ok(
        target="rerank",
        message="Rerank 联通成功",
        detail={"provider": provider, "model": model, "base_url": base_url},
    )


def _test_vl(payload: dict[str, Any]) -> dict[str, Any]:
    provider = _s(payload, "vl_provider").lower() or "stub"
    api_key = _normalize_token(_s(payload, "vl_api_key") or _s(payload, "llm_api_key"))
    model = _s(payload, "vl_model") or "gpt-4o-mini"
    base_url = (_s(payload, "vl_base_url") or _s(payload, "llm_base_url") or "https://api.openai.com/v1").rstrip("/")

    if provider == "stub":
        return _ok(target="vl", message="VL 联通成功(stub)", detail={"provider": "stub"})
    if provider != "openai":
        return _fail(target="vl", message=f"vl_provider 不支持: {provider}", detail={"provider": provider})
    if not api_key:
        return _fail(target="vl", message="vl_api_key 不能为空", detail={"provider": provider})

    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": "connectivity test: reply OK"}],
                "temperature": 0,
                "max_tokens": 8,
            },
            timeout=float(os.getenv("LLM_HTTP_TIMEOUT_S", "30")),  # nosec B113
        )
        _raise_for_status_with_body(resp)
        body = resp.json()
        content = (((body.get("choices") or [{}])[0]).get("message") or {}).get("content")
        if not str(content or "").strip():
            raise RuntimeError("empty vl completion response")
    except Exception as exc:  # noqa: BLE001
        return _fail(
            target="vl",
            message=f"VL 联通失败: {exc}",
            detail={"provider": provider, "model": model, "base_url": base_url},
        )

    return _ok(
        target="vl",
        message="VL 联通成功",
        detail={"provider": provider, "model": model, "base_url": base_url},
    )


@router.post("/test")
def test_connectivity(payload: dict | None = None) -> dict[str, Any]:
    req: dict[str, Any] = payload or {}
    target = _s(req, "target").lower()
    if target == "mineru":
        return _test_mineru(req)
    if target == "llm":
        return _test_llm(req)
    if target == "embedding":
        return _test_embedding(req)
    if target == "rerank":
        return _test_rerank(req)
    if target == "vl":
        return _test_vl(req)
    return _fail(target="unknown", message="target 必须是 mineru、llm、embedding、rerank 或 vl")
