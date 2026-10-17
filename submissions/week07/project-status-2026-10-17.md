# Team 11 项目进度与 W07 验收差距（2026-10-17）

## 结论

项目还没有完成浏览器级 M1，但现在已经有了一条真实可运行的后端垂直切片。
`w7-integration-bootstrap` 合并了 A 的配置、D 的语料/前端和 B 的解析证据，
并补了扫描、worker、keyword search 与 canonical routes。剩余工作集中在 C 的
schema 适配和 D 的结果页真实搜索联调。

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
| A `w7-scan-dispatch` | `7b084e5`，仅决策、owner-map、配置和 W03 测试文件名修复 | 原分支仍缺；集成分支已补可运行实现 |
| B `w7-parsing` | 本次提交后包含解析、证据、关系、复核及 HTTP 路由 | 模块可验收，依赖 A 接线 |
| C `feat/c-search-model-evaluation` | 独立关键词/向量/混合搜索可运行 | 与 B schema 不兼容，尚未适配 |
| D `Role_D` | 前端页面与 adapter 已有，搜索仍是本地过滤 | 尚未贯真实主链路 |
| `w7-integration-bootstrap` | A+B+D 已合并，扫描/worker/search/证据及 UI 代码已接通 | **尚缺人工浏览器走查/截图** |
| `main` | 仍是 starter `abacacd` | 未合并集成分支 |

## 按角色的完成度

### A：找文件

已完成：

- 目录/版本/chunk 字段决策。
- `current_version_id` 由扫描事务维护的决策。
- 服务端 mount allowlist 和只读 compose 配置。
- W03 测试文件名修复。

集成候选已补，仍需 A 审核：

1. `services/scan/`：遍历、哈希、版本复用、`current_version_id` 更新。
2. `scan_root` worker：首次/重复/文件变化/异常混入。
3. `extract_file` dispatch：调用 B 的 `handle_extract_file()`。
4. `/mounts`、directories、canonical roots/jobs 路由。
5. 当前以 canonical keyword search 替代尚未适配的 C 语义搜索。
6. 单一 Alembic head 已保持；C 合并时仍需重接迁移。

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

- D 的正式 16 文件语料已纳入集成分支并通过回归。
- 剩余只缺真实浏览器结果页调用搜索接口。

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

1. 用真实浏览器做一次人工走查并保存截图。
2. 核对搜索命中、页码和证据展开的视觉状态。

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

集成分支又补齐了：

- `services/scan/`：授权路径解析、递归扫描、哈希、版本复用和 current pointer；
- worker 的 `scan_root` 与 `extract_file` 分发；
- `/mounts` 和目录选择；
- canonical `/roots`、`/jobs`、`/files` 响应；
- 读取 B current chunk 的关键词 `/search`；
- D 现有文件证据视图的兼容路由。

真实 Docker fresh-volume 结果：16 文件、12 ready、4 个明确不可处理原因、
关键词 5/5、证据 5/5、重复扫描 0 新增、原件 SHA-256 0 变化。详见
`evidence/w7-m1-live.md`。

## 当前最重要的执行顺序

在 10.18 18:00 前，只做以下顺序，不新增 OCR、复杂图谱或部署优化：

1. **A 审核并吸收 `w7-integration-bootstrap` 的 scan/worker/routes 实现。**
2. **B 已在集成分支提供 files/evidence/relations/reviews；不再重复实现。**
3. **C 放弃第二套三表，按 B 的 chunk 改编 keyword 搜索。**
4. **D 把结果页输入框从本地过滤改为真实 `POST /search`。**
5. **D 用 16 文件语料跑首次、重复、异常混入三种场景。**
6. **全员记录 M1 结果；若失败，按排期裁掉语义和关系，不声称完整 W07。**

## 是否已经可以演示

**后端已经可以演示，浏览器完整链路还不能。** 当前能演示的是：

- 真实 Docker 下的选目录、扫描、后台解析、关键词搜索、证据读取后端链路；
- B 模块的命令行和测试证据；
- D 的授权、进度、文件列表和证据页面。

不能演示的是：

- 人工观看到的浏览器搜索→证据走查（代码和构建已完成）；
- 失败任务在页面可见并重试；
- 尚未适配 C 的语义检索。

因此现在不能把“模块测试通过”写成“W07 已达标”。
