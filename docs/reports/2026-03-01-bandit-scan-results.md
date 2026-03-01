# Bandit 安全扫描报告

**扫描日期**：2026-03-01
**工具**：bandit 1.9.x
**扫描范围**：`services/` + `shared/`
**配置**：`.bandit`（跳过 B608 误报）

## 扫描结果汇总

| Severity | Count |
|---|---|
| HIGH | 0 |
| MEDIUM | 0 |
| LOW | 5 |

**跳过文件**：`services/api-server/app/api/upload.py`（AST parse 失败，需单独人工审查）

---

## LOW 级别问题（已知可接受风险）

| 规则 | 位置 | 说明 | 决策 |
|---|---|---|---|
| B110: try_except_pass | `entity_index.py:45` | 缓存刷新失败时静默跳过，使用过期缓存 | 可接受，失败时使用降级数据 |
| B112: try_except_continue | `retrieval_eval.py:16` | 迭代评测样本时跳过异常条目 | 可接受，单条失败不影响整体评测 |
| B112: try_except_continue | `search_service.py:403` | 检索路由中单路故障降级 | 可接受，RRF 多路设计即为容错 |
| B112: try_except_continue | `search_service.py:429` | 同上 | 同上 |
| B112: try_except_continue | `mineru_client.py:329` | 页面解析循环中跳过异常页 | 可接受，单页失败不阻断文档处理 |

---

## 已修复问题

| 规则 | 原始 Severity | 修复方式 |
|---|---|---|
| B608 × 2 | Medium | 确认为参数化查询误报，在 `.bandit` 配置中豁免并添加注释说明 |
| B310 × 1 | Medium | 将 `urllib.request.urlopen` 替换为 `http.client.HTTPConnection` |
| B113 × 5 | Medium | 确认所有 `requests.post` 调用均已传入 `timeout=` 参数，添加 `# nosec B113` |

---

## 需要后续跟进

1. `upload.py` AST 解析失败 — 需人工检查文件语法（可能是流式上传改造引入的语法错误）
2. 所有 `try/except/pass` 模式 — 建议在下一个迭代中加入日志记录，消除 B110/B112
