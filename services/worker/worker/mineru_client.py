"""MinerU client adapter (MVP stub)."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
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

    def _page_lines_from_text(self, text: str) -> list[str]:
        lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
        if not lines:
            return []
        # Some PDFs extract as one-char-per-line. Merge first, then split by sentence marks.
        tiny_ratio = sum(1 for line in lines if len(line) <= 2) / max(1, len(lines))
        if tiny_ratio >= 0.7 and len(lines) >= 16:
            merged = "".join(lines)
            merged = re.sub(r"([。！？；;])", r"\1\n", merged)
            repaired = [line.strip() for line in merged.splitlines() if line.strip()]
            if repaired:
                return repaired
        return lines

    def _page_text(self, page: Any) -> str:
        if not isinstance(page, dict):
            return ""
        lines: list[str] = []
        for block in page.get("blocks") or []:
            if isinstance(block, dict):
                text = str(block.get("text") or "").strip()
                if text:
                    lines.append(text)
        for table in page.get("tables") or []:
            if isinstance(table, dict):
                text = str(table.get("raw_text") or "").strip()
                if text:
                    lines.append(text)
        return "\n".join(lines).strip()

    def _cjk_ratio(self, text: str) -> float:
        sample = str(text or "").strip()
        if not sample:
            return 0.0
        cjk_count = sum(1 for ch in sample if "\u4e00" <= ch <= "\u9fff")
        return cjk_count / max(1, len(sample))

    def _noise_line_ratio(self, text: str) -> float:
        lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
        if not lines:
            return 1.0
        noisy = 0
        for line in lines:
            lower = line.lower()
            if "www." in lower or ".com" in lower or "bzfxw" in lower:
                noisy += 1
                continue
            if self._readable_ratio(line) < 0.45:
                noisy += 1
                continue
            compact = re.sub(r"\s+", "", line)
            if compact and self._cjk_ratio(compact) < 0.05 and len(compact) <= 48:
                noisy += 1
        return noisy / max(1, len(lines))

    def _page_char_count(self, page: Any) -> int:
        return len(re.sub(r"\s+", "", self._page_text(page)))

    def _readable_ratio(self, text: str) -> float:
        sample = str(text or "").strip()
        if not sample:
            return 0.0
        keep = 0
        for ch in sample:
            if ch.isalnum() or "\u4e00" <= ch <= "\u9fff":
                keep += 1
                continue
            if ch in "，。！？；：、（）()[]【】《》“”‘’+-*/%=._:;,\"' \n\t|":
                keep += 1
        return keep / max(1, len(sample))

    def _default_ocr_base_url(self, provider: str) -> str:
        if provider == "siliconflow":
            return "https://api.siliconflow.cn/v1"
        return "https://api.openai.com/v1"

    def _default_ocr_model(self, provider: str) -> str:
        if provider == "siliconflow":
            return "deepseek-ai/DeepSeek-OCR"
        return "gpt-4o-mini"

    def _resolve_ocr_runtime(self, runtime_config: dict[str, Any] | None = None) -> dict[str, str]:
        runtime = runtime_config or {}
        provider = str(runtime.get("ocr_provider") or os.getenv("OCR_PROVIDER", "")).strip().lower()
        default_base = self._default_ocr_base_url(provider)
        default_model = self._default_ocr_model(provider)
        return {
            "provider": provider,
            "api_key": self._normalize_token(
                str(
                    runtime.get("ocr_api_key")
                    or os.getenv("OCR_API_KEY")
                    or os.getenv("OPENAI_API_KEY")
                    or ""
                )
            ),
            "base_url": str(runtime.get("ocr_base_url") or os.getenv("OCR_BASE_URL") or os.getenv("OPENAI_BASE_URL", default_base))
            .strip()
            .rstrip("/"),
            "model": str(runtime.get("ocr_model") or os.getenv("OCR_MODEL") or default_model).strip(),
        }

    def _ocr_enabled(self, runtime_config: dict[str, Any] | None = None) -> bool:
        cfg = self._resolve_ocr_runtime(runtime_config=runtime_config)
        return cfg["provider"] in {"openai", "siliconflow"} and bool(cfg["api_key"] and cfg["base_url"] and cfg["model"])

    def _page_needs_ocr(self, page: Any) -> bool:
        text = self._page_text(page)
        min_chars = max(1, int(os.getenv("OCR_MIN_PAGE_TEXT_LEN", "48")))
        min_ratio = max(0.0, float(os.getenv("OCR_MIN_PAGE_READABLE_RATIO", "0.55")))
        max_noise_ratio = min(1.0, max(0.0, float(os.getenv("OCR_MAX_PAGE_NOISE_LINE_RATIO", "0.4"))))
        min_cjk_ratio = min(1.0, max(0.0, float(os.getenv("OCR_MIN_PAGE_CJK_RATIO", "0.02"))))
        compact = re.sub(r"\s+", "", text)
        if len(compact) < min_chars:
            return True
        if self._readable_ratio(text) < min_ratio:
            return True
        if self._noise_line_ratio(text) >= max_noise_ratio:
            return True
        has_cjk = bool(re.search(r"[\u4e00-\u9fff]", compact))
        if not has_cjk and self._cjk_ratio(compact) < min_cjk_ratio and len(compact) <= 160:
            return True
        return False

    def _should_force_full_doc_ocr(self, pages: list[Any], repair_page_numbers: list[int]) -> bool:
        if not pages or not repair_page_numbers:
            return False
        min_bad_pages = max(1, int(os.getenv("OCR_FORCE_FULL_DOC_MIN_BAD_PAGES", "24")))
        min_bad_ratio = min(1.0, max(0.0, float(os.getenv("OCR_FORCE_FULL_DOC_BAD_PAGE_RATIO", "0.3"))))
        avg_chars = sum(self._page_char_count(page) for page in pages) / max(1, len(pages))
        max_avg_chars = max(1.0, float(os.getenv("OCR_FORCE_FULL_DOC_MAX_AVG_PAGE_CHARS", "180")))
        bad_ratio = len(repair_page_numbers) / max(1, len(pages))
        if len(repair_page_numbers) >= min_bad_pages:
            return True
        if bad_ratio >= min_bad_ratio:
            return True
        return avg_chars <= max_avg_chars and bad_ratio >= max(min_bad_ratio / 2.0, 0.12)

    def _ocr_prompt(self, page_no: int) -> str:
        return (
            "你是电力工程规范文档 OCR 引擎。请逐字提取这一页的正文内容，"
            "尽量保留标题层级、条文编号、序号、表格行和单位数值。"
            "只输出页面内容本身，使用纯文本或简单 Markdown；不要解释，不要补充页面外信息。"
            f"当前页码：{page_no}。"
        )

    def _extract_message_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text") or item.get("content") or "").strip()
                if text:
                    parts.append(text)
            return "\n".join(x for x in parts if x).strip()
        if isinstance(content, dict):
            return str(content.get("text") or content.get("content") or "").strip()
        return ""

    def _render_pdf_page_images(self, pdf_bytes: bytes, page_numbers: list[int]) -> dict[int, bytes]:
        try:
            import fitz  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("PyMuPDF is required for OCR page rendering") from exc

        scale = max(1.0, float(os.getenv("OCR_RENDER_SCALE", "2.5")))
        rendered: dict[int, bytes] = {}
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            page_count = int(getattr(doc, "page_count", 0) or 0)
            for page_no in sorted({int(p) for p in page_numbers if int(p) > 0}):
                if page_no > page_count:
                    continue
                page = doc.load_page(page_no - 1)
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                rendered[page_no] = pix.tobytes("png")
        return rendered

    def _request_ocr_page(self, image_bytes: bytes, cfg: dict[str, str], page_no: int) -> str:
        data_url = f"data:image/png;base64,{base64.b64encode(image_bytes).decode('ascii')}"
        resp = requests.post(
            f"{cfg['base_url']}/chat/completions",
            headers={"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"},
            json={
                "model": cfg["model"],
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": self._ocr_prompt(page_no=page_no)},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    }
                ],
                "temperature": 0,
                "max_tokens": int(os.getenv("OCR_MAX_TOKENS", "4096")),
            },
            timeout=float(os.getenv("OCR_HTTP_TIMEOUT_S", "60")),
        )
        self._raise_for_status_with_body(resp)
        body = resp.json()
        content = (((body.get("choices") or [{}])[0]).get("message") or {}).get("content")
        return self._extract_message_text(content)

    def _title_like(self, line: str) -> bool:
        text = str(line or "").strip()
        if not text or len(text) > 80:
            return False
        return bool(
            re.match(r"^(第[一二三四五六七八九十百千万0-9]+[章节篇部分卷])", text)
            or re.match(r"^[0-9]+(?:\.[0-9]+){0,3}\s+", text)
            or re.match(r"^[一二三四五六七八九十]+、", text)
        )

    def _blocks_and_tables_from_ocr_text(self, text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        lines = [line.rstrip() for line in str(text or "").splitlines()]
        blocks: list[dict[str, Any]] = []
        tables: list[dict[str, Any]] = []
        para_lines: list[str] = []
        table_lines: list[str] = []

        def flush_para() -> None:
            if not para_lines:
                return
            content = " ".join(x.strip() for x in para_lines if x.strip()).strip()
            para_lines.clear()
            if content:
                blocks.append({"type": "paragraph", "text": content})

        def flush_table() -> None:
            if not table_lines:
                return
            raw = "\n".join(x.strip() for x in table_lines if x.strip()).strip()
            table_lines.clear()
            if raw:
                tables.append({"raw_text": raw})
                blocks.append({"type": "paragraph", "text": raw})

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                flush_para()
                flush_table()
                continue
            is_table_line = line.count("|") >= 2 or "\t" in line
            if is_table_line:
                flush_para()
                table_lines.append(line)
                continue
            flush_table()
            if self._title_like(line):
                flush_para()
                blocks.append({"type": "title", "text": line})
                continue
            para_lines.append(line)

        flush_para()
        flush_table()

        if not blocks and text.strip():
            blocks = [{"type": "paragraph", "text": text.strip()}]
        return blocks, tables

    def _parse_pdf_with_ocr(
        self,
        pdf_bytes: bytes,
        runtime_config: dict[str, Any] | None = None,
        page_numbers: list[int] | None = None,
    ) -> dict[str, Any]:
        cfg = self._resolve_ocr_runtime(runtime_config=runtime_config)
        if cfg["provider"] not in {"openai", "siliconflow"} or not cfg["api_key"]:
            raise RuntimeError("ocr runtime is not configured")

        render_pages = page_numbers or []
        if not render_pages:
            try:
                from pypdf import PdfReader  # type: ignore

                reader = PdfReader(io.BytesIO(pdf_bytes))
                render_pages = list(range(1, len(getattr(reader, "pages", []) or []) + 1))
            except Exception:  # noqa: BLE001
                render_pages = [1]

        rendered = self._render_pdf_page_images(pdf_bytes=pdf_bytes, page_numbers=render_pages)
        max_workers_raw = str(os.getenv("OCR_PAGE_CONCURRENCY", "3")).strip()
        try:
            max_workers = int(max_workers_raw)
        except Exception:  # noqa: BLE001
            max_workers = 3
        max_workers = max(1, min(max_workers, len(render_pages)))
        page_texts: dict[int, str] = {}

        def _ocr_one(page_no: int) -> tuple[int, str] | None:
            image_bytes = rendered.get(int(page_no))
            if not image_bytes:
                return None
            text = self._request_ocr_page(image_bytes=image_bytes, cfg=cfg, page_no=int(page_no))
            return int(page_no), text

        if max_workers == 1:
            for page_no in render_pages:
                try:
                    result = _ocr_one(int(page_no))
                except Exception:
                    continue
                if result is None:
                    continue
                done_page_no, text = result
                page_texts[done_page_no] = text
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(_ocr_one, int(page_no)) for page_no in render_pages]
                for future in as_completed(futures):
                    try:
                        result = future.result()
                    except Exception:
                        continue
                    if result is None:
                        continue
                    done_page_no, text = result
                    page_texts[done_page_no] = text

        pages: list[dict[str, Any]] = []
        for page_no in render_pages:
            text = page_texts.get(int(page_no))
            if not text:
                continue
            blocks, tables = self._blocks_and_tables_from_ocr_text(text)
            pages.append({"page_no": int(page_no), "blocks": blocks, "tables": tables, "images": []})
        if not pages:
            raise RuntimeError("ocr returned no pages")
        return {"pages": pages}

    def _apply_ocr_repair(
        self,
        pdf_bytes: bytes,
        parsed: dict[str, Any],
        runtime_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        pages = parsed.get("pages")
        if not isinstance(pages, list) or not pages:
            return parsed

        max_repair_pages = max(1, int(os.getenv("OCR_MAX_REPAIR_PAGES_PER_DOC", "48")))
        repair_page_numbers: list[int] = []
        for idx, page in enumerate(pages, start=1):
            page_no = int((page or {}).get("page_no") or idx) if isinstance(page, dict) else idx
            if not self._page_needs_ocr(page):
                continue
            repair_page_numbers.append(page_no)

        if not repair_page_numbers:
            return parsed

        if self._should_force_full_doc_ocr(pages=pages, repair_page_numbers=repair_page_numbers):
            repaired = self._parse_pdf_with_ocr(
                pdf_bytes=pdf_bytes,
                runtime_config=runtime_config,
                page_numbers=None,
            )
            repaired_pages = {
                int(page.get("page_no") or 0): page
                for page in repaired.get("pages") or []
                if isinstance(page, dict)
            }
            merged_pages: list[dict[str, Any]] = []
            for idx, page in enumerate(pages, start=1):
                page_no = int((page or {}).get("page_no") or idx) if isinstance(page, dict) else idx
                merged_pages.append(repaired_pages.get(page_no) or page)
            return {**parsed, "pages": merged_pages}

        if len(repair_page_numbers) > max_repair_pages:
            repair_page_numbers = repair_page_numbers[:max_repair_pages]

        repaired = self._parse_pdf_with_ocr(
            pdf_bytes=pdf_bytes,
            runtime_config=runtime_config,
            page_numbers=repair_page_numbers,
        )
        repaired_pages = {
            int(page.get("page_no") or 0): page
            for page in repaired.get("pages") or []
            if isinstance(page, dict)
        }
        merged_pages: list[dict[str, Any]] = []
        for idx, page in enumerate(pages, start=1):
            page_no = int((page or {}).get("page_no") or idx) if isinstance(page, dict) else idx
            merged_pages.append(repaired_pages.get(page_no) or page)
        return {**parsed, "pages": merged_pages}

    def _parse_pdf_locally(self, pdf_bytes: bytes) -> dict[str, Any] | None:
        """Fallback parser when MinerU endpoint is not configured.

        Prefer PDF text extraction over raw bytes decoding so multi-page documents
        can still produce reasonable page-level blocks in offline/dev mode.
        """
        try:
            from pypdf import PdfReader  # type: ignore
        except Exception:  # noqa: BLE001
            return None

        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
        except Exception:  # noqa: BLE001
            return None

        max_pages = max(0, int(os.getenv("MINERU_LOCAL_MAX_PAGES", "0")))
        max_lines_per_page = max(20, int(os.getenv("MINERU_LOCAL_MAX_LINES_PER_PAGE", "240")))
        pages: list[dict[str, Any]] = []
        for idx, page in enumerate(getattr(reader, "pages", []) or [], start=1):
            if max_pages > 0 and idx > max_pages:
                break
            try:
                text = ""
                try:
                    text = str(page.extract_text(extraction_mode="layout") or "").strip()
                except Exception:  # noqa: BLE001
                    text = ""
                if not text:
                    text = str(page.extract_text() or "").strip()
            except Exception:  # noqa: BLE001
                text = ""
            if not text:
                continue
            lines = self._page_lines_from_text(text)
            if not lines:
                lines = [text]
            lines = lines[:max_lines_per_page]
            blocks: list[dict[str, Any]] = []
            for line_idx, line in enumerate(lines, start=1):
                block_type = "title" if line_idx == 1 and len(line) <= 70 else "paragraph"
                blocks.append({"type": block_type, "text": line})
            pages.append({"page_no": idx, "blocks": blocks, "tables": []})

        if not pages:
            return None
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
        # Some MinerU gateways accept only `token` header while others accept Bearer.
        # Send both when token is not explicitly provided to maximize compatibility.
        token_value = token or api_key
        if token_value:
            headers["token"] = token_value
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
                timeout=float(os.getenv("MINERU_HTTP_TIMEOUT_S", "30")),  # nosec B113
            )
            self._raise_for_status_with_body(resp)
            payload = resp.json()
            if isinstance(payload, dict) and isinstance(payload.get("pages"), list):
                return payload
            return self._to_pages(self._extract_text(payload))

        local_parsed = self._parse_pdf_locally(pdf_bytes)
        if local_parsed is not None:
            if self._ocr_enabled(runtime_config=runtime_config):
                try:
                    return self._apply_ocr_repair(
                        pdf_bytes=pdf_bytes,
                        parsed=local_parsed,
                        runtime_config=runtime_config,
                    )
                except Exception:
                    return local_parsed
            return local_parsed

        if self._ocr_enabled(runtime_config=runtime_config):
            try:
                return self._parse_pdf_with_ocr(pdf_bytes=pdf_bytes, runtime_config=runtime_config)
            except Exception:
                pass

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
