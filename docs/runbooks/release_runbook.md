# ExpertDatebase 上线 Runbook（MVP）

## 目标
- 一键拉起 API / Worker / Scheduler / PostgreSQL / Redis / MinIO / Qdrant
- 完成上线前验收与回滚预案

## 上线前检查
1. 配置 `APP_ENV=production` 并确认生产 secrets 非默认值。
2. 执行迁移：`alembic upgrade head`。
3. 执行测试：
   - `pytest -q`
   - `pytest tests/api -q`
   - `pytest tests/worker -q`
   - `pytest tests/eval -q`
4. 验证健康：`GET /health` 返回 `{"status":"ok"}`。
5. 验证 scheduler 日志存在周期触发记录。

## 启动命令
```bash
docker compose -f docker/docker-compose.yml up -d --build
```

## 冒烟用例
1. 上传 PDF：`POST /api/upload`
2. 查询状态：`GET /api/admin/docs/{version_id}/artifacts`
3. 启动评测：`POST /api/admin/eval/runs/start`
4. 查看趋势：`GET /api/admin/eval/trends`

## 回滚方案
1. 停止当前版本：
```bash
docker compose -f docker/docker-compose.yml down
```
2. 回退到上一 tag/commit，重新构建并启动：
```bash
git checkout <previous-tag-or-commit>
docker compose -f docker/docker-compose.yml up -d --build
```
3. 如新迁移影响业务，执行相应 `alembic downgrade` 回退。

## 告警与排查
- 优先查看：`api-server`、`worker`、`scheduler` 容器日志。
- 关键异常：LLM 调用失败、Qdrant/MinIO 连通失败、评测结果持续低于阈值。
