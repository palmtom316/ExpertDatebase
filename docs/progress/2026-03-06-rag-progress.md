# 2026-03-06 RAG 改造进度

## 今日已完成
- 检索主链路增强（`search_service.py`）：
  - 新增 `route plan`（precision query 路由裁剪）
  - 新增 route gating（`sparse/keyword/filter_keyword` 精准门控与词法门控）
  - rerank 文本加入元数据拼装（`doc_name/standard_no/clause_id/route`）
  - debug 输出增加 `route_plan` 与 `route_gate_counts`
- 配置与运行时：
  - `.env.example` 增补路由门控和 rerank 元数据开关
  - `docker/docker-compose.yml` 透传新增检索开关到 `api-server`
- API 侧修复：
  - 修复 `admin_jobs.reprocess` 对 `reuse_mineru_artifacts=false` 的过滤问题（false 现在可透传）
- Worker 侧改造：
  - `MinerUClient` 本地 PDF fallback 增强：
    - 接入 `pypdf` 本地解析
    - 单字断行合并策略
    - `layout` 提取失败/空结果时自动回退常规提取
  - `services/worker/Dockerfile` 增加 `pypdf` 依赖
- 回归数据与测试：
  - 新增双文档检索回归集：`datasets/v1.0/retrieval_eval_gb_pair_10.jsonl`
  - 新增/更新测试：
    - `tests/api/test_admin_jobs_reprocess_runtime_config.py`
    - `tests/api/test_hybrid_search_filters.py`
    - `tests/worker/test_mineru_runtime_config.py`

## 验证结果
- 本地单测通过：`42 passed`
- 容器重建完成：`api-server`、`worker`
- 两份 GB 文档已多轮重处理与索引验证（含 `reuse_mineru_artifacts=false` 路径）

## 当前阻塞（未完全解决）
- 两份测试 PDF 提取出的有效正文极少（当前仍以页眉/水印为主），导致每个版本仅少量可用 chunk，直接拉低召回与 MRR。
- 在该输入质量下，`/api/admin/eval/retrieval/run` 对 `retrieval_eval_gb_pair_10.jsonl` 的结果仍为：
  - `hit@10 = 0.0`
  - `mrr = 0.0`

## 明日继续计划
- 优先解决“标准号过滤 + sparse 元数据缺失”的召回问题（`standard_no/doc_name` 在 sparse 路由透传与过滤对齐）。
- 评估并接入更稳定的 OCR/解析来源（避免仅页眉文本入索引）。
- 基于上述修复再次跑双文档回归，目标恢复到可用 MRR 区间。
