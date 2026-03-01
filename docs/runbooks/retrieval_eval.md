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
  --output outputs/retrieval_eval.latest.json
```

## 3. 输出指标

- `hit_at_5`: 前 5 条命中率
- `hit_at_10`: 前 10 条命中率
- `mrr`: 平均倒数排名（越高越好）
- `details`: 每条 query 的首个相关命中排名 `rank` 和 top1 样本
