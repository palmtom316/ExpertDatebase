# ExpertDatebase

ExpertDatebase 项目（MVP）

## 当前能力

- PDF 上传入库（本地或 MinIO）
- 文档注册（JSON 或 PostgreSQL）
- 处理任务入队（内存或 Redis）
- MinerU 后处理最小流水线（normalize/chapter/chunk）
- IE 抽取（含 grounding 字段）
- Hybrid 检索（向量 + filter）
- Chat 强引用输出
- 评测评分与 E2E 测试基线

## 快速开始

```bash
cd ExpertDatebase
cp .env.example .env
pytest -q
```

## 商业 LLM 配置（本地调试）

在 `.env` 里选择 provider：

```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=你的密钥
OPENAI_MODEL=gpt-4o-mini
# OPENAI_BASE_URL 可换成任意 OpenAI 兼容网关
```

或：

```bash
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=你的密钥
ANTHROPIC_MODEL=claude-3-5-sonnet-latest
```

不配置密钥时会自动回退本地 stub（便于离线开发）。

## Docker 启动（后端 + 基础设施）

```bash
docker compose -f docker/docker-compose.yml up -d postgres redis minio qdrant api-server worker scheduler
```

后端健康检查：

```bash
curl http://localhost:8080/health
```

## 本地联调：上传 PDF 并启动抽取

1. 启动服务后，上传文件：

```bash
curl -sS -X POST "http://localhost:8080/api/upload" \
  -F "file=@/绝对路径/your.pdf"
```

响应会返回 `doc_id/version_id/object_key`，其中 `version_id` 用于查状态。

2. 查看抽取进度：

```bash
curl -sS "http://localhost:8080/api/admin/docs/<version_id>/artifacts"
```

`intermediate.status` 会经历 `uploaded -> processing -> processed`（失败时为 `failed`）。

3. 发起问答（走商业 LLM 或本地 stub）：

```bash
curl -sS -X POST "http://localhost:8080/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"question":"合同金额是多少？"}'
```

## Docker 启动（前端）

```bash
docker compose -f docker/docker-compose.yml --profile ui up -d --build web-ui
```

前端访问：`http://localhost:5500`（已支持 PDF 上传并实时轮询抽取状态）。

## 评测与趋势

- 一键加入评测集：`POST /api/admin/eval/datasets/add`
- 启动评测运行：`POST /api/admin/eval/runs/start`
- 查看趋势指标：`GET /api/admin/eval/trends`

## 测试

```bash
pytest -q
```
