# C 冻结查询本地评测

2026-10-15 候选实现评测；文件名沿用排期约定，不表示团队已经封板。基准为手写合成文档，5 关键词 + 5 语义查询，在首次真实 E5 评测前固定答案。

模型：`intfloat/multilingual-e5-small@614241f622f53c4eeff9890bdc4f31cfecc418b3`，384 维，query/passage 前缀，attention mean pooling，L2 归一化。混合权重为 keyword 0.65 / semantic 0.35，无独立 cross-encoder reranker。

逐项记录和真实响应见 [PostgreSQL JSON](evidence/C/search-eval-postgres.json)，SQLite 对照见 [本机 JSON](evidence/C/search-eval-local.json)。关键词使用 keyword 模式，语义使用 semantic 模式，均要求文件与页码同时正确；语义降级不会算成功。

<!-- QUERY_TABLE_START -->
| ID | 模式 | 冻结查询 | 预期文件 / 页 | 返回的预期文件及页码 | 结果 |
|---|---|---|---|---|---|
| kw-1 | keyword | reimbursement | fixture-expenses / 1 | fixture-expenses / 1–1 | 通过 |
| kw-2 | keyword | Password reset | fixture-access / 1 | fixture-access / 1–1 | 通过 |
| kw-3 | keyword | Database backup | fixture-backup / 2 | fixture-backup / 2–3 | 通过 |
| kw-4 | keyword | 个人信息保留期限 | fixture-retention / 2 | fixture-retention / 2–2 | 通过 |
| kw-5 | keyword | Attendance policy | fixture-attendance / 3 | fixture-attendance / 3–3 | 通过 |
| sem-1 | semantic | How can I get my money back for work journeys? | fixture-expenses / 1 | fixture-expenses / 1–1 | 通过 |
| sem-2 | semantic | I forgot my credentials and cannot sign in | fixture-access / 1 | fixture-access / 3–3 | 失败（页码错误） |
| sem-3 | semantic | 不小心清空存储，怎样找回丢失内容 | fixture-backup / 2 | fixture-backup / 2–3 | 通过 |
| sem-4 | semantic | When should a business dispose of information about former clients? | fixture-retention / 2 | fixture-retention / 2–2 | 通过 |
| sem-5 | semantic | 身体不适没去上课需要交什么材料 | fixture-attendance / 3 | fixture-attendance / 3–3 | 通过 |
<!-- QUERY_TABLE_END -->

关键词 Top-1 为 5/5，语义 Top-3 为 4/5，重复文件为 0，正常查询降级数为 0。账户问题 `sem-2` 找对文件但选到第 3 页，预期第 1 页，保持失败。

这些结果只反映 12 份合成文档和 15 个文本块的内部烟雾测试。真实 PDF、授权及 UI 证据链尚待 A/B/D 整合；不能据此声称泛化性能。
