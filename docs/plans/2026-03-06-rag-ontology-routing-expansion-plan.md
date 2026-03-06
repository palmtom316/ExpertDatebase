# RAG Ontology, Routing, and Query Expansion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rework the standards RAG path so it stops depending on lucky user phrasing and instead uses standards ontology, structured query routing, controlled query expansion, and a formal multi-variant benchmark.

**Architecture:** Keep the current worker indexing and hybrid retrieval foundation, but insert a deterministic standards ontology layer and a structured query router ahead of retrieval. Add controlled query expansion only after routing is in place, and make every change measurable through a new 200-sample benchmark that separates routing failures, retrieval failures, rerank failures, and answer-format failures.

**Tech Stack:** FastAPI, Python services under `services/api-server`, existing hybrid search stack (`Qdrant`, `PgBM25`, optional `Sirchmunk`/`GraphRAG`), pytest, JSONL/YAML datasets.

---

## Scope

This plan covers two approved implementation batches.

- Batch 1:
  - Standards ontology for the current 8 indexed standards
  - Structured query routing layer
  - 200-sample multi-variant benchmark scaffold
  - Retrieval evaluation extensions and route diagnostics
- Batch 2:
  - Query2doc-style controlled expansion
  - HyDE optional switch
  - Expanded-retrieval fusion and safety gates
  - Before/after metric comparison and rollout controls

This plan does not include:
- Reworking proposal-writing generation flows
- Re-architecting enterprise/personnel fact storage
- Full frontend redesign
- Re-indexing all PDFs unless routing metadata requires it

## Current Problem Statement

The current system has a working ingest/index pipeline, but retrieval still fails in the most business-critical way: broad natural-language questions route to the wrong standard family.

Representative failures already observed in the live system:
- `变压器安装有哪些规定` drifting to `GB 50150-2016` (交接试验标准) instead of `GB20148-2010`
- `变压器安装验收的主控项目有哪些` collapsing to `GB 50303-2015` instead of balancing professional transformer install/acceptance rules with quality-acceptance language

Root causes:
- No explicit ontology for standard roles and topic coverage
- Retrieval pipeline treats all standard PDFs as flat peers too early
- Current clause templating improves formatting after retrieval, but cannot recover from wrong-document routing
- No formal benchmark that measures phrasing robustness across variants

## Acceptance Criteria

Batch 1 is complete only when all of the following are true:
- Each of the 8 indexed standards is represented in a maintained ontology file with role/topic/task metadata
- Search entrypoint can emit an explainable route plan derived from structured query understanding
- The two known failure questions no longer top-rank clearly wrong standard roles in doc-agnostic mode
- A new 200-sample benchmark dataset exists, validates, and runs in CI/local evaluation tooling
- Retrieval evaluation output includes routing-oriented metrics (`top1_doc_accuracy`, `doc_role_accuracy`, `variant_consistency` scaffold)

Batch 2 is complete only when all of the following are true:
- Query expansion can be enabled or disabled without code edits
- Expansion only runs after routing produces a constrained candidate set
- Default route remains safe when expansion fails or times out
- Benchmark comparison shows measurable improvement in broad-query robustness without obvious cross-standard pollution
- Query expansion path is documented and covered by focused tests

## Implementation Strategy

Implement in this order:
1. Standards ontology
2. Structured query router
3. Benchmark and evaluation extensions
4. Query2doc-style expansion
5. HyDE optional path
6. Metric comparison and rollout guidance

Rationale:
- Ontology is required before routing can be reliable
- Routing is required before expansion can be safe
- Benchmark must exist before expansion work, otherwise improvement cannot be verified

---

### Task 1: Create standards ontology data model

**Files:**
- Create: `datasets/ontology/standards_ontology.yaml`
- Create: `services/api-server/app/services/ontology_service.py`
- Test: `tests/api/test_ontology_service.py`
- Reference: `datasets/v1.2/retrieval_eval_eight_specs_bid_32.jsonl`

**Step 1: Write the failing test**

