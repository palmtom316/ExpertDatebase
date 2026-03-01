"""Map character offsets to page numbers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _Span:
    page_no: int
    start: int
    end: int


class PageOffsetMapper:
    def __init__(self, spans: list[_Span]) -> None:
        self._spans = spans

    @classmethod
    def from_pages(cls, pages: list[dict]) -> "PageOffsetMapper":
        spans: list[_Span] = []
        cursor = 0
        for row in pages:
            page_no = int((row or {}).get("page_no") or 0)
            text = str((row or {}).get("text") or "")
            length = len(text)
            spans.append(_Span(page_no=page_no, start=cursor, end=cursor + length))
            cursor += length + 1
        return cls(spans=spans)

    def page_for_offset(self, offset: int) -> int | None:
        pos = int(offset)
        for span in self._spans:
            if span.start <= pos <= span.end:
                return span.page_no
        if self._spans:
            return self._spans[-1].page_no
        return None

