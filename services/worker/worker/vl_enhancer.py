"""Visual asset enhancement (image/table/cross-page table) with optional VL model."""

from __future__ import annotations

import os
from typing import Any

import requests


def _norm_text(value: Any, limit: int = 2000) -> str:
    text = str(value or "").replace("\x00", " ").strip()
    if not text:
        return ""
    return " ".join(text.split())[:limit]


def _pick_image_url(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if not isinstance(item, dict):
        return ""
    for key in ("url", "image_url", "src", "image", "path"):
        val = str(item.get(key) or "").strip()
        if val:
            return val
    return ""


def _is_cross_page_table(raw_text: str) -> bool:
    lower = raw_text.lower()
    marks = ["续表", "continued", "cont."]
    return any(mark in lower for mark in marks)


def extract_visual_candidates(mineru_result: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    pages = mineru_result.get("pages")
    if not isinstance(pages, list):
        return out

    for page_index, page in enumerate(pages, start=1):
        if not isinstance(page, dict):
            continue
        page_no = int(page.get("page_no") or page_index)

        tables = page.get("tables")
        if isinstance(tables, list):
            for idx, table in enumerate(tables, start=1):
                raw = _norm_text((table or {}).get("raw_text") if isinstance(table, dict) else table)
                if not raw:
                    continue
                visual_type = "cross_page_table" if _is_cross_page_table(raw) else "table"
                out.append(
                    {
                        "visual_type": visual_type,
                        "page_no": page_no,
                        "source": "table",
                        "table_idx": idx,
                        "text_hint": raw[:800],
                        "image_url": _pick_image_url(table),
                    }
                )

        blocks = page.get("blocks")
        if isinstance(blocks, list):
            for idx, block in enumerate(blocks, start=1):
                if not isinstance(block, dict):
                    continue
                block_type = str(block.get("type") or "").strip().lower()
                if block_type not in {"image", "figure", "chart", "diagram"}:
                    continue
                caption = _norm_text(block.get("text") or block.get("caption"), limit=800)
                out.append(
                    {
                        "visual_type": "image",
                        "page_no": page_no,
                        "source": "block",
                        "block_idx": idx,
                        "text_hint": caption,
                        "image_url": _pick_image_url(block),
                    }
                )

        images = page.get("images")
        if isinstance(images, list):
            for idx, image in enumerate(images, start=1):
                caption = _norm_text((image or {}).get("caption") if isinstance(image, dict) else "", limit=800)
                out.append(
                    {
                        "visual_type": "image",
                        "page_no": page_no,
                        "source": "images",
                        "image_idx": idx,
                        "text_hint": caption,
                        "image_url": _pick_image_url(image),
                    }
                )

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str, str]] = set()
    for item in out:
        key = (
            str(item.get("visual_type") or ""),
            int(item.get("page_no") or 0),
            str(item.get("image_url") or ""),
            str(item.get("text_hint") or "")[:120],
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:120]