Create tests that assert:
- ontology file loads successfully
- all 8 current standards have entries
- each entry exposes required keys:
  - `standard_no`
  - `standard_name`
  - `doc_id`
  - `version_id`
  - `role`
  - `domain`
  - `device_tags`
  - `task_tags`
  - `priority_signals`
  - `negative_signals`
- service can resolve entries by `doc_id`, `version_id`, and normalized `standard_no`

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/api/test_ontology_service.py`
Expected: FAIL because the ontology service and ontology file do not exist yet.

**Step 3: Write minimal implementation**

Implement an ontology loader/service with:
- stable schema validation
- normalized standard number matching (`GB20148-2010` vs `GB 20148-2010`)
- APIs to return:
  - all standards
  - one standard by id/version/standard number
  - standards filtered by role/device/task tags

Seed the ontology with the current 8 indexed standards and conservative role assignments.

**Step 4: Run test to verify it passes**

Run: `pytest -q tests/api/test_ontology_service.py`
Expected: PASS

**Step 5: Commit**

```bash
git add datasets/ontology/standards_ontology.yaml \
  services/api-server/app/services/ontology_service.py \
  tests/api/test_ontology_service.py
git commit -m "feat(rag): add standards ontology service"
```

---

### Task 2: Define structured query schema and router contract

**Files:**
- Create: `services/api-server/app/services/query_router.py`
- Test: `tests/api/test_query_router.py`
- Reference: `services/api-server/app/services/search_service.py`
- Reference: `services/api-server/app/services/chat_orchestrator.py`

**Step 1: Write the failing test**

Add tests that parse representative questions into a structured route payload. Cover at least:
- `变压器安装有哪些规定`
- `变压器安装验收的主控项目有哪些`
- `并联电容器交流耐压试验应符合哪些规定`
- `电缆线路金属护套接地应符合哪些要求`

Expected structured fields:
- `subject_entities`
- `task_type`
- `intent_type`
- `constraint_type`
- `preferred_roles`
- `negative_roles`
- `needs_clause_level`
- `needs_listing`
- `expansion_allowed`

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/api/test_query_router.py`
Expected: FAIL because the router does not exist yet.

**Step 3: Write minimal implementation**

Implement a deterministic router that combines:
- token/regex extraction
- ontology-backed role hints
- question-shape detection
- negative role assignment for obviously mismatched families

Do not add LLM dependence in v1 router. Keep it deterministic and testable.

**Step 4: Run test to verify it passes**

Run: `pytest -q tests/api/test_query_router.py`
Expected: PASS

**Step 5: Commit**

```bash
git add services/api-server/app/services/query_router.py \
  tests/api/test_query_router.py
git commit -m "feat(rag): add structured query router"
```

---

### Task 3: Integrate routing into hybrid search entrypoint

**Files:**
- Modify: `services/api-server/app/services/search_service.py`
- Test: `tests/api/test_hybrid_search_routing.py`
- Reference: `services/api-server/app/api/chat.py`
- Reference: `services/api-server/app/api/admin_eval.py`

**Step 1: Write the failing test**

Add search-level tests that assert:
- route plan is attached to debug output
- ontology/router can constrain candidate standard roles before retrieval
- broad transformer-install questions no longer top-rank `交接试验标准` without explicit trial/test terms
- `主控项目` questions can allow `质量验收规范` but do not blindly suppress professional install/acceptance standards

Use fake repo hits to make route behavior deterministic.

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/api/test_hybrid_search_routing.py`
Expected: FAIL against current route plan behavior.

**Step 3: Write minimal implementation**

Modify `hybrid_search` flow to:
- call `QueryRouter`
- derive candidate standards and role filters from ontology
- merge route constraints with existing `selected_doc_id` / `selected_version_id` scoping
- expose a richer debug structure:
  - `query_profile`
  - `candidate_standard_ids`
  - `candidate_roles`
  - `routing_explanations`

Keep current dense/sparse/keyword routes, but only after route constraints are applied.

**Step 4: Run test to verify it passes**

Run: `pytest -q tests/api/test_hybrid_search_routing.py`
Expected: PASS

**Step 5: Commit**

```bash
git add services/api-server/app/services/search_service.py \
  tests/api/test_hybrid_search_routing.py
