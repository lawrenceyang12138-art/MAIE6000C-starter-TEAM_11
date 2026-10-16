# C → A/B/D 交接合同

状态：2026-10-16 更新交接状态；本地实现及完整测试证据仍为 2026-10-15，待整合，尚未团队确认或封板。

复查已读取远程 B 的 `w7-parsing`（`c248e8a`）及 A 的 `w7-scan-dispatch`（`7b084e5`）分支；已确认公共表字段和迁移冲突，详见 [逐字段合同差异](search-contract-differences.md)。A 已给出当前版本指针、挂载和任务派发决定；对应完整实现仍待联调。当前不能直接合并两套迁移后运行，也没有完成团队真实 PDF 端到端验收。

## 给 A：迁移、队列与授权

新迁移 `20261015_0002_source_search.py` 接在 starter 初始迁移后，提供三张 source 表、唯一当前版本约束、GIN 和 pgvector。分支上可独立运行；若 A 的分支已有正式文件/版本/chunk 表，统一以 A 的迁移为准，移植向量、模型元信息和检索字段，勿重复创建同名表。此处涉及公共模型/迁移的修改是可审阅的整合草案。

`embed_version(db, version_id, backend)` 是可被公共 Worker 分发器调用的 C 处理器，不会 `commit()`，返回 `version_id/chunk_count/embedded_count/embedding_error`。它不复用 starter 的 `triage_case` Job，避免把 case 外键当文件版本 ID；A 需要在正式文件任务合同中建立向量任务及其重试/尝试记录。当前可用独立 CLI 在后台执行：

```cmd
python -m scripts.search_tools index --database-url YOUR_DATABASE_URL --version-id VERSION_ID --backend http --ai-url http://127.0.0.1:8100
```

扫描未完成、解析完成、向量就绪是不同状态。A 的 D1 已确定 `files.current_version_id` 由 scan 事务设置，指向最新观察到的版本；C 后续须按该指针和文本状态筛选，不能在新版本尚未解析时展示历史块为当前结果。文本写入后即支持关键词搜索；向量失败不应把已解析的基本文本删除。当前 C 的文件筛选已有 ready/current/hash 检查，正式授权还需要 A/C 在 `_base_statement()` 连接有效 root/mount 范围。`file_id` 过滤器不代表授权控制，搜索也不返回可绕过授权的磁盘读取接口。

## 给 B：文本与页码

以下是 C 当前样例适配器的输入合同：版本 ID、从 0 开始的唯一 `chunk_index`、完整 `text`、从 1 开始的 `page_start/page_end`，且结束页不小于开始页。B 的正式块使用 `version_id/ordinal/page_number`，应由 C 适配正式公共模型，保留 B 的 chunk ID，不要求 B 改成 C 的草案字段。建议每块不超过 2000 字符，避免 embedding 只读前缀。跨页块应保留真实页码范围；未知页码不能伪造，C 不生成或推断页码。

通过 ORM 插入/更新会自动生成 `search_text/search_terms`；若使用 bulk SQL/COPY，则调用 `normalize_text(text)` 和 `search_terms(text)` 填列。文本不可为了语义调参改写原文。旧版本与当前文件哈希不一致的数据不参与搜索。

`index_document()` 是 C 的样例导入适配器，接收手写 chunk，不执行扫描或 PDF 解析。相同版本、同一内容的重复导入返回原记录；同一版本内容不同会报错，必须使用新版本号。插入较旧版本不会覆盖当前版本。B 正式解析链路整合后可以直接使用公共模型写库，不必调用该适配器。

## 给 D：公开搜索接口

```http
POST /search
Content-Type: application/json
```

```json
{"query":"数据库备份", "mode":"hybrid", "top_k":10, "file_id":null}
```

`mode` 可为 `keyword/semantic/hybrid`，默认 hybrid。响应中 `mode` 保留请求模式，`effective_mode` 表示实际使用模式。`degraded` 为真时，在 UI 显示 `degradation_reason` 对应的友好提示，比如“语义服务暂不可用，已返回关键词结果”。空结果仍是 HTTP 200、`results=[]`；空白/过长查询或越界 `top_k` 是 422。

每个 `results[]` 的稳定字段：

| 字段 | 含义 |
|---|---|
| `file_id/file_name/file_path` | 文件身份、显示名、路径，仅作展示 |
| `version_id/version_number` | 证据对应的不可变版本 |
| `chunk_id/chunk_index` | 结果块身份与原始顺序 |
| `page_start/page_end` | 1-based 源页码范围 |
| `text` | 最多 2000 字符原文节选 |
| `score/keyword_score/semantic_score` | 0–1 分数，不是概率 |
| `reason` | 匹配词/文件名/语义余弦解释 |

证据展开须把版本与块 ID 交给 B 的授权证据 API。当前 C 没有伪造该 API，也不提供 `file://` 链接。`total` 为候选池内去重文件数；当前无分页，最多展示 `top_k` 份。

2026-10-16 推送前再次读取 `origin/Role_D`（`eb656ca`）：前端已默认使用真实 API，mock 改为显式选择；真实 adapter 尚无 `POST /search`，结果框仍在浏览器过滤已载入的记录。D 的交接说明将搜索接入排在 10 月 17 日。C 当前只有 `file_id` 过滤，正式接入前需 A/C/D 共同确定授权 root 参数与服务端校验，不能将现有独立端点当作授权链路已完成。

## 可交接材料

模型配置在 `submissions/week07/search-config-final.json`，其 freeze 状态明确为候选。逐项评测/停 AI/断网证据在 `submissions/week07/evidence/C/`。`sections/C.md`、`C-slides.md`、`C-notes.md`、`C-qa.md` 是供本人复核及 D 拼装的文字草稿，不代表团队报告/PPT 已最终提交。

本模块通过 `feat/c-search-model-evaluation` 独立分支供团队审阅和备份。用户于 2026-10-16 授权提交并推送该分支；发布范围见 [分支审阅说明](../submissions/week07/C-branch-review.md)。团队计划 10 月 21 日统一封板和合并，此次发布不合并 `main`，也不代表公共合同已经确认。