class VLRecognizer:
    def __init__(self) -> None:
        self.timeout_s = float(os.getenv("VL_HTTP_TIMEOUT_S", "30"))

    def _default_base_url(self, provider: str) -> str:
        if provider == "siliconflow":
            return "https://api.siliconflow.cn/v1"
        return "https://api.openai.com/v1"

    def _default_model(self, provider: str) -> str:
        if provider == "siliconflow":
            return "Qwen/Qwen2.5-VL-7B-Instruct"
        return "gpt-4o-mini"

    def _normalize_token(self, raw: str) -> str:
        token = str(raw or "").strip()
        if token.lower().startswith("bearer "):
            token = token.split(" ", 1)[1].strip()
        return token

    def _resolve_runtime(self, runtime_config: dict[str, Any] | None) -> dict[str, str]:
        runtime = runtime_config or {}
        provider = str(runtime.get("vl_provider") or runtime.get("llm_provider") or os.getenv("VL_PROVIDER", "stub")).strip().lower()
        default_base_url = self._default_base_url(provider)
        default_model = self._default_model(provider)
        api_key = self._normalize_token(str(runtime.get("vl_api_key") or runtime.get("llm_api_key") or os.getenv("VL_API_KEY", "")))
        base_url = str(
            runtime.get("vl_base_url")
            or runtime.get("llm_base_url")
            or os.getenv("VL_BASE_URL")
            or os.getenv("OPENAI_BASE_URL", default_base_url)
        ).strip()
        model = str(
            runtime.get("vl_model")
            or os.getenv("VL_MODEL")
            or runtime.get("llm_model")
            or os.getenv("OPENAI_MODEL", default_model)
        ).strip()
        return {
            "provider": provider,
            "api_key": api_key,
            "base_url": base_url.rstrip("/"),
            "model": model,
        }

    def _prompt_for_task(self, task: str, visual_type: str, text_hint: str) -> str:
        if task == "table_repair":
            return (
                "你是投标文档表格修复助手。请把表格信息输出为可切分的行文本："
                "第一行为表头，后续行为数据行；优先使用竖线'|'分隔列；"
                "不要输出解释、不要使用Markdown代码块。"
                f"视觉类型={visual_type}。已知提示：{text_hint or '无'}"
            )
        return (
            "你是投标文档解析助手。请识别并提取该视觉片段的关键信息，"
            f"视觉类型={visual_type}。输出简洁中文文本，不要解释。已知提示：{text_hint or '无'}"
        )

    def _estimate_confidence(self, task: str, text: str, fallback_reason: str) -> float:
        if fallback_reason:
            return 0.0
        if not text:
            return 0.0
        if task == "table_repair":
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if len(lines) >= 2 and any("|" in line for line in lines):
                return 0.85
            if len(lines) >= 2:
                return 0.6
            return 0.35
        return 0.75

    def _request_once(self, candidate: dict[str, Any], cfg: dict[str, str], task: str, timeout_s: float) -> str:
        visual_type = str(candidate.get("visual_type") or "visual")
        text_hint = _norm_text(candidate.get("text_hint"), limit=1000)
        image_url = str(candidate.get("image_url") or "").strip()

        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": self._prompt_for_task(task=task, visual_type=visual_type, text_hint=text_hint),
            }
        ]
        if image_url:
            content.append({"type": "image_url", "image_url": {"url": image_url}})

        resp = requests.post(
            f"{cfg['base_url']}/chat/completions",
            headers={"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"},
            json={
                "model": cfg["model"],
                "messages": [{"role": "user", "content": content}],
                "temperature": 0,
            },
            timeout=timeout_s,
        )
        resp.raise_for_status()
        body = resp.json()
        text = (
            (((body.get("choices") or [{}])[0]).get("message") or {}).get("content")
            if isinstance(body, dict)
            else ""
        )
        return _norm_text(text, limit=1600)

    def enhance(
        self,
        candidates: list[dict[str, Any]],
        runtime_config: dict[str, Any] | None = None,
        task: str = "visual_summary",
        max_items: int | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        cfg = self._resolve_runtime(runtime_config=runtime_config)
        env_max = max(1, int(os.getenv("VL_MAX_ITEMS_PER_DOC", "40")))
        limit = max(1, int(max_items)) if max_items is not None else env_max
        limited = candidates[:limit]
        req_timeout = float(timeout_s) if timeout_s is not None else self.timeout_s

        if cfg["provider"] in {"", "stub"} or not cfg["api_key"]:
            items = []
            for item in limited:
                recognized_text = _norm_text(item.get("text_hint"), limit=1600)
                fallback_reason = "provider_disabled_or_missing_key"
                items.append(
                    {
                        **item,
                        "recognized_text": recognized_text,
                        "confidence": self._estimate_confidence(task=task, text=recognized_text, fallback_reason=fallback_reason),
                        "fallback_reason": fallback_reason,
                    }
                )
            return {
                "enabled": False,
                "provider": cfg["provider"] or "stub",
                "model": cfg["model"] or "",
                "task": task,
                "items": items,
            }

        items: list[dict[str, Any]] = []
        for item in limited:
            fallback_reason = ""
            try:
                text = self._request_once(item, cfg, task=task, timeout_s=req_timeout)
            except Exception:  # noqa: BLE001
                text = _norm_text(item.get("text_hint"), limit=1600)
                fallback_reason = "request_error"
            items.append(
                {
                    **item,
                    "recognized_text": text,
                    "confidence": self._estimate_confidence(task=task, text=text, fallback_reason=fallback_reason),
                    "fallback_reason": fallback_reason,
                }
            )
        return {
            "enabled": True,
            "provider": cfg["provider"],
            "model": cfg["model"],
            "task": task,
            "items": items,
        }


def merge_visual_text_into_mineru(mineru_result: dict[str, Any], recognized_items: list[dict[str, Any]]) -> dict[str, Any]:
    pages = mineru_result.get("pages")
    if not isinstance(pages, list):
        return mineru_result

    page_map: dict[int, dict[str, Any]] = {}
    for idx, page in enumerate(pages, start=1):
        if not isinstance(page, dict):
            continue
        page_no = int(page.get("page_no") or idx)
        page.setdefault("blocks", [])
        page.setdefault("tables", [])
        page_map[page_no] = page

    for item in recognized_items:
        page_no = int(item.get("page_no") or 0)
        text = _norm_text(item.get("recognized_text"), limit=1800)
        if not text:
            continue
        visual_type = str(item.get("visual_type") or "visual")
        page = page_map.get(page_no)
        if page is None:
            continue

        marker = f"[VL-{visual_type}] {text}"
        blocks = page.get("blocks")
        if isinstance(blocks, list):
            exists = any(str((b or {}).get("text") or "").strip() == marker for b in blocks if isinstance(b, dict))
            if not exists:
                blocks.append({"type": "paragraph", "text": marker})

        if visual_type in {"table", "cross_page_table"}:
            tables = page.get("tables")
            if isinstance(tables, list):
                tables.append({"raw_text": marker})

    return mineru_result
