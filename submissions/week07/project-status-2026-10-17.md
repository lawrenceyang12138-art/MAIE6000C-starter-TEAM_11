# Team 11 项目进度与 W07 验收差距（2026-10-17）

## 结论

项目还没有达到 M1。当前仓库是**四个可独立运行的模块，而不是一条已经连通的产
品**。B 的解析、证据和复核质量已具备提交条件；决定能否演示的剩余工作集中在 A
的扫描/worker/公共路由、C 的 schema 适配，以及 D 的真实接口联调。

按团队排期，M1 的最晚检查时间是 **10 月 18 日 18:00**，正式 W07 汇报是
**10 月 24 日**。距离 M1 已不足一天，应停止扩功能，只做最窄链路。

## 课程与排期要求

### 必过的最窄链路

```text
选择文件夹
→ API 返回 root/job，不在请求内做重活
→ worker 扫描并创建文件/内容版本/解析任务
→ B 解析并保存带页码 chunk
→ C 在授权且 current 的 chunk 上完成关键词检索
→ 返回文件、版本、chunk、页码和原文
→ D 在浏览器中完成授权、进度、搜索和证据展开
```

### M1 固定验收基线

- 固定 16 个文件：12 个正常文本 PDF（至少 2 个子目录）、3 个异常 PDF（加密/
  无文字层/损坏）和 1 个不支持文件。
- 固定 10 条查询：5 条关键词、5 条语义描述，包含中英文，至少 2 条语义查询不依赖
  原文关键词。
- 关键词查询命中预期文档 **5/5**。
- 原文、版本、页码一致 **10/10**。
- 12 个正常 PDF 完成；3 个异常 PDF 有明确原因；1 个不支持文件有记录。
- 重复扫描新增文件/版本 **0**；演示前后原件 SHA-256 变化 **0**。
- 最窄链路阻断级 P0/P1 缺陷为 **0**。

### 正式提交物

- `report.md` 至少 3000 字；A/B/C 各至少 700 字，D 至少 900 字。
- Week07 README 十栏齐全，并附 AI Use Statement。
- 12 页同名 PPT/PDF；A/B/C/D 各三页。
- `demo-script.md` 至少 600 字、6 步流程；真实演示录像 3–4 分钟。
- 四份讲稿各不超过 3 分钟；Q&A 至少 8 问。
- `release-manifest-final.md`、运行包、模型缓存、代码 SHA 与备份一致。

## 分支实际状态

| 成员/分支 | 最新状态 | 判定 |
| --- | --- | --- |
| A `w7-scan-dispatch` | `7b084e5`，仅决策、owner-map、配置和 W03 测试文件名修复 | **关键实现仍缺** |
| B `w7-parsing` | 本次提交后包含解析、证据、关系、复核及 HTTP 路由 | 模块可验收，依赖 A 接线 |
| C `feat/c-search-model-evaluation` | 独立关键词/向量/混合搜索可运行 | 与 B schema 不兼容，尚未适配 |
| D `Role_D` | 前端页面与 adapter 已有，搜索仍是本地过滤 | 尚未贯真实主链路 |
| `main` | 仍是 starter `abacacd` | 没有团队集成版本 |

## 按角色的完成度

### A：找文件

已完成：

- 目录/版本/chunk 字段决策。
- `current_version_id` 由扫描事务维护的决策。
- 服务端 mount allowlist 和只读 compose 配置。
- W03 测试文件名修复。

仍缺：

1. `services/scan/`：遍历、哈希、版本复用、`current_version_id` 更新。
2. `scan_root` worker：首次/重复/文件变化/异常混入。
3. `extract_file` dispatch：调用 B 的 `handle_extract_file()`。
4. `/mounts`、directories、完整 roots/jobs 路由和公开状态映射。
5. 解析后触发 keyword index/embedding；失败重试与可见状态。
6. 单一 Alembic head 的最终 schema。

### B：读文件

已完成：

