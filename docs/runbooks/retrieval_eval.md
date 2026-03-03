# 检索质量离线评测（Hit@5/10, MRR）

用于重建索引后快速量化“召回是否变好”，避免只靠主观体验。

## 1. 数据集格式（JSONL）

每行一个 query，至少包含 `query` 和一组相关性条件。

```json
{"query":"电容器","selected_doc_id":"doc_xxx","expected_doc_id":"doc_xxx","expected_pages":[61,62]}
{"query":"真空断路器","selected_doc_id":"doc_xxx","expected_doc_id":"doc_xxx","expected_pages":[35,36]}
{"query":"11.4.1 串联电容补偿装置","selected_doc_id":"doc_xxx","relevant_any":[{"doc_id":"doc_xxx","page":61},{"doc_id":"doc_xxx","chapter_id":"ch_22"}]}
```

字段说明：

- `query`: 问题文本（必填）
- `selected_doc_id` / `selected_version_id`: 检索时施加过滤（可选）
- `expected_doc_id` / `expected_version_id` / `expected_doc_name`: 命中约束（可选）
- `expected_pages`: 相关页码列表（可选）
- `relevant_any`: 复杂匹配规则数组，命中任意一条即算相关（可选）

## 2. 执行命令

先重建目标文档索引（可选）：

```bash
.venv/bin/python services/worker/scripts/reindex_from_mineru_json.py \
  --mineru-json /path/to/mineru.json \
  --doc-id doc_xxx \
  --version-id ver_xxx \
  --doc-name "xxx.pdf" \
  --qdrant-endpoint http://localhost:6333 \
  --reset-collection
```

再执行评测：

```bash
.venv/bin/python services/api-server/scripts/eval_retrieval.py \
  --dataset /path/to/retrieval_eval.jsonl \
  --top-k 10 \
  --output outputs/retrieval_eval.latest.json \
  --report outputs/retrieval_eval.report.json
```

## 3. 输出指标

- `hit_at_5`: 前 5 条命中率
- `hit_at_10`: 前 10 条命中率
- `evidence_hit_rate_at_10`: Top10 证据命中率
- `mrr`: 平均倒数排名（越高越好）
- `clause_hit_at_k`: 条文型查询在 TopK 内命中预期条文号的比例（ClauseHit@k）
- `constraint_coverage`: 约束规格（条文号/强制性/约束类型）在 TopK 的覆盖率（ConstraintCoverage）
- `citation_completeness`: 相关命中文档中“文档+页码+片段”完整引用比例（CitationCompleteness）
- `details`: 每条 query 的首个相关命中排名 `rank` 和 top1 样本
- `failed_samples`: 未命中的失败样本集合
- `release_gate`: 切流量门禁结论（阈值与通过状态）
- `allow_traffic`: `release_gate.passed` 的布尔镜像，用于流水线判定

默认门禁阈值（可通过环境变量覆盖）：

- `EVAL_MIN_QUERIES`（默认 `30`）
- `EVAL_MIN_HIT10`（默认 `0.75`）
- `EVAL_MIN_MRR`（默认 `0.45`）
- `EVAL_MIN_EVIDENCE_HIT10`（默认 `0.80`）
- `EVAL_MIN_CLAUSE_HIT_AT_K`（默认 `0.70`，仅在数据集包含条文预期时生效）
- `EVAL_MIN_CONSTRAINT_COVERAGE`（默认 `0.70`，仅在数据集包含约束规格时生效）
- `EVAL_MIN_CITATION_COMPLETENESS`（默认 `0.85`，仅在存在相关命中时生效）
