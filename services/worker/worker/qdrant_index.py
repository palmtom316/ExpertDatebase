"""Qdrant payload index bootstrap for hybrid filtering."""

from __future__ import annotations

from typing import Any

import requests


DEFAULT_PAYLOAD_INDEXES: list[dict[str, str]] = [
    {"field_name": "doc_id", "field_schema": "keyword"},
    {"field_name": "version_id", "field_schema": "keyword"},
    {"field_name": "doc_type", "field_schema": "keyword"},
    {"field_name": "page_start", "field_schema": "integer"},
    {"field_name": "page_end", "field_schema": "integer"},
    {"field_name": "chapter_id", "field_schema": "keyword"},
    {"field_name": "source_type", "field_schema": "keyword"},
    {"field_name": "page_type", "field_schema": "keyword"},
    {"field_name": "entity_person_ids", "field_schema": "keyword"},
    {"field_name": "entity_project_ids", "field_schema": "keyword"},
    {"field_name": "entity_equipment_ids", "field_schema": "keyword"},
    {"field_name": "rel_person_role", "field_schema": "keyword"},
    {"field_name": "rel_person_role_project", "field_schema": "keyword"},
    {"field_name": "clause_no", "field_schema": "keyword"},
    {"field_name": "standard_no", "field_schema": "keyword"},
    {"field_name": "certificate_no", "field_schema": "keyword"},
    {"field_name": "val_voltage_kv", "field_schema": "integer"},
    {"field_name": "val_contract_amount_w", "field_schema": "float"},
    {"field_name": "val_line_length_km", "field_schema": "float"},
    {"field_name": "val_capacity_mva", "field_schema": "float"},
]


def ensure_payload_indexes(
    endpoint: str,
    collection: str = "chunks_v1",
    timeout_s: float = 8.0,
    fields: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    base = endpoint.rstrip("/")
    specs = fields or DEFAULT_PAYLOAD_INDEXES
    created = 0
    skipped = 0

    for spec in specs:
        url = f"{base}/collections/{collection}/index"
        resp = requests.put(
            url=url,
            json={
                "field_name": spec["field_name"],
                "field_schema": spec["field_schema"],
            },
            timeout=timeout_s,
        )
        if resp.status_code in (200, 201):
            created += 1
            continue
        if resp.status_code == 409:
            skipped += 1
            continue
        resp.raise_for_status()

    return {"created": created, "skipped": skipped, "collection": collection}
