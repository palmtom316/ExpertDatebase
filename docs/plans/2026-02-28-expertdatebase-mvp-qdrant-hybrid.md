# ExpertDatebase MVP (Qdrant Hybrid) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 基于 `expert_kb_codex_pack_v1_1_qdrant_hybrid.zip` 实现可运行 MVP：PDF 上传与处理、Qdrant 混合检索、带强引用 QA、IE 资产抽取入库、基础评测闭环。

**Architecture:** 采用 monorepo + 多服务 Docker 架构。`api-server` 负责上传/检索/问答/管理接口，`worker` 负责 MinerU 后处理流水线与评测，`postgres/minio/qdrant/redis` 提供状态、对象存储、向量检索与队列。先打通后端最小闭环，再补评测与管理页。

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, Alembic, Pydantic, Celery, Redis, PostgreSQL 16, MinIO, Qdrant, pytest。

---

## Scope Baseline（从压缩包固化）

- 需求来源：
  - `00_README_Codex_Handoff.md`
  - `01_Architecture_and_Modules.md`
  - `02~09` 全部规范文件
  - `configs/*.yaml|json`
  - `docker/docker-compose.skeleton.yml`
- MVP 验收（必须）：
  - PDF 上传并产出可查看中间结果
  - chunks 检索 + QA 返回 1~N 引用（文档+页码+摘录）
  - IE 至少 1 类资产（资质/人员/业绩）入库并保留 source_page/excerpt
  - Qdrant Hybrid：向量 + payload filter 同时生效

### Task 1: 仓库骨架与运行基线

**Files:**
- Create: `services/api-server/app/main.py`
- Create: `services/worker/worker/main.py`
- Create: `shared/models/__init__.py`
- Create: `shared/configs/README.md`
- Create: `docker/docker-compose.yml`
- Create: `pyproject.toml`
- Create: `.env.example`
- Test: `tests/smoke/test_project_layout.py`

**Step 1: Write the failing test**

```python
# tests/smoke/test_project_layout.py
from pathlib import Path

def test_required_dirs_exist():
    required = [
        "services/api-server/app",
        "services/worker/worker",
        "shared/models",
        "shared/configs",
        "docker",
    ]
    root = Path(__file__).resolve().parents[2]
    for p in required:
        assert (root / p).exists(), p
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/smoke/test_project_layout.py -v`
Expected: FAIL with missing directories

**Step 3: Write minimal implementation**
- 创建目录与占位入口文件。
- 将 `docker-compose.skeleton.yml` 映射成可启动的 `docker/docker-compose.yml`。

**Step 4: Run test to verify it passes**

Run: `pytest tests/smoke/test_project_layout.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add .
git commit -m "chore: bootstrap monorepo structure and runtime baseline"
```

### Task 2: 配置中心与规则加载（zip 配置落地）

**Files:**
- Create: `shared/configs/keyword_rules_v1.yaml`
- Create: `shared/configs/page_type_rules_v1.yaml`
- Create: `shared/configs/ie_schema_v1.json`
- Create: `shared/configs/table_columns_v1.json`
- Create: `shared/configs/routing_policy_v1.json`
- Create: `shared/configs/loader.py`
- Test: `tests/config/test_config_loader.py`

**Step 1: Write the failing test**

```python
from shared.configs.loader import load_all_configs

def test_load_all_configs_has_versions():
    cfg = load_all_configs()
    assert cfg["keyword_rules"]["version"] == "v1.0"
    assert cfg["page_type_rules"]["version"] == "v1.0"
    assert cfg["routing_policy"]["version"] == "routing_policy_v1"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/config/test_config_loader.py -v`
Expected: FAIL with import/file missing

**Step 3: Write minimal implementation**
- 从 zip 逐字落地配置文件。
- `loader.py` 统一读取 YAML/JSON 并返回 dict。

**Step 4: Run test to verify it passes**

Run: `pytest tests/config/test_config_loader.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add shared/configs tests/config
git commit -m "feat: add v1 config packs and config loader"
```

### Task 3: 元数据模型与数据库迁移

**Files:**
- Create: `shared/models/base.py`
- Create: `shared/models/document.py`
- Create: `shared/models/chunk.py`
- Create: `shared/models/asset.py`
- Create: `shared/models/llm_call_log.py`
- Create: `shared/models/eval.py`
- Create: `services/api-server/alembic.ini`
- Create: `services/api-server/alembic/versions/0001_init.py`
- Test: `tests/db/test_schema_tables.py`

**Step 1: Write the failing test**
- 断言表存在：`documents`, `document_versions`, `chunks`, `assets`, `llm_call_log`, `eval_run`, `eval_sample`, `eval_result`。

**Step 2: Run test to verify it fails**

