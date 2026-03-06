# 2026-03-06 RAG 全链路冒烟验证记录

## 范围

本次记录覆盖 2 个“新增 PDF -> 上传 -> 处理 -> 索引 -> 检索 -> 约束抽取”的真实链路冒烟样本：

1. `GB50300-2013 建筑工程施工质量验收统一标准.pdf`
2. `GB-T13955-2017 剩余电流动作保护装置安装和运行.pdf`

运行环境为本地重建后的 `docker-api-server-1` 与 `worker`，默认运行时模型为：

- OCR: `deepseek-ai/DeepSeek-OCR`
- Embedding: `Qwen/Qwen3-Embedding-8B`
- Rerank: `Qwen/Qwen3-Reranker-8B`
- Embedding dimensions: `4096`

## 样本 A: GB50300-2013

源文件：

- `C:\Users\palmtom\Desktop\电力工程投标规范\GB50300-2013 建筑工程施工质量验收统一标准.pdf`

上传结果：

- `doc_id=doc_c574be0f9d9d`
- `version_id=ver_26b045cc0da1`
- `status=accepted`

处理完成结果：

- `status=processed`
- `chunks=127`
- `doc_pages_upserted=34`
- `text_len=17459`
- `quality_gate.grade=A`
- `embedding_stats.providers={"siliconflow":127}`

检索验证：

- 问题：`工程质量验收均应在什么基础上进行？`
- 结果：`rank=1`
- 命中条款：`3.0.6`
- 页码：`p.9`
- 证据：`工程质量验收均应在施工单位自检合格的基础上进行`

约束抽取验证：

- 问题：`经返修或加固处理仍不能满足安全或重要使用功能的分部工程是否允许验收？`
- 模式：`constraint`
- 首条命中：`5.0.8`
- 页码：`p.13`
- 结果字段：
  - `is_mandatory=true`
  - `risk_level=high`
- 关键证据：`严禁验收`

判定：

- `通过`

## 样本 B: GB-T13955-2017

源文件：

- `C:\Users\palmtom\Desktop\电力工程投标规范\GB-T13955-2017 剩余电流动作保护装置安装和运行.pdf`

上传结果：

- `doc_id=doc_66d33a68cdf0`
- `version_id=ver_d9889263225a`
- `status=accepted`

处理完成结果：

- `status=processed`
- `chunks=46`
- `doc_pages_upserted=23`
- `text_len=19561`
- `quality_gate.grade=A`
- `embedding_stats.providers={"siliconflow":46}`

检索验证：

- 问题：`在TN系统中安装使用RCD前应如何处理？`
- 验证方式：`hybrid_search + version scope`
- 结果：`rank=1`
- 命中条款：`4.2.2.2`
- 页码：`p.8`
- 证据：`应将 TN-C 系统改造为 TN-C-S、TN-S 系统或局部 TT 系统后，方可安装使用 RCD`

约束抽取验证：

- 问题：`在TN系统中安装使用RCD前应如何处理？`
- 模式：`constraint`
- 当前排序前 10 中，`4.2.2.2` 未稳定排到首位
- 当前前 10 主要包含：
  - `4.5`
  - `4.4.1`
  - `4.2.4`
  - `4.2.1`
  - `4.2.2.1`
  - `4.2.3`
  - `4.1`

判定：

- 检索链路：`通过`
- 约束抽取链路：`部分通过`
- 结论：本样本证明“新增文档可完成上传、解析、索引和定向召回”，但 `constraint` 模式对 `TN-C/TN-C-S/RCD` 这类拓扑型约束问法仍存在排序偏差。

## 本轮烟测中补做的修正

### 1. 强制性约束补判

为避免索引阶段未显式打上 `is_mandatory` 时漏判，本轮在约束摘要阶段增加了文本补判：

- 已覆盖：`必须 / 应当 / 不得 / 严禁 / 禁止 / 方可 / 只允许`

对应回归测试：

- `test_chat_constraint_mode_infers_mandatory_from_guard_terms`
- `test_chat_constraint_mode_infers_mandatory_from_only_allow_terms`

### 2. 解析伪文本过滤

为避免 OCR/稀疏侧车伪文本混入约束证据，本轮增加了以下噪声标记过滤：

- `value of the product`
- `value of the power system`

对应回归测试：

- `test_chat_constraint_mode_filters_watermark_and_parse_artifacts`

## 验收判断

按“新增 PDF 真实入链路”的标准，本次烟测结论如下：

- 样本 A：`全通过`
- 样本 B：
  - 上传/处理/索引：`通过`
  - 定向检索：`通过`
  - 约束抽取：`存在排序缺口`

综合判断：

- 系统已具备“新增规范 PDF 入库后完成索引与检索”的稳定能力。
- 作为投标约束抽取系统，主链路已可用，但对 `GB-T13955-2017` 这类带 `TN-C/TN-C-S/RCD` 拓扑术语的问题，`constraint` 排序仍需继续微调后才能算完全收口。
