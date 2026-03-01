# MVP 上线验收清单

**项目**：ExpertDatebase / BidExpert
**版本**：M1 Foundation
**日期**：2026-03-01

## 使用说明

每一项由负责人完成后在 `[ ]` 中填 `x`，并签名。
所有 **MUST** 项通过后方可合并到 main 并部署生产环境。

---

## P0：基础安全（MUST ALL PASS）

- [x] `AUTH_ENABLED` 默认值已改为 `true`
- [x] `AUTH_TOKENS_JSON` 在 compose 中使用 `:?` 强制要求，无默认值
- [x] `POSTGRES_PASSWORD`、`MINIO_SECRET_KEY` 均已外置为必填 env var
- [x] `.env.example` 中所有敏感字段已替换为 `CHANGE_ME_REQUIRED` 占位符
- [x] 生产环境 `.env` 中无任何 `CHANGE_ME` 或 `changeme` 字样（人工确认）
- [x] Bandit 扫描：HIGH=0，MEDIUM=0（见 `docs/reports/2026-03-01-bandit-scan-results.md`）
- [ ] 已轮换所有曾出现在 VCS 历史中的密码（`git log` 确认无历史明文密码）

## P0：稳定性（MUST ALL PASS）

- [x] 上传接口改为流式读取，支持 ≥50MB PDF 不 OOM
- [x] `Dockerfile` CMD 包含 `alembic upgrade head`，数据库自动迁移
- [x] Qdrant payload index 包含 `doc_id`、`version_id` 等关键过滤字段
- [x] 实体索引 `PgEntityIndex` 已接入 chat/search，实体过滤链路通
- [x] `LLMRouter` BYOK 优先级已修复，runtime key 生效
- [x] Rate limiting：upload 5/min、chat 30/min、search 60/min

## P1：可观测性（MUST ALL PASS）

- [x] 所有服务（api-server / worker / scheduler）使用 structlog 结构化 JSON 日志
- [x] `/health` 端点返回 PG / Redis / Qdrant 真实探活结果，503 when degraded
- [x] docker-compose 中 postgres / redis / qdrant 均有 healthcheck
- [x] api-server / worker / scheduler 使用 `condition: service_healthy` 等待依赖

## P1：功能完整性（MUST ALL PASS）

- [x] PG-BM25 tsvector 迁移已创建（`0003_doc_pages_tsvector.py`）
- [x] `ENABLE_PG_BM25=1` 在 `.env.example` 中已激活
- [x] `ENABLE_STRUCTURED_LOOKUP=1` 已激活
- [x] Embedding 降级时输出 WARNING 日志（不再静默失败）
- [x] per-chunk `page_type` 按页面集合正确标注（非文档级别）
- [x] Frontend：App.vue 拆分为 5 个子组件，单文件均 ≤300 行

## P1：工程质量（SHOULD PASS）

- [x] `pyproject.toml` 包含 `uvicorn[standard]`、`slowapi`、`structlog`、pytest dev extras
- [x] CI/CD GitHub Actions 流水线（`.github/workflows/ci.yml`）存在且通过

## P2：功能激活（SHOULD PASS）

- [x] 稀疏检索路由已激活
- [x] 结构化查询路由已激活
- [ ] 在暂存环境完整跑通一次 PG-BM25 检索（端到端冒烟测试）
- [ ] 在暂存环境完整跑通一次结构化查询（端到端冒烟测试）

## P3：上线收口（MUST ALL PASS）

- [x] Bandit 安全扫描通过（MEDIUM=0，HIGH=0）
- [x] `upload.py` 语法错误已修复（AST parse 通过）
- [ ] 所有 127 项测试在 CI 中通过（`pytest -q` exit 0）
- [ ] Docker Compose 完整启动测试：`docker compose up --wait` 所有服务 healthy
- [ ] 压力测试：上传 5 个并发 PDF，系统无崩溃，上传端点 P95 < 10s
- [ ] 故障演练：手动 `docker stop redis`，api-server `/health` 返回 503，恢复后自动变回 200

---

## 签核

| 角色 | 姓名 | 日期 | 签名 |
|---|---|---|---|
| 开发负责人 | | | |
| QA 负责人 | | | |
| 运维负责人 | | | |
