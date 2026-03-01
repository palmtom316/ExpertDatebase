"""MinerU client adapter (MVP stub)."""

from __future__ import annotations

import io
import json
import os
import re
import time
import zipfile
from typing import Any

import requests


class MinerUClient:
    def _normalize_token(self, raw: str) -> str:
        token = str(raw or "").strip()
        if token.lower().startswith("bearer "):
            token = token.split(" ", 1)[1].strip()
        return token

    def _raise_for_status_with_body(self, resp: requests.Response) -> None:
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

    def _to_pages(self, text: str) -> dict[str, Any]:
        content = str(text or "").strip()
        if not content:
            content = "上传文档内容。"
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if not lines:
            lines = [content[:50000]]

        max_lines = int(os.getenv("MINERU_TO_PAGES_MAX_LINES", "4000"))
        if max_lines > 0:
            lines = lines[:max_lines]
        lines_per_page = max(20, int(os.getenv("MINERU_TO_PAGES_LINES_PER_PAGE", "120")))

        pages: list[dict[str, Any]] = []
        for start in range(0, len(lines), lines_per_page):
            page_no = len(pages) + 1
            page_lines = lines[start : start + lines_per_page]
            blocks = []
            for offset, line in enumerate(page_lines, start=1):
                global_idx = start + offset
                block_type = "title" if global_idx == 1 and len(line) <= 70 else "paragraph"
                blocks.append({"type": block_type, "text": line})
            pages.append({"page_no": page_no, "blocks": blocks, "tables": []})
        return {"pages": pages}

    def _extract_text(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return "\n".join(x for x in (self._extract_text(v) for v in value) if x)
        if isinstance(value, dict):
            parts = [self._extract_text(v) for v in value.values()]
            return "\n".join(x for x in parts if x)
        return ""

    def _html_to_text(self, value: str) -> str:
        text = str(value or "")
        if not text:
            return ""
        text = re.sub(r"</(tr|p|div|li|h[1-6])\s*>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _line_text(self, line: Any, images: list[dict[str, Any]]) -> str:
        if not isinstance(line, dict):
            return ""
        spans = line.get("spans")
        if not isinstance(spans, list):
            return ""
        parts: list[str] = []
        for span in spans:
            if not isinstance(span, dict):
                continue
            span_type = str(span.get("type") or "").strip().lower()
            content = str(span.get("content") or "").strip()
            if span_type == "table":
                html = str(span.get("html") or "").strip()
                if html:
                    content = self._html_to_text(html)
            if span_type in {"text", "inline_equation", "interline_equation", "table"} and content:
                parts.append(content)

            image_url = str(span.get("image_path") or span.get("image_url") or span.get("url") or "").strip()
            if image_url:
                images.append({"url": image_url, "caption": content})
        return " ".join(x for x in parts if x).strip()

    def _block_text(self, block: Any, images: list[dict[str, Any]]) -> str:
        if not isinstance(block, dict):
            return ""
        lines = block.get("lines")
        if isinstance(lines, list) and lines:
            parts = [self._line_text(line, images) for line in lines]
            text = "\n".join(x for x in parts if x).strip()
            if text:
                return text
        return ""

    def _parse_para_blocks(self, para_blocks: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        blocks: list[dict[str, Any]] = []
        tables: list[dict[str, Any]] = []
        images: list[dict[str, Any]] = []

        def walk(node: Any) -> None:
            if not isinstance(node, dict):
                return
            block_type = str(node.get("type") or "paragraph").strip().lower()

            if block_type == "list":
                children = node.get("blocks")
                if isinstance(children, list):
                    for child in children:
                        walk(child)
                text = self._block_text(node, images)
                if text:
                    blocks.append({"type": "paragraph", "text": text})
                return

            if block_type == "table":
                table_parts: list[str] = []
                caption = self._block_text(node, images)
                if caption:
                    table_parts.append(caption)
                    blocks.append({"type": "paragraph", "text": caption})
                children = node.get("blocks")
                if isinstance(children, list):
                    for child in children:
                        child_text = self._block_text(child, images)
                        if child_text:
                            table_parts.append(child_text)
                        child_lines = child.get("lines") if isinstance(child, dict) else None
                        if isinstance(child_lines, list):
                            for line in child_lines:
                                text = self._line_text(line, images)
                                if text:
                                    table_parts.append(text)
                raw_table = "\n".join(x for x in table_parts if x).strip()
                if raw_table:
                    tables.append({"raw_text": raw_table})
                return

            text = self._block_text(node, images)
            if text:
                normalized_type = "title" if block_type == "title" else "paragraph"
                blocks.append({"type": normalized_type, "text": text})

            children = node.get("blocks")
            if isinstance(children, list):
                for child in children:
                    walk(child)

        for block in para_blocks:
            walk(block)
        return blocks, tables, images

    def _normalize_page(self, page: Any, fallback_page_no: int) -> dict[str, Any]:
        if not isinstance(page, dict):
            text = self._extract_text(page)
            return {"page_no": fallback_page_no, "blocks": [{"type": "paragraph", "text": text}], "tables": [], "images": []}

        page_no = int(page.get("page_no") or page.get("page") or page.get("index") or (int(page.get("page_idx") or -1) + 1) or fallback_page_no)
        blocks: list[dict[str, Any]] = []
        tables: list[dict[str, Any]] = []
        images: list[dict[str, Any]] = []

        raw_para_blocks = page.get("para_blocks")
        if isinstance(raw_para_blocks, list) and raw_para_blocks:
            pb_blocks, pb_tables, pb_images = self._parse_para_blocks(raw_para_blocks)
            blocks.extend(pb_blocks)
            tables.extend(pb_tables)
            images.extend(pb_images)

        raw_blocks = page.get("blocks")
        if isinstance(raw_blocks, list):
            for item in raw_blocks:
                if isinstance(item, str):
                    blocks.append({"type": "paragraph", "text": item.strip()})
                    continue
                if not isinstance(item, dict):
                    continue
                block_type = str(item.get("type") or item.get("block_type") or "paragraph").strip().lower()
                text = str(item.get("text") or item.get("content") or item.get("raw_text") or "").strip()
                if not text:
                    text = self._extract_text(item)
                if block_type in {"table", "table_cell"}:
                    tables.append({"raw_text": text})
                    continue
                if block_type in {"image", "figure", "chart", "diagram"}:
                    images.append(
                        {
                            "url": str(item.get("url") or item.get("image_url") or item.get("src") or "").strip(),
                            "caption": text,
                        }
                    )
                blocks.append({"type": block_type or "paragraph", "text": text})

        raw_tables = page.get("tables")
        if isinstance(raw_tables, list):
            for table in raw_tables:
                if isinstance(table, str):
                    tables.append({"raw_text": table.strip()})
                    continue
                if not isinstance(table, dict):
                    continue
                raw_text = str(table.get("raw_text") or table.get("text") or table.get("markdown") or "").strip()
                if not raw_text:
                    raw_text = self._extract_text(table)
                tables.append(
                    {
                        "raw_text": raw_text,
                        "image_url": str(table.get("url") or table.get("image_url") or table.get("src") or "").strip(),
                    }
                )

        raw_images = page.get("images")
        if isinstance(raw_images, list):
            for image in raw_images:
                if isinstance(image, str):
                    images.append({"url": image.strip(), "caption": ""})
                    continue
                if not isinstance(image, dict):
                    continue
                images.append(
                    {
                        "url": str(image.get("url") or image.get("image_url") or image.get("src") or "").strip(),
                        "caption": str(image.get("caption") or image.get("text") or "").strip(),
                    }
                )

        if not blocks:
            text = str(page.get("text") or page.get("md") or page.get("markdown") or "").strip()
            if not text:
                text = self._extract_text(page)
            if text:
                blocks = [{"type": "paragraph", "text": text}]

        return {"page_no": page_no, "blocks": blocks, "tables": tables, "images": images}

    def _to_pages_from_structured_json(self, parsed: Any) -> dict[str, Any] | None:
        candidate_pages: Any = None
        if isinstance(parsed, dict):
            if isinstance(parsed.get("pages"), list):
                candidate_pages = parsed.get("pages")
            elif isinstance(parsed.get("data"), dict) and isinstance(parsed.get("data", {}).get("pages"), list):
                candidate_pages = parsed.get("data", {}).get("pages")
            elif isinstance(parsed.get("pdf_info"), list):
                candidate_pages = parsed.get("pdf_info")
        elif isinstance(parsed, list):
            candidate_pages = parsed

        if not isinstance(candidate_pages, list) or not candidate_pages:
            return None
        normalized_pages = [self._normalize_page(page, idx) for idx, page in enumerate(candidate_pages, start=1)]
        if not normalized_pages:
            return None
        return {"pages": normalized_pages}

    def _extract_api_error(self, body: Any) -> str:
        if not isinstance(body, dict):
            return ""
        if body.get("success") is False:
            return str(body.get("msg") or body.get("message") or body.get("msgCode") or "request failed").strip()
        code = body.get("code")
        if code not in (None, 0, "0"):
            return str(body.get("msg") or body.get("message") or code).strip()
        return ""

    def _pick_upload_url_and_batch_id(self, init_body: Any) -> tuple[str, str]:
        if not isinstance(init_body, dict):
            return "", ""
        data = init_body.get("data")
        if not isinstance(data, dict):
            return "", ""

        batch_id = str(data.get("batch_id") or data.get("batchId") or data.get("id") or "").strip()

        candidates: list[Any] = []
        for key in ("file_urls", "fileUrls", "files"):
            value = data.get(key)
            if isinstance(value, list):
                candidates.extend(value)

        def _pick_url(item: Any) -> str:
            if isinstance(item, str):
                return item.strip()
            if isinstance(item, dict):
                for k in ("url", "upload_url", "uploadUrl", "presigned_url", "presignedUrl", "put_url", "putUrl"):
                    val = str(item.get(k) or "").strip()
                    if val:
                        return val
            return ""

        for item in candidates:
            url = _pick_url(item)
            if url:
                return batch_id, url

        fallback_url = _pick_url(data)
        if fallback_url:
            return batch_id, fallback_url
        return batch_id, ""

    def _parse_zip_payload(self, payload: bytes) -> dict[str, Any]:
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                names = zf.namelist()
                json_files = [n for n in names if n.lower().endswith(".json")]
                for name in sorted(json_files):
                    try:
                        raw = zf.read(name).decode("utf-8", errors="ignore")
                        parsed = json.loads(raw)
                    except Exception:  # noqa: BLE001
                        continue
                    structured = self._to_pages_from_structured_json(parsed)
                    if structured is not None:
                        return structured
                    text = self._extract_text(parsed)
                    if text.strip():
                        return self._to_pages(text)
                md_files = [n for n in names if n.lower().endswith(".md")]
                if md_files:
                    text = zf.read(sorted(md_files)[0]).decode("utf-8", errors="ignore")
                    return self._to_pages(text)
        except zipfile.BadZipFile:
            pass
        return self._to_pages(payload.decode("utf-8", errors="ignore"))

    def _build_headers(self, api_key: str, token: str, json_mode: bool = False) -> dict[str, str]:
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if token:
            headers["token"] = token
        if json_mode:
            headers["Content-Type"] = "application/json"
        return headers

    def _parse_pdf_v4_cloud(
        self,
        base: str,
        api_key: str,
        token: str,
        pdf_bytes: bytes,
        model_version: str,
    ) -> dict[str, Any]:
        timeout = float(os.getenv("MINERU_HTTP_TIMEOUT_S", "30"))
        max_polls = max(1, int(os.getenv("MINERU_CLOUD_MAX_POLLS", "90")))
        poll_interval = max(0.2, float(os.getenv("MINERU_CLOUD_POLL_INTERVAL_S", "2")))
        headers = self._build_headers(api_key=api_key, token=token, json_mode=True)

        api_root = f"{base.split('/api/v4', 1)[0]}/api/v4"
        init_resp = requests.post(
            f"{api_root}/file-urls/batch",
            headers=headers,
            json={"enable_formula": True, "files": [{"name": "upload.pdf", "is_ocr": False}]},
            timeout=timeout,
        )
        self._raise_for_status_with_body(init_resp)
        init_body = init_resp.json()
        init_err = self._extract_api_error(init_body)
        if init_err:
            raise RuntimeError(init_err)
        batch_id, upload_url = self._pick_upload_url_and_batch_id(init_body)
        if not batch_id or not upload_url:
            summary = ""
            if isinstance(init_body, dict):
                data = init_body.get("data")
                if isinstance(data, dict):
                    summary = f" data_keys={sorted(data.keys())}"
            raise RuntimeError(f"MinerU 返回上传地址为空{summary}")

        upload_resp = requests.put(
            upload_url,
            data=pdf_bytes,
            timeout=timeout,
        )
        self._raise_for_status_with_body(upload_resp)

        # MinerU v4 file-urls/batch flow auto-submits parse tasks after PUT upload.
        # Do not call /extract/task/batch here; that endpoint expects `files` payload.
        poll_url = f"{api_root}/extract-results/batch/{batch_id}"
        done_states = {"done", "success", "completed"}
        fail_states = {"failed", "error"}

        for _ in range(max_polls):
            poll_resp = requests.get(poll_url, headers=headers, timeout=timeout)
            self._raise_for_status_with_body(poll_resp)
            poll_body = poll_resp.json()
            poll_err = self._extract_api_error(poll_body)
            if poll_err:
                raise RuntimeError(poll_err or "查询解析结果失败")

            poll_data = poll_body.get("data") if isinstance(poll_body, dict) else {}
            extract_result = (poll_data or {}).get("extract_result") if isinstance(poll_data, dict) else []
            if not isinstance(extract_result, list) or not extract_result:
                time.sleep(poll_interval)
                continue

            states = {str((item or {}).get("state") or "").strip().lower() for item in extract_result if isinstance(item, dict)}
            if any(state in fail_states for state in states):
                raise RuntimeError(f"MinerU 云解析失败: states={sorted(states)}")
            if not all(state in done_states for state in states):
                time.sleep(poll_interval)
                continue

            for item in extract_result:
                if not isinstance(item, dict):
                    continue
                zip_url = str(item.get("full_zip_url") or item.get("zip_url") or "").strip()
                if zip_url:
                    zip_resp = requests.get(zip_url, timeout=timeout)
                    self._raise_for_status_with_body(zip_resp)
                    return self._parse_zip_payload(zip_resp.content)
                md_url = str(item.get("full_md_url") or item.get("md_url") or "").strip()
                if md_url:
                    md_resp = requests.get(md_url, timeout=timeout)
                    self._raise_for_status_with_body(md_resp)
                    return self._to_pages(md_resp.text)
                text = self._extract_text(item)
                if text.strip():
                    return self._to_pages(text)

            return self._to_pages("MinerU 云解析完成，但未返回可读文本。")

        raise TimeoutError("MinerU 云解析超时")

    def parse_pdf(self, pdf_bytes: bytes, runtime_config: dict[str, Any] | None = None) -> dict[str, Any]:
        runtime = runtime_config or {}
        base = str(runtime.get("mineru_api_base") or "").strip().rstrip("/")
        api_key = self._normalize_token(str(runtime.get("mineru_api_key") or "").strip())
        token = str(runtime.get("mineru_token") or "").strip()
        model_version = str(runtime.get("mineru_model_version") or os.getenv("MINERU_MODEL_VERSION", "vlm")).strip() or "vlm"
        if base:
            if "/api/v4" in base:
                return self._parse_pdf_v4_cloud(
                    base=base,
                    api_key=api_key,
                    token=token,
                    pdf_bytes=pdf_bytes,
                    model_version=model_version,
                )
            resp = requests.post(
                f"{base}/parse",
                headers=self._build_headers(api_key=api_key, token=token),
                files={"file": ("upload.pdf", pdf_bytes, "application/pdf")},
                timeout=float(os.getenv("MINERU_HTTP_TIMEOUT_S", "30")),
            )
            self._raise_for_status_with_body(resp)
            payload = resp.json()
            if isinstance(payload, dict) and isinstance(payload.get("pages"), list):
                return payload
            return self._to_pages(self._extract_text(payload))

        text = pdf_bytes.decode("utf-8", errors="ignore").strip()
        if not text:
            text = "上传文档内容。"
        body = text[:2000]
        return {
            "pages": [
                {
                    "page_no": 1,
                    "blocks": [
                        {"type": "title", "text": "第一章 自动解析"},
                        {"type": "paragraph", "text": body},
                    ],
                    "tables": [],
                }
            ]
        }
