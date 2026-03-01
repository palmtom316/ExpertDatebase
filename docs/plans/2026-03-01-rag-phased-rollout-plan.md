# RAG 分阶段落地清单（P0/P1/P2）

日期：2026-03-01
状态：待审批
适用仓库：ExpertDatebase（当前主干）

## 目标
在不推翻现有架构前提下，分阶段提升索引与查询质量：
- P0：从“能跑”到“可用”
- P1：从“可用”到“稳定准”
- P2：从“稳定准”到“复杂可答”

---

## P0：召回层救火（必须先做）

### 1. Query Analyzer V2（统一三路输入）
改造输出：`(filter_json, sparse_query, dense_query_text)`

覆盖：
- 人名、角色、kV、金额
- 条款号（如 `11.4.1`）
- 证书号、标准号

建议修改：
- `services/api-server/app/services/filter_parser.py`

验收指标：
- 规则抽取准确率（抽样 100 问）≥ 90%
- 条款号识别召回率 ≥ 95%

### 2. 稀疏检索正式化（优先 PG tsvector，Sirchmunk 可切换）
新增：
- `services/api-server/app/services/retrieval/sparse/pg_bm25.py`
- `services/api-server/app/services/retrieval/sparse/sirchmunk_client.py`

约束：统一返回字段 `doc_id/page_no/excerpt/score/source`

验收指标：
- 编号/型号/kV/金额类问题 Recall@10 ≥ 0.75
- 稀疏路可独立开关，关闭后主链路可用（回滚通过）

### 3. 三路召回 → 融合 → rerank → evidence pack
- 三路：dense + sparse + structured（P1补齐 structured 细节）
- 统一 RRF 融合后 rerank，再生成 evidence pack

建议修改：
- `services/api-server/app/services/search_service.py`

验收指标：
- Recall@10 较当前基线 +30%（绝对值）
- MRR ≥ 0.45
- EvidenceHitRate@10 ≥ 0.80

### 4. 入库质量治理（补齐规范）
- 按页文本稳定落盘（支持 sparse/sidecar）
- 结构化 chunking + 质量闸门阈值配置化

建议修改：
- `services/worker/worker/normalize.py`
- `services/worker/worker/chunking.py`
- `services/worker/worker/quality_gate.py`
- `services/worker/worker/runner.py`

验收指标：
- 重复页眉页脚噪声块下降 ≥ 80%
- 低质量块拒绝入库且可追踪原因

### 5. 离线评测纳入常规流程
- 固化 50 条真实问题集（最低 30）
- 输出 Hit@5/10、MRR、失败样本

建议修改：
- `services/api-server/scripts/eval_retrieval.py`
- `services/api-server/app/services/retrieval_eval.py`

验收指标：
- 每次重建索引可自动出报告
- 无评测报告不允许切流量

---

## P1：结构化与抽取增强

### 1. Structured Lookup 优先路由
- 证书号/标准号/人员资质/项目编号优先走结构化查询
- 与 dense/sparse 融合

新增建议：
- `services/api-server/app/services/retrieval/structured_lookup.py`

验收指标：
- 字段型问题 EvidenceHitRate@10 ≥ 0.90
- 字段型问题 Top1 命中率 ≥ 0.70

### 2. LangExtract（in-process）接入
新增建议：
- `services/worker/worker/ie/engines/langextract_engine.py`
- `services/worker/worker/ie/grounding/page_offset_mapper.py`
- `services/worker/worker/ie/validators/power_field_validator.py`

要求：
- 可插拔引擎：`custom | langextract`
- char offset → page_no 可追溯
- fatal 字段校验（kV/资质等级/金额数量级）

验收指标：
- FieldAcc 提升 ≥ 15%
- SourceAcc 不下降
- Fatal 字段错误率 ≤ 1%

### 3. 表格证据增强
- 表格按行摘要入库
- 表格行可直接进入 evidence pack

验收指标：
- 表格问题 Recall@10 ≥ 0.80
- “有表无证据”比例下降 ≥ 50%

---

## P2：复杂推理增强与灰度上线

### 1. Sirchmunk sidecar 正式化
- API/索引目录规范落地
- 增加熔断降级与可回滚

验收指标：
- sidecar 故障时自动降级主链路，成功率不低于当前

### 2. GraphRAG sidecar（复杂问题触发）
- rule/fallback 触发
- 作为第四路候选参与 RRF

验收指标：
- 多条件问题 Recall@10 再提升 ≥ 15%
- 复杂问句 EvidenceHitRate@10 ≥ 0.85
- P95 延迟可控（建议 ≤ 3.5s）

### 3. A/B 灰度与回滚
开关建议：
- `ENABLE_SIRCHMUNK`
- `ENABLE_LANGEXTRACT`
- `ENABLE_YOUTU_GRAPHRAG`

验收指标：
- 一键回滚 < 1 分钟
- 灰度期间 fatal 率不高于基线

---

## 统一 DoD（最终验收）
1. Recall@10 达到可用阈值（建议 ≥ 0.75，且显著高于当前）
2. MRR ≥ 0.45
3. EvidenceHitRate@10 ≥ 0.80
4. Fatal 字段错误率 ≤ 1%
5. 回答必须有引用或明确“证据不足”
6. 各增强模块可独立关闭并回到旧链路

---

## 建议周期
- P0：3-5 天
- P1：4-7 天
- P2：5-10 天（含灰度观察）