Run: `pytest tests/db/test_schema_tables.py -v`
Expected: FAIL with missing metadata/tables

**Step 3: Write minimal implementation**
- 按 `01_Architecture_and_Modules.md` 定义高层对象。
- Alembic 首次迁移建表。

**Step 4: Run test to verify it passes**

Run: `pytest tests/db/test_schema_tables.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add shared/models services/api-server/alembic tests/db
git commit -m "feat: add core metadata schema and initial migration"
```

### Task 4: 上传入口与文档注册

**Files:**
- Create: `services/api-server/app/api/upload.py`
- Create: `services/api-server/app/services/storage.py`
- Create: `services/api-server/app/services/doc_registry.py`
- Modify: `services/api-server/app/main.py`
- Test: `tests/api/test_upload_api.py`

**Step 1: Write the failing test**
- `POST /api/upload` 上传 PDF 后返回 `doc_id/version_id/object_key`。

**Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_upload_api.py -v`
Expected: FAIL with 404 / handler missing

**Step 3: Write minimal implementation**
- 上传 PDF 到 MinIO。
- 写 `documents/document_versions`，状态置 `uploaded`。
- 投递处理任务到 Redis 队列。

**Step 4: Run test to verify it passes**

Run: `pytest tests/api/test_upload_api.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add services/api-server tests/api
git commit -m "feat: implement upload endpoint and document registration"
```

### Task 5: Worker 主流水线（MinerU 后处理最小闭环）

**Files:**
- Create: `services/worker/worker/pipeline.py`
- Create: `services/worker/worker/mineru_client.py`
- Create: `services/worker/worker/normalize.py`
- Create: `services/worker/worker/chapters.py`
- Create: `services/worker/worker/chunking.py`
- Test: `tests/worker/test_pipeline_mvp.py`

**Step 1: Write the failing test**
- 给 fixture `mineru_result.json`，断言产出 `normalized_blocks/tables`、`chapters`、`chunks`。

**Step 2: Run test to verify it fails**

Run: `pytest tests/worker/test_pipeline_mvp.py -v`
Expected: FAIL with missing pipeline stages

**Step 3: Write minimal implementation**
- 支持 `章节优先 + 退化策略C(先页后合并 4k~8k)`。
- chunk 长度控制在 500~800 字，保留 page_range/block_ids。

**Step 4: Run test to verify it passes**

Run: `pytest tests/worker/test_pipeline_mvp.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add services/worker tests/worker
git commit -m "feat: add mineru post-processing pipeline with chapter degrade strategy"
```

### Task 6: IE 抽取与资产落库（含电力字段）

**Files:**
- Create: `services/worker/worker/ie_extract.py`
- Create: `services/worker/worker/prompt_templates/ie_v1.md`
- Create: `services/worker/worker/asset_writer.py`
- Test: `tests/worker/test_ie_extract_grounding.py`

**Step 1: Write the failing test**
- 输入章节文本，断言输出 JSON 合法。
- 断言 `source_page/source_excerpt/source_type` 必填。

**Step 2: Run test to verify it fails**

Run: `pytest tests/worker/test_ie_extract_grounding.py -v`
Expected: FAIL with missing extractor/grounding

**Step 3: Write minimal implementation**
- 使用 `ie_schema_v1` 驱动字段抽取。
- 支持电力专项字段：`voltage_level_kv` 等。
- 资产写入 `assets` 表并回填来源字段。

**Step 4: Run test to verify it passes**

Run: `pytest tests/worker/test_ie_extract_grounding.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add services/worker tests/worker
git commit -m "feat: implement schema-based IE extraction with grounding"
```

### Task 7: Embedding 入库与 Qdrant payload 构建

**Files:**
- Create: `services/worker/worker/embedding_client.py`
- Create: `services/worker/worker/qdrant_repo.py`
- Create: `services/worker/worker/build_payload.py`
- Test: `tests/worker/test_qdrant_payload_builder.py`

**Step 1: Write the failing test**
- 给 chunk + relations + entity_index，断言 payload 具备：
  - `entity_*_ids`
  - `rel_person_role(_project)`
  - `val_voltage_kv/val_contract_amount_w`

**Step 2: Run test to verify it fails**

Run: `pytest tests/worker/test_qdrant_payload_builder.py -v`
Expected: FAIL with payload fields missing

**Step 3: Write minimal implementation**
- 实现 `build_payload()`（按 `09_Qdrant_Hybrid_Search_Spec.md`）。
- 写 Qdrant upsert 与 payload index 建立脚本。

**Step 4: Run test to verify it passes**

Run: `pytest tests/worker/test_qdrant_payload_builder.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add services/worker tests/worker
git commit -m "feat: add embedding upsert and qdrant hybrid payload builder"
```

### Task 8: 检索 API（parse_filter_spec + hybrid search）

**Files:**
- Create: `services/api-server/app/services/filter_parser.py`
- Create: `services/api-server/app/services/search_service.py`
- Create: `services/api-server/app/api/search.py`
- Test: `tests/api/test_hybrid_search_filters.py`

**Step 1: Write the failing test**
- 问句含 “110kV + 项目经理 + 人名” 时生成 must filters。
- 搜索结果返回 `citations[]`（含 doc_name/page/excerpt）。

**Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_hybrid_search_filters.py -v`
Expected: FAIL with parser/search missing

