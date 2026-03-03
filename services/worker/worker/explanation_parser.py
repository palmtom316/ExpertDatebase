"""Configurable parser for clause explanation sections."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any


@dataclass
class Page:
    doc_id: str
    page_no: int
    text: str


@dataclass
class ExplanationNode:
    doc_id: str
    clause_id: str
    clause_id_base: str
    clause_sub: str | None
    title: str | None
    body: str
    page_start: int
    page_end: int


def parse_explanations_from_pages(
    pages: list[Page],
    explanation_start_regexes: list[str],
    clause_id_regex: str,
) -> list[ExplanationNode]:
    start_res = [re.compile(raw, re.IGNORECASE) for raw in explanation_start_regexes]
    id_re = re.compile(clause_id_regex)

    in_explain = False
    nodes: list[ExplanationNode] = []
    current: ExplanationNode | None = None
    body_lines: list[str] = []

    for page in pages:
        lines = [x.strip() for x in str(page.text).splitlines() if x.strip()]
        for line in lines:
            if not in_explain and any(r.search(line) for r in start_res):
                in_explain = True
                continue
            if not in_explain:
                continue

            m = id_re.match(line)
            if m:
                if current is not None:
                    current.body = "\n".join(body_lines).strip()
                    current.page_end = page.page_no
                    nodes.append(current)
                body_lines = []
                base = str(m.group("id") or "").strip()
                sub = (m.groupdict().get("sub") or "").strip() or None
                rest = (m.groupdict().get("rest") or "").strip()
                clause_id = base + (f"({sub})" if sub else "")
                title = rest if rest and len(rest) <= 60 and not rest.endswith(("。", ".", "；", ";", "：", ":")) else None
                if title is None and rest:
                    body_lines.append(rest)
                current = ExplanationNode(
                    doc_id=page.doc_id,
                    clause_id=clause_id,
                    clause_id_base=base,
                    clause_sub=sub,
                    title=title,
                    body="",
                    page_start=page.page_no,
                    page_end=page.page_no,
                )
            elif current is not None:
                body_lines.append(line)

    if current is not None:
        current.body = "\n".join(body_lines).strip()
        nodes.append(current)
    return nodes


def node_to_dict(node: ExplanationNode) -> dict[str, Any]:
    return asdict(node)
