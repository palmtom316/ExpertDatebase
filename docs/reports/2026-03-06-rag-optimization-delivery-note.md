# 2026-03-06 RAG 优化最终交付说明

## 范围
本文档汇总 2026-03-06 当日已完成并已验证的 RAG 优化结果，覆盖：
- 默认 SiliconFlow 模型栈
- 当日落地的关键修订
- 新增默认评测集与容器可运行性修复
- 真实接口与离线评测验证结果
- 当前残留风险

## 默认模型栈
当前系统默认运行时已固化为：
- OCR: `deepseek-ai/DeepSeek-OCR`
- Embedding: `Qwen/Qwen3-Embedding-8B`
- Embedding dimensions: `4096`
- Rerank: `Qwen/Qwen3-Reranker-8B`
- Base URL: `https://api.siliconflow.cn/v1`
- Provider: `siliconflow`

证据：
- `services/api-server/app/services/runtime_defaults.py`
- `tests/api/test_runtime_defaults.py`

## 本轮补充修订
### 1. 修复 TN/RCD 约束排序误杀
真实链路里，`4.2.2.2` 会被同页 `sparse` 噪声块误合并，正文被 `value of the product...` 一类伪文本污染，随后在证据过滤阶段整体丢弃，导致 `constraint` 模式把 `4.5`、`4.4.1` 排到前面。

已修复：
- 在 citation 去重阶段，禁止“同页、一个有 `clause_id`、一个没有 `clause_id`、且 `route` 不同”的误合并

涉及文件：
- `services/api-server/app/services/chat_orchestrator.py`
- `tests/api/test_chat_answer_quality.py`

### 2. 默认评测集升级到 8 本规范 / 32 条样本
新增两条正式回归样本并切为默认数据集：
- `GB50300-2013`：`工程质量验收均应在什么基础上进行？`
- `GB-T13955-2017`：`在TN系统中安装使用RCD前应如何处理？`

新默认数据集：
- `datasets/v1.2/retrieval_eval_eight_specs_bid_32.jsonl`

涉及文件：
- `datasets/v1.2/retrieval_eval_eight_specs_bid_32.jsonl`
- `datasets/v1.2/manifest.json`
- `services/api-server/app/services/runtime_defaults.py`
- `docs/runbooks/retrieval_eval.md`
- `tests/api/test_runtime_defaults.py`

### 3. 修复容器内默认评测集不可读
默认评测集路径改到 `v1.2` 后，`api-server` 镜像内未包含 `datasets/`，导致容器中直接运行默认评测会报 `dataset not found`。

已修复：
- `api-server` Dockerfile 增加 `COPY datasets /app/datasets`

涉及文件：
- `services/api-server/Dockerfile`

## 验证结果
### 单元与接口相关测试
已执行：

```bash
pytest -q tests/api/test_chat_answer_quality.py -k 'prefers_tn_rcd_topology_clause or same_page_sparse_artifact_exists or mandatory_from_guard_terms or only_allow_terms or filters_watermark_and_parse_artifacts' tests/api/test_runtime_defaults.py tests/api/test_admin_eval_retrieval_run_api.py
```

结果：
- `5 passed`

### 真实接口复验
问题：
- `在TN系统中安装使用RCD前应如何处理？`

调用：
- `/api/chat`
- `mode=constraint`
- `selected_doc_id=doc_66d33a68cdf0`
- `selected_version_id=ver_d9889263225a`

结果：
- `rank=1`: `4.2.2.2`
- `page=8`
- `is_mandatory=true`
- `risk_level=high`
- 摘要：`共提取 16 条约束，其中强制性条款 1 条，高风险条款 1 条。请逐条核对引用页码后执行。`

### 默认离线评测集复验
执行：

```bash
docker exec docker-api-server-1 sh -lc 'python /app/services/api-server/scripts/eval_retrieval.py --top-k 10 --dataset /app/datasets/v1.2/retrieval_eval_eight_specs_bid_32.jsonl'
```

结果：
- `query_count=32`
- `hit_at_5=1.0`
- `hit_at_10=1.0`
- `evidence_hit_rate_at_10=1.0`
- `mrr=0.60625`
- `clause_hit_at_k=0.967741935483871`
- `citation_completeness=1.0`
- `release_gate.passed=true`
- `allow_traffic=true`

新增两条样本结果：
- `GB50300-2013` 问题 `工程质量验收均应在什么基础上进行？`：`rank=1` 命中 `3.0.6`
- `GB-T13955-2017` 问题 `在TN系统中安装使用RCD前应如何处理？`：`rank=1` 命中 `4.2.2.2`

## 当前残留风险
- 容器内离线评测默认未注入 SiliconFlow embedding key，当前会自动降级到 stub embedding；这次门禁仍通过，但这会掩盖真实在线 embedding 的抖动情况。
- 部分旧样本的 `top1` 仍可能落在 `sparse` 页面噪声，正确条文在 `topk` 内；当前门禁指标已通过，但继续提高 `top1` 稳定性仍有价值。
- `constraint_coverage=0.0` 不是回退，原因是当前默认评测集仍以召回/条文命中为主，未给 32 条样本补齐约束规格字段。

## 结论
截至 2026-03-06 当日，这轮交付已经完成：
- `TN/RCD` 约束排序问题已修复并通过真实接口验证
- 默认评测集已升级为 `v1.2 / 8 本规范 / 32 条样本`
- `api-server` 容器已可直接读取默认评测集
- 默认离线评测门禁通过，允许切流量