**Step 3: Write minimal implementation**
- `parse_filter_spec()` 提取 kV/金额/角色/人名。
- 调用 Qdrant vector+filter，并返回标准引用结构。

**Step 4: Run test to verify it passes**

Run: `pytest tests/api/test_hybrid_search_filters.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add services/api-server tests/api
git commit -m "feat: implement hybrid search api with qdrant filters"
```

### Task 9: QA 编排与强引用输出

**Files:**
- Create: `services/api-server/app/services/chat_orchestrator.py`
- Create: `services/api-server/app/api/chat.py`
- Create: `services/api-server/app/services/llm_router.py`
- Test: `tests/api/test_chat_citations.py`

**Step 1: Write the failing test**
- 调用 `/api/chat` 后答案必须带 1~N 条引用。
- 引用支持 `expandable_evidence`（before/excerpt/after）。

**Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_chat_citations.py -v`
Expected: FAIL with missing citations/evidence format

**Step 3: Write minimal implementation**
- 接入 `routing_policy_v1` 的 Tier1/2/3 回退。
- 记录 `llm_call_log`（provider/model/latency/tokens/error）。

**Step 4: Run test to verify it passes**

Run: `pytest tests/api/test_chat_citations.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add services/api-server tests/api
git commit -m "feat: add chat orchestration with mandatory citations"
```

### Task 10: 评测执行器、评分器与管理接口（最小）

**Files:**
- Create: `services/worker/worker/eval_runner.py`
- Create: `services/worker/worker/scorer.py`
- Create: `services/api-server/app/api/admin_eval.py`
- Create: `services/worker/worker/diff_report.py`
- Test: `tests/eval/test_eval_scoring_ie_qa_retr.py`

**Step 1: Write the failing test**
- 使用 toy dataset 断言 IE/TABLE/QA/RETR 分数公式正确。

**Step 2: Run test to verify it fails**

Run: `pytest tests/eval/test_eval_scoring_ie_qa_retr.py -v`
Expected: FAIL with scorer missing

**Step 3: Write minimal implementation**
- `eval_runner` 按 manifest 执行并产出 `pred.json + diff_report.json`。
- `scorer` 按 `06_Datasets_and_Scoring.md` 公式计算分数。
- 提供管理员最小接口：run list / result detail。

**Step 4: Run test to verify it passes**

Run: `pytest tests/eval/test_eval_scoring_ie_qa_retr.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add services/worker services/api-server tests/eval
git commit -m "feat: add eval runner, scoring and admin eval apis"
```

### Task 11: 端到端验收与交付清单

**Files:**
- Create: `tests/e2e/test_mvp_pipeline_to_chat.py`
- Create: `docs/runbooks/mvp_acceptance.md`
- Create: `docs/runbooks/ops_checklist.md`

**Step 1: Write the failing test**
- e2e：上传 PDF -> pipeline -> hybrid search -> chat 回答 + citations。

**Step 2: Run test to verify it fails**

Run: `pytest tests/e2e/test_mvp_pipeline_to_chat.py -v`
Expected: FAIL before all components wired

**Step 3: Write minimal implementation**
- 打通 API/Worker/DB/Qdrant 连接与状态流转。
- 形成运行手册与验收检查项。

**Step 4: Run test to verify it passes**

Run: `pytest tests/e2e/test_mvp_pipeline_to_chat.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/e2e docs/runbooks
git commit -m "test: add mvp e2e acceptance and operational runbooks"
```

## Non-Goals（本计划明确不做）

- 自动触发外部 MinerU（仅管理员手动触发）
- 投标文件自动生成模块（仅预留接口，不实现）
- 完整 Web 前端复杂交互（MVP 仅提供最小接口与可选简页）

## Milestones

1. `M1` 基础设施 + 上传 + pipeline 初通（Task 1~5）
2. `M2` IE + Qdrant Hybrid 检索 + QA 强引用（Task 6~9）
3. `M3` 评测闭环 + E2E 验收（Task 10~11）

## Approval Gate

- Gate A（实施前审批）：确认技术栈与目录规划。
- Gate B（M1 完成）：确认最小闭环可演示。
- Gate C（M3 完成）：确认上线前清单与容量策略。
