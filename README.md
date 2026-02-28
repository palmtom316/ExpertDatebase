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

## Docker 启动（基础设施）

```bash
docker compose -f docker/docker-compose.yml up -d
```

## 测试

```bash
pytest -q
```
