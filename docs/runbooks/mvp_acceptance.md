# MVP Acceptance

## Preconditions
- Docker services are up: postgres/redis/minio/qdrant/api-server/worker.
- Config pack loaded from `shared/configs`.

## Checklist
1. Upload one PDF via `/api/upload`.
2. Verify worker pipeline output contains normalized blocks, chapters, and chunks.
3. Verify hybrid search returns citations with `doc_name/page_start/excerpt`.
4. Verify chat output includes `citations` and `expandable_evidence`.
5. Verify IE output contains grounding fields (`source_page/source_excerpt/source_type`).
6. Verify admin retry endpoints can list/cleanup/retry failed jobs.
7. Verify `/api/admin/docs/{version_id}/artifacts` returns version + assets view.
8. Verify `/api/admin/eval/results/{result_id}` can return eval result detail.

## Pass Criteria
- All checks above pass without manual DB edits.