git commit -m "feat(rag): route hybrid search with standards ontology"
```

---

### Task 4: Make clause-answer formatting respect routed standard scope

**Files:**
- Modify: `services/api-server/app/services/chat_orchestrator.py`
- Test: `tests/api/test_clause_listing_behavior.py`
- Test: `tests/api/test_chat_answer_quality.py`

**Step 1: Write the failing test**

Add tests that simulate wrong-family citations arriving alongside correct-family routed citations, and assert:
- answer builder prefers citations from routed candidate standards
- listing answers do not confidently summarize clearly mismatched standard roles
- fallback answer suggests narrowing scope when route confidence is low

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/api/test_clause_listing_behavior.py tests/api/test_chat_answer_quality.py -k 'routed_scope or low_confidence_scope'`
Expected: FAIL

**Step 3: Write minimal implementation**

Update answer orchestration so that:
- routed standard scope influences citation selection and answer construction
- mismatched-family citations are downweighted or excluded from clause-template answers
- low-confidence cross-family mixes produce guarded responses instead of overconfident summaries

**Step 4: Run test to verify it passes**

Run: `pytest -q tests/api/test_clause_listing_behavior.py tests/api/test_chat_answer_quality.py -k 'routed_scope or low_confidence_scope'`
Expected: PASS

**Step 5: Commit**

```bash
git add services/api-server/app/services/chat_orchestrator.py \
  tests/api/test_clause_listing_behavior.py \
  tests/api/test_chat_answer_quality.py
git commit -m "fix(rag): guard clause answers with routed standard scope"
```

---

### Task 5: Build 200-sample multi-variant benchmark scaffold

**Files:**
- Create: `datasets/v1.3/retrieval_eval_multivariant_200.jsonl`
- Create: `datasets/v1.3/manifest.json`
- Modify: `services/api-server/scripts/eval_retrieval.py`
- Modify: `services/api-server/app/api/admin_eval.py`
- Test: `tests/api/test_admin_eval_retrieval_run_api.py`
- Test: `tests/api/test_eval_retrieval_metrics.py`

**Step 1: Write the failing test**

Add tests for:
- loading the new dataset manifest
- validating required benchmark fields
- computing new metrics placeholders:
  - `top1_doc_accuracy`
  - `doc_role_accuracy`
  - `variant_consistency`
- retrieval eval API accepting the new dataset version/path

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/api/test_admin_eval_retrieval_run_api.py tests/api/test_eval_retrieval_metrics.py`
Expected: FAIL because v1.3 dataset and metrics are missing.

**Step 3: Write minimal implementation**

Create a 200-sample scaffold with 4 balanced buckets:
- role discrimination
- phrasing variants
- clause localization
- bid-constraint extraction

Extend evaluation code to:
- load v1.3 manifests
- report routing-aware metrics
- preserve existing metrics for backward compatibility

Do not claim the dataset is final-gold until each line is validated against actual indexed docs.

**Step 4: Run test to verify it passes**

Run: `pytest -q tests/api/test_admin_eval_retrieval_run_api.py tests/api/test_eval_retrieval_metrics.py`
Expected: PASS

**Step 5: Commit**

```bash
git add datasets/v1.3/retrieval_eval_multivariant_200.jsonl \
  datasets/v1.3/manifest.json \
  services/api-server/scripts/eval_retrieval.py \
  services/api-server/app/api/admin_eval.py \
  tests/api/test_admin_eval_retrieval_run_api.py \
  tests/api/test_eval_retrieval_metrics.py
