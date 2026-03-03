# 扩展补丁包：规范条文说明 + 表格增强 + 去噪（v1）

本补丁包把 3 个能力一起提供：
1) 规范条文说明（Explanation）专用索引：正文与条文说明同 PDF 内，按 `clause_id` 关联，查询时自动成对呈现。
2) 表格三件套入库 + 跨页拼接 + VL 兜底：同一张表生成 `raw/summary/rowfacts` 三类 chunk；跨页表格自动拼接；失败时可切图调用 VL 模型（不要求回填 PDF）。
3) 页眉页脚/水印去噪：正则过滤 + 全局重复行过滤 + layout 裁剪（header/footer band）+ 可选 `ignore_regions`（二维码等）。

这是增量式补丁，可叠加到现有 `MinerU -> Worker -> Qdrant -> Search/Rerank -> UI evidence pack` 流程。

## 最小接入点
1) Worker：MinerU 输出后可先执行 `text_denoiser.py`；可选 `layout_cropper.py`
2) Ingest：规范正文 clause chunks + `explanation_parser.py` 生成说明 chunks；表格 blocks 用 `table_threepack.py`
3) Query：检索后可按 `clause_id` 自动补齐正文/说明