- 逐页 PDF 抽取、文件 SHA-256、页码保留。
- 700 字符切块、120 字符重叠、绝不跨页。
- chunk 原子替换与稳定 ID。
- 加密/损坏/无文字层/非 PDF/缺失/读取中变化等失败状态。
- 证据当前版本、文件存在、目录授权校验。
- 有界关系候选、人工复核 revision guard。
- 12 正常/3 异常/1 不支持回归。
- 12/12 独立页码归属检查；66 页、0 损坏字符、20/20 片段页码正确。
- `GET /files`、`GET /evidence/{chunk_id}`、
  `GET /versions/{id}/relations`、`POST /relations/{id}/reviews`。
- `active` 和 `paused` root 均可读已有证据；`revoking/revoked` 被拒绝。

仍缺：

- 正式 16 文件语料到达后用同一回归重跑。
- A 的扫描产生真实 `current_version_id` 后做一条真实浏览器链路。

### C：搜文件

已完成：

- 中英文 tokenize、关键词评分、hybrid 合并。
- 本地 E5 embedding、向量校验、AI 失败降级。
- 独立搜索测试和评测证据。

仍缺：

1. 删除重复的 `source_files/source_versions/source_chunks`。
2. 新增 `chunk_search_index`，以 B 的 `source_chunks.id` 为外键。
3. 迁移接在 `445f908b73b4` 后。
4. retrieval 改读 B 的 current file/version/chunk。
5. 搜索加 `root_id` 授权过滤。
6. 响应统一为 `version_id/version_created_at/chunk_id/ordinal/page`。

### D：用文件

已完成：

- 文件夹选择、进度、文件列表、证据展开的界面与 adapter。
- 错误、空结果、降级状态的基础展示。

仍缺：

1. 接 A 真实的 mounts/roots/jobs/files 路由。
2. 搜索框调用 C 的 `POST /search`，去掉浏览器本地过滤。
3. 证据改用 `GET /evidence/{chunk_id}`。
4. 小写 reason code 映射。
5. 干净数据库上的浏览器端到端验收和截图。

## 本次实际实现

已在 B 分支加入 `services/api/app/parsing_routes.py`：

- `GET /files?root_id=...`
- `GET /evidence/{chunk_id}`
- `GET /versions/{version_id}/relations`
- `POST /relations/{relation_id}/reviews`

错误码映射到 HTTP：

| code | HTTP |
| --- | --- |
| `chunk_not_found` / `file_missing` | 404 |
| `root_revoked` | 403 |
| `version_superseded` | 409 |
| `no_current_version` | 503 |
| `review_conflict` | 409 |
| `invalid_decision` / correction validation | 422 |

这些路由放在独立文件中，A 合并时只需保留 `main.py` 中的 router 注册，减少多人
同时修改主 API 文件的冲突。

## 当前最重要的执行顺序

在 10.18 18:00 前，只做以下顺序，不新增 OCR、复杂图谱或部署优化：

1. **A 立即合并 B 并实现扫描、current pointer、worker 的
   `extract_file`。**
2. **A 实现 `/mounts` 和 `/files` 所需的真实扫描数据；B 的 evidence/
   relations/reviews 路由已提供。**
3. **C 放弃第二套三表，按 B 的 chunk 改编 keyword 搜索。**
4. **D 使用真实接口，不再以本地过滤或 mock 作为主链路。**
5. **D 用 16 文件语料跑首次、重复、异常混入三种场景。**
6. **全员记录 M1 结果；若失败，按排期裁掉语义和关系，不声称完整 W07。**

## 是否已经可以演示

**不能。** 当前能演示的是：

- B 模块的命令行和测试证据。

不能演示的是：

- 从浏览器选择文件夹后自动扫描/解析/搜索；
- 搜索结果回到同一原文证据；
- 失败任务在页面可见并重试；
- 干净数据库上的完整 W07 垂直切片。

因此现在不能把“模块测试通过”写成“W07 已达标”。
