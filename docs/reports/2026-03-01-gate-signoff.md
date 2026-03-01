# 生产上线 Gate Sign-off

**项目**：ExpertDatebase / BidExpert M1 Foundation
**日期**：2026-03-01
**分支**：`feature/m1-foundation` → `main`

---

## 已完成的修订工作（P0–P3 全部落地）

### P0 基础安全与稳定性
| 任务 | 文件 | 状态 |
|---|---|---|
| Auth 默认开启 | `docker-compose.yml` | ✅ |
| Secrets 外置（PG/MinIO/Auth） | `docker-compose.yml`, `.env.example` | ✅ |
| 上传流式处理（防 OOM） | `api/upload.py` | ✅ |
| 数据库自动迁移 | `api-server/Dockerfile` | ✅ |
| 实体索引接入 | `services/entity_index.py`, `chat.py`, `search.py` | ✅ |
| LLM Tier 路由修复（BYOK 优先） | `services/llm_router.py` | ✅ |
| Rate Limiting（slowapi） | `main.py`, `upload.py`, `chat.py`, `search.py` | ✅ |
| CI/CD 流水线 | `.github/workflows/ci.yml` | ✅ |

### P1 可观测与功能完整
| 任务 | 文件 | 状态 |
|---|---|---|
| 结构化日志（structlog） | `shared/logging_config.py`, worker, scheduler | ✅ |
| Keyword 检索性能（PG-BM25 迁移） | `0003_doc_pages_tsvector.py` | ✅ |
| Qdrant Payload Index 补全 | `worker/qdrant_index.py` | ✅ |
| pyproject.toml 补全 | `pyproject.toml` | ✅ |
| 前端组件拆分（5 个子组件） | `src/frontend/src/components/` | ✅ |
| 真实 healthcheck（PG+Redis+Qdrant） | `api-server/main.py`, `docker-compose.yml` | ✅ |
| per-chunk page_type 修复 | `worker/runner.py` | ✅ |
| Embedding 降级告警 | `services/search_service.py` | ✅ |

### P2 功能激活
| 任务 | 文件 | 状态 |
|---|---|---|
| 稀疏检索激活（PG-BM25） | `.env.example` | ✅ |
| 结构化查询激活 | `.env.example` | ✅ |

### P3 安全扫描与收口
| 任务 | 文件 | 状态 |
|---|---|---|
| Bandit 扫描（HIGH=0, MEDIUM=0） | `.bandit`, 各源文件 | ✅ |
| upload.py 语法错误修复 | `api/upload.py:217` | ✅ |
| MVP 验收清单 | `docs/reports/2026-03-01-mvp-acceptance-checklist.md` | ✅ |
| Bandit 报告 | `docs/reports/2026-03-01-bandit-scan-results.md` | ✅ |

---

## 剩余事项（部署前需人工完成）

以下事项需在部署生产前由团队完成，不属于本次代码修订范围：

1. **密码历史清理**：运行 `git log --all -S "changeme"` 确认历史 commit 中无明文密码；如有，使用 `git filter-repo` 清除后 force push。
2. **CI 通过确认**：确认 `feature/m1-foundation` 分支 CI 全部绿灯（127 项测试）。
3. **Docker Compose 冒烟**：在暂存环境运行 `docker compose up --wait`，确认所有服务达到 `healthy`。
4. **端到端冒烟测试**：上传一份测试 PDF，等待 `processed`，发送一个问题，验证 RAG 返回答案。
5. **故障演练**：手动 kill redis 容器，观察 `/health` 返回 503；重启后观察自动恢复为 200。
6. **生产 .env 准备**：基于 `.env.example` 创建生产 `.env`，填写所有 `CHANGE_ME_REQUIRED` 字段。

---

## 决定

- [ ] **通过 Gate** — 所有 MUST 项验收完毕，批准合并到 main 并部署生产
- [ ] **有条件通过** — 注明待办事项：___
- [ ] **拒绝** — 原因：___

**签核日期**：
**签核人**：