git commit -m "feat(rag): add multivariant retrieval benchmark scaffold"
```

---

### Task 6: Run and baseline Batch 1 metrics

**Files:**
- Create: `docs/reports/2026-03-xx-rag-routing-benchmark-baseline.md`
- Reference: `docs/runbooks/retrieval_eval.md`

**Step 1: Write the reporting stub**

Create a baseline report template with sections for:
- environment
- dataset version
- route diagnostics summary
- key failures by category
- known false positives
- next tuning decisions

**Step 2: Run evaluation**

Run the v1.3 dataset locally and capture:
- old baseline on mainline behavior if still reproducible
- post-Batch-1 results

**Step 3: Record evidence**

Populate the report with:
- top1 wrong-standard examples
- role-routing improvement notes
- unresolved failures requiring expansion work

**Step 4: Commit**

```bash
git add docs/reports/2026-03-xx-rag-routing-benchmark-baseline.md
git commit -m "docs(rag): record routing benchmark baseline"
```

---

### Task 7: Add Query2doc-style controlled query expansion

**Files:**
- Create: `services/api-server/app/services/query_expansion.py`
- Modify: `services/api-server/app/services/runtime_defaults.py`
- Test: `tests/api/test_query_expansion.py`
- Test: `tests/api/test_hybrid_search_routing.py`

**Step 1: Write the failing test**

Add tests asserting that expansion:
- runs only when router allows it
- emits a bounded expansion payload
- preserves subject/task signals
- does not inject standards outside routed candidate families
- gracefully falls back when provider errors or times out

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/api/test_query_expansion.py tests/api/test_hybrid_search_routing.py -k 'expansion'`
Expected: FAIL because expansion service does not exist.

**Step 3: Write minimal implementation**

Implement a Query2doc-style service that returns:
- `canonical_query`
- `keyword_expansions`
- `pseudo_doc`
- `role_hints`
- `device_hints`

Add runtime defaults and env flags for:
- provider/model/base/api key
- timeout
- max tokens
- `QUERY_EXPANSION_ENABLED`
- `QUERY_EXPANSION_MODE=query2doc`

**Step 4: Run test to verify it passes**

Run: `pytest -q tests/api/test_query_expansion.py tests/api/test_hybrid_search_routing.py -k 'expansion'`
Expected: PASS

**Step 5: Commit**

```bash
git add services/api-server/app/services/query_expansion.py \
  services/api-server/app/services/runtime_defaults.py \
  tests/api/test_query_expansion.py \
  tests/api/test_hybrid_search_routing.py
git commit -m "feat(rag): add controlled query expansion"
```

---

### Task 8: Fuse expansion into retrieval safely

**Files:**
- Modify: `services/api-server/app/services/search_service.py`
- Test: `tests/api/test_hybrid_search_routing.py`
- Test: `tests/api/test_hybrid_search_filters.py`

**Step 1: Write the failing test**

Add tests asserting:
- original query route still executes when expansion is unavailable
- expanded query retrieval is run in parallel with original retrieval inside the routed candidate set
- fusion can improve broad-query hits without overriding explicit clause/standard precision questions
- precision queries still bypass unnecessary expansion

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/api/test_hybrid_search_routing.py tests/api/test_hybrid_search_filters.py -k 'query2doc or expansion_fusion'`
Expected: FAIL

**Step 3: Write minimal implementation**

Integrate expansion by:
- building secondary dense/sparse query strings from expansion output
- fusing results with route-aware weighting
- disabling expansion for explicit clause-id / exact-standard precision queries
- logging expansion provenance in search debug output

**Step 4: Run test to verify it passes**

Run: `pytest -q tests/api/test_hybrid_search_routing.py tests/api/test_hybrid_search_filters.py -k 'query2doc or expansion_fusion'`
Expected: PASS

**Step 5: Commit**

```bash
git add services/api-server/app/services/search_service.py \
  tests/api/test_hybrid_search_routing.py \
  tests/api/test_hybrid_search_filters.py
git commit -m "feat(rag): fuse expansion results into hybrid retrieval"
```

---

### Task 9: Add optional HyDE mode behind a strict switch

**Files:**
- Modify: `services/api-server/app/services/query_expansion.py`
- Modify: `services/api-server/app/services/runtime_defaults.py`
- Test: `tests/api/test_query_expansion.py`

**Step 1: Write the failing test**

Add tests asserting:
- `QUERY_EXPANSION_MODE=hyde` generates a pseudo-document style payload
- HyDE mode is disabled by default
- HyDE respects routed candidates and the same safety bounds as Query2doc
- timeout/failure falls back cleanly to original query path

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/api/test_query_expansion.py -k 'hyde'`
Expected: FAIL

**Step 3: Write minimal implementation**

Extend query expansion service to support:
- mode `query2doc`
- mode `hyde`
- shared bounded output schema
- shared safety and routing constraints

