# C 本地实现验收记录

日期：2026-10-15。状态：候选实现，本地未提交，未替团队进行 10 月 21 日封板或签认。

本文件保留 10 月 15 日验收时的 Git 状态和测试证据。10 月 16 日用户已授权发布 C 独立分支，后续发布及整合状态见 [分支审阅说明](C-branch-review.md)；下文的“未提交”和初始 HEAD 描述只适用于验收快照。

## 分支与实现

- 仓库位于 `C:\Users\LEGION\Desktop\MAIE6000C-starter-TEAM_11`。
- 分支为 `feat/c-search-model-evaluation`，HEAD 为初始提交 `abacacd0ea64c8393a1114f8acafa54dfb7c60a1`。
- 没有暂存、commit、push 或合并；实现和材料均留在工作区。
- 已实现 PostgreSQL 中英文关键词检索、`POST /search`、按文件去重、版本和页码结果、本地 E5、pgvector 语义查询、混合排序及关键词降级。
- 向量处理函数在所有批次成功后才发布向量，失败保留原文；公共 Worker 的文件任务分发仍由 A 整合。
- 同分证据按原始分块顺序选取，不用随机块 ID 决定页码。

## 实际验证结果

| 检查 | 结果 | 证据 |
|---|---|---|
| 本机完整测试（单元、集成、真实 smoke） | 49 passed，0 failed，0 skipped | [pytest-results.xml](evidence/C/pytest-results.xml) |
| Docker Python 3.11.17 完整测试 | 49 passed，0 failed，0 skipped | [pytest-docker-python311.xml](evidence/C/pytest-docker-python311.xml) |
| Ruff | All checks passed | [validation-summary.json](evidence/C/validation-summary.json) |
| PostgreSQL/pgvector | 实际执行全文及向量查询，GIN 索引存在 | [PostgreSQL 逐项结果](evidence/C/search-eval-postgres.json) |
| 迁移一致性 | 当前 revision 为 `20261015_0002`，无新增迁移差异 | [validation-summary.json](evidence/C/validation-summary.json) |
| Docker 构建及 Compose 配置 | 镜像构建成功；Compose 配置验证通过 | [validation-summary.json](evidence/C/validation-summary.json) |
| 外网连接阻断时的真实模型推理 | 关键词 5/5，语义 4/5，10 条 hybrid 返回 200 | [offline-docker-python311.json](evidence/C/offline-docker-python311.json) |
| 实际结束 AI 进程 | 5 条关键词仍命中正确文件和页码，有明确降级字段 | [http-docker-python311.json](evidence/C/http-docker-python311.json) |
| 原有 starter case → worker → AI | 通过 | [http-docker-python311.json](evidence/C/http-docker-python311.json) |
| 向量批处理失败隔离 | 第二批失败后未发布部分向量，文本保留 | `tests/integration/test_search_api.py::test_failed_second_embedding_batch_keeps_text_and_existing_vectors` |

本机与容器分别出现两条依赖弃用提示，没有测试失败。容器使用 Python 3.11 与项目固定依赖；最终源文件和测试通过只读挂载完成验证。模型由只读挂载提供，不打入 Git 或镜像。机器环境和实际版本见 JSON 验收摘要。

本轮复查修复了部分向量状态漏报及误计语义成功、损坏模型清单未正常降级，并修正原 starter 测试误后缀，恢复两项测试的收集。已有向量在重建失败后仍保留的场景已补验。逐项要求和未完成条件见 [要求复查](C-requirements-review.md)。

## 冻结查询的实际成绩

语料是 12 份手写合成文档、15 个带页码文本块。答案在首次 E5 评测前冻结，语料和答案 SHA-256 随评测记录保存；当前没有团队真实 PDF 的验收结论。

- 关键词 Top-1：5/5。
- 语义 Top-3：4/5，达到该内部基准的 4/5 目标。
- 重复文件：0；正常评测降级查询：0。
- `sem-2` 命中 `fixture-access`，但返回第 3 页，预期第 1 页；保持失败，未改答案。

完整逐项表见 [search-eval-final.md](search-eval-final.md)。该结果是内部烟雾测试，不代表泛化性能、真实 PDF 页码链路或团队端到端演示已经验收。

## 可复核交付物

| 内容 | 文件 |
|---|---|
| 算法、模型、接口、命令与边界 | [search-plan.md](../../docs/search-plan.md) |
| 给 A/B/D 的整合合同 | [search-integration-handoff.md](../../docs/search-integration-handoff.md) |
| 5 条关键词返回样例 | [keyword-results.json](evidence/C/keyword-results.json) |
| 10 个数据库实际向量样例 | [vector-samples.json](evidence/C/vector-samples.json) |
| 15 条向量检索记录 | [vector-retrieval-records.json](evidence/C/vector-retrieval-records.json) |
| 模型文件 SHA-256 | [model-manifest.json](evidence/C/model-manifest.json) |
| 参数候选 | [search-config-final.json](search-config-final.json) |
| C 章节、三页内容、讲稿、问答 | [章节](sections/C.md)、[第 7–9 页文字](C-slides.md)、[讲稿](C-notes.md)、[两问](C-qa.md) |
| AI 使用说明草稿 | [AI-Use-C.md](AI-Use-C.md) |

第 7–9 页目前是可拼装的文字内容，尚未生成正式 PPT；讲稿需本人计时复核。材料没有替任何组员签署声明。

## 后续团队整合

A 需核对公共模型和迁移、有效目录授权过滤、文件向量任务及重试状态。B 需接真实解析结果并核对不可变版本、原文和页码；D 需接 UI、证据展开和降级提示。公共表与迁移是 C 的可运行合同草案，合并前按 A 的最终合同整合。

已只读核对远程 `w7-parsing`，发现与 C 草案的字段和迁移冲突；详见 [合同差异](../../docs/search-contract-differences.md)。当前不能直接叠加两套迁移。本项为合并前 P1，不能将本检查表当作团队联调或公共合同已经确认的记录。

本实现没有独立 cross-encoder reranker，没有扫描器、PDF 解析器或正式授权证据 API。第二电脑部署、真实 PDF 端到端验收与 10 月 21 日团队封板仍按团队排期进行。

独立测试数据库容器 `team11-c-search-verify-1015` 保留运行，端口仅绑定 `127.0.0.1:55432`，便于继续核对。临时 API/AI/worker 已自动结束；未关闭用户的 Docker。
