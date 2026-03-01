"""In-process LangExtract-style rule engine."""

from __future__ import annotations

import re
from typing import Any

from worker.ie.grounding.page_offset_mapper import PageOffsetMapper
from worker.ie.validators.power_field_validator import validate_power_fields


def _build_field(value: Any, start: int, end: int, mapper: PageOffsetMapper | None) -> dict[str, Any]:
    return {
        "value": value,
        "start": start,
        "end": end,
        "page_no": mapper.page_for_offset(start) if mapper else None,
    }


class LangExtractEngine:
    def extract(self, text: str, mapper: PageOffsetMapper | None = None) -> dict[str, Any]:
        raw = str(text or "")
        fields: dict[str, Any] = {}

        kv = re.search(r"(\d{2,4})\s*(kV|KV|千伏)", raw)
        if kv:
            fields["voltage_kv"] = _build_field(int(kv.group(1)), kv.start(1), kv.end(1), mapper=mapper)

        amount = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(亿|万|万元)", raw)
        if amount:
            value_wan = float(amount.group(1))
            if amount.group(2) == "亿":
                value_wan *= 10000
            fields["amount_wan"] = _build_field(value_wan, amount.start(1), amount.end(2), mapper=mapper)

        person = re.search(r"(?:项目经理|技术负责人|总工|安全员|质量员)[:：\s]*([\u4e00-\u9fa5]{2,4})", raw)
        if person:
            fields["person_name"] = _build_field(person.group(1), person.start(1), person.end(1), mapper=mapper)

        cert = re.search(r"(?<![A-Z0-9])([A-Z]{1,6}(?:-[A-Z0-9]{1,10}){2,})(?![A-Z0-9])", raw)
        if cert:
            fields["certificate_no"] = _build_field(cert.group(1), cert.start(1), cert.end(1), mapper=mapper)

        standard = re.search(
            r"(?<![A-Za-z0-9])((?:GB|DL/T|DL|NB/T|IEC|ISO)\s*[-A-Z]*\s*\d{2,6}(?:-\d{4})?)(?![A-Za-z0-9])",
            raw,
            flags=re.IGNORECASE,
        )
        if standard:
            fields["standard_no"] = _build_field(
                standard.group(1).upper(),
                standard.start(1),
                standard.end(1),
                mapper=mapper,
            )

        clause = re.search(r"\b(\d{1,2}(?:\.\d+){1,4})\b", raw)
        if clause:
            fields["clause_no"] = _build_field(clause.group(1), clause.start(1), clause.end(1), mapper=mapper)

        validation = validate_power_fields(fields)
        return {"fields": fields, "validation": validation}