**Step 4: Run test to verify it passes**

Run: `pytest -q tests/api/test_query_expansion.py -k 'hyde'`
Expected: PASS

**Step 5: Commit**

```bash
git add services/api-server/app/services/query_expansion.py \
  services/api-server/app/services/runtime_defaults.py \
  tests/api/test_query_expansion.py
git commit -m "feat(rag): add optional hyde expansion mode"
```

---

### Task 10: Run Batch 2 comparison and rollout report

**Files:**
- Create: `docs/reports/2026-03-xx-rag-expansion-rollout-report.md`
- Modify: `docs/runbooks/retrieval_eval.md`

**Step 1: Create comparison template**

Template must include:
- Batch 1 metrics
- Batch 2 metrics
- delta table by bucket
- failure regressions
- recommendation for default mode (`none`, `query2doc`, `hyde`)

**Step 2: Run benchmark comparison**

Run the 200-sample benchmark in at least three modes:
- routing only
- routing + query2doc
- routing + hyde

Capture:
- top1 doc accuracy
- doc role accuracy
- hit@5/hit@10
- MRR
- clause hit rate
- variant consistency

**Step 3: Update runbook**

Document:
- how to enable each mode
- when not to enable expansion
- expected failure patterns

**Step 4: Commit**

```bash
git add docs/reports/2026-03-xx-rag-expansion-rollout-report.md \
  docs/runbooks/retrieval_eval.md
git commit -m "docs(rag): add expansion rollout guidance"
```

---

## Test Matrix

Minimum required checks before claiming the work complete:
- `pytest -q tests/api/test_ontology_service.py`
- `pytest -q tests/api/test_query_router.py`
- `pytest -q tests/api/test_hybrid_search_routing.py`
- `pytest -q tests/api/test_clause_listing_behavior.py`
- `pytest -q tests/api/test_chat_answer_quality.py`
- `pytest -q tests/api/test_admin_eval_retrieval_run_api.py`
- `pytest -q tests/api/test_eval_retrieval_metrics.py`
- `pytest -q tests/api/test_query_expansion.py`
- retrieval benchmark run against `datasets/v1.3/retrieval_eval_multivariant_200.jsonl`

## Data Curation Rules for the 200-Sample Benchmark

Use these buckets, 50 samples each:
- `role_discrimination`
- `phrasing_variants`
- `clause_localization`
- `bid_constraint_extraction`

Each record must include at minimum:
- `query`
- `query_variant_group`
- `selected_doc_id`
- `selected_version_id`
- `expected_doc_id`
- `expected_version_id`
- `expected_role`
- `expected_clause_ids`
- `expected_pages`
- `intent_type`
- `difficulty`

Do not bulk-generate and trust the dataset blindly. Every line must be checked against the current indexed standard and normalized to the active `doc_id`/`version_id` inventory.

## Risks and Mitigations

- Risk: Router becomes overfit to a few examples.
  - Mitigation: keep router deterministic, ontology-backed, and benchmark-driven.
- Risk: Query expansion amplifies wrong role hints.
  - Mitigation: expansion only runs after routed candidate restriction.
- Risk: 200-sample dataset becomes noisy or stale.
  - Mitigation: keep manifest versioned and validate ids against current registry.
- Risk: Answer layer still overstates confidence.
  - Mitigation: add low-confidence guarded answer path tied to routed scope confidence.

## Rollout Recommendation

Recommended implementation approval sequence:
- Approve and execute Batch 1 first
- Review benchmark and route diagnostics
- Only then approve Batch 2 expansion work

That sequence limits regression risk and gives an objective checkpoint before introducing expansion complexity.

## Definition of Done

The plan is fully executed only when:
- ontology exists and is wired into routing
- routing affects retrieval behavior, not just debug logs
- benchmark v1.3 runs locally and through the existing evaluation path
- routing reduces wrong-standard top1 cases for known broad questions
- query expansion is optional, bounded, and benchmarked
- rollout docs record which mode should be the default

Plan complete and saved to `docs/plans/2026-03-06-rag-ontology-routing-expansion-plan.md`. Two execution options:

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

**Which approach?**
