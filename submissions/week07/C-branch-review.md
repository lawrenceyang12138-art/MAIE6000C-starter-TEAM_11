# C 独立分支审阅说明

日期：2026-10-16。分支：`feat/c-search-model-evaluation`。提交作者：`LI Yucheng`。

用户已授权提交并推送此 C 分支，供团队审阅和备份；团队计划 10 月 21 日统一封板、合并。本次发布不合并 `main`，当前公共合同和真实 PDF 链路仍待整合。

## 发布内容

- 中英文关键词检索、固定 revision 的本地多语言 E5、pgvector 语义检索、混合排序、按文件去重以及文件/版本/页码结果。
- `POST /search` 和内部 `POST /embeddings`；AI 关闭、超时、不可用和向量状态异常时明确报告降级。
- 分批向量处理器和本地 CLI；批次失败保留原文与旧向量，不在处理器内提交事务。
- 12 份合成文档、15 个块、10 条冻结查询、回归测试、完整验证证据和 A/B/D 交接材料。
- 模型权重、`.env`、本地数据库与临时工作目录均由 Git 忽略，不随代码分支发布。

## 验证日期和范围

| 项目 | 结果 | 验证日期与范围 |
|---|---|---|
| 本机单元与集成测试 | 46 passed，2 deselected | 2026-10-16；排除 PostgreSQL marker，不含 HTTP smoke |
| Ruff / Git diff 检查 | 通过 | 2026-10-16 |
| 源码与测试 SHA-256 | 41 个文件全部一致 | 推送前与 10 月 15 日完整验证摘要核对；此轮仅更新发布和交接文档 |
| 本机完整套件 | 49 passed，0 skipped | 2026-10-15；包含真实 HTTP smoke 和 PostgreSQL |
| Docker Python 3.11 完整套件 | 49 passed，0 skipped | 2026-10-15；10 月 16 日 Docker 引擎不可连接，未重新执行 |
| 冻结关键词 Top-1 / 语义 Top-3 | 5/5 / 4/5，重复文件 0 | 2026-10-15；合成文本基准，不能当作真实 PDF 全链路验收 |

`sem-2` 文件正确但返回页 3，预期页 1，继续保留失败。模型文件和固定答案未因发布而变更。

[完整验证摘要](evidence/C/validation-summary.json)、[要求复查](C-requirements-review.md)、[本地验收记录](C-final-check.md) 保留原验证时间和当时的 Git 状态，包括未提交工作区和初始 HEAD；这些字段是历史证据，不表示本分支发布后的状态。

## 合并前仍需处理

1. B 的 `files/file_versions/source_chunks(version_id, ordinal, page_number)` 与 C 草案不兼容，两条迁移都创建 `source_chunks`。A 需统一公共模型和迁移，C 配合改为正式表上的增量字段并保留 B 的 chunk ID。详见 [合同差异](../../docs/search-contract-differences.md)。
2. A 的 `w7-scan-dispatch`（`7b084e5`）已给出当前版本指针、挂载和任务派发决定；对应扫描和文件任务链路仍待接入。公共文件归 A 统一落地，C 当前模型、迁移、API 组装和部署修改是供 A 审阅的独立运行草案。
3. D 的 `Role_D`（`eb656ca`）已改为默认真实 API，mock 需显式选择；adapter 尚无 `POST /search`，搜索接入排在 10 月 17 日。C 需与 A/D 确定授权 root 范围和响应适配。
4. 真实 PDF、授权撤销、当前版本和证据一致性仍需团队联调。C 的正式三页 PPT、对 A 的互审、讲稿计时和备机验证仍待完成。
5. 当前 GitHub Actions 监听 `main` 的 push 和 pull request，单独 push C 分支不会触发 workflow。本次仅发布独立分支，没有创建 PR 或执行合并。

远程核对快照：A `7b084e573edd4e4c6985685ce8a3c7189aa3504c`；B `c248e8a9272f76beeec8f50a50bfd727f035aed9`；D `eb656ca3f32001f95937a2c90195611631657126`。团队分支均只读核对，未合入 C。
