# C 与远程 A/B 分支的合同差异

核对日期：2026-10-16。比较对象为 C 独立模块与远程 `w7-parsing`（`c248e8a9272f76beeec8f50a50bfd727f035aed9`）、`w7-scan-dispatch`（`7b084e573edd4e4c6985685ce8a3c7189aa3504c`）分支。对 A/B 分支只 fetch 和读取，没有切换或合并。C 的独立分支发布范围见 [分支审阅说明](../submissions/week07/C-branch-review.md)。

## 结论

C 的独立检索模块可以运行，但当前不能直接叠加 B 的数据库迁移，也不能直接读取 B 产出的表结构。按附件约定，公共模型与迁移的最终选择由 A 负责；C 的修改标为草案仍不等于 A 已确认。此项作为整合前 P1 问题保留，不能把独立模块测试通过写成团队链路已经贯通。

## 字段对照

| 语义 | C 本地合同草案 | B 分支现状 | 整合处理建议（待 A 确认） |
|---|---|---|---|
| 文件身份 | `SourceFile` / `source_files` | `FileRecord` / `files` | 保留正式文件 ID，迁移检索字段，勿建两套文件目录 |
| 授权目录 | 尚未连接 | `AuthorizedRoot` / `authorized_roots` | 搜索 join 有效 root 与 present 文件；有效挂载检查按 A 合同执行 |
| 当前版本 | `SourceVersion.is_current` | `FileRecord.current_version_id` | A 的 D1 已确定由 scan 事务设置，指向最新观察到的版本；检索须同时检查版本文本状态，不能回退展示旧版本 |
| 版本内容哈希 | `SourceVersion.sha256` | `FileVersion.content_sha256` | 绑定同一个不可变版本；最新磁盘状态由 A/B 校验 |
| 版本号 | 正整数 `version_number` | 只有稳定版本 ID，没有版本序号列 | 由 A/D 确定响应字段，不以临时猜测补版本号 |
| 可检索状态 | 文件、版本均为 `ready` | 文件 `presence_status=present`，版本 `basic_ready/enriched` | 统一状态筛选；向量失败后仍可搜索基本文本 |
| chunk 外键 | `source_version_id` | `version_id` | 改检索和索引处理器的列引用，保留原 chunk ID |
| chunk 顺序 | `chunk_index` 从 0 开始 | `ordinal` 从 1 开始 | 在适配边界转换，不修改 B 原始顺序 |
| 页码 | `page_start/page_end` 必填 | `page_number` 可空 | 单页块可映射为相同起止页；未知页码不能伪造为第 1 页 |
| 关键词字段 | `search_text/search_terms`、GIN | 尚无 | 由 A 的增量迁移加入，现有块需回填；B 写库路径需生成检索列 |
| 向量字段 | `vector(384)`、模型及维度 | 尚无 | 增量加入并回填；重新解析替换 chunk 后需调度向量重建 |
| Worker 合同 | `embed_version` 不提交事务 | B 的解析处理函数会提交阶段结果，Job 已有 `version_id` | 由 A 定任务类型、阶段提交与重试；勿把文件任务塞入 case 流程 |

B 的关系证据通过外键引用 `source_chunks.id`。整合时重新复制出一套 chunk ID 会使搜索结果与已有证据无法对应，应使用同一组正式记录。

## 迁移冲突

C 的迁移 `20261015_0002` 和 B 的迁移 `c2d1ac693a0e` 都从 `20260713_0001` 分出，而且都创建 `source_chunks`，但列定义不同。仅拼接文件会形成多个 Alembic head，执行两条分支还会遇到重复建表。

B 后续迁移链为 `c2d1ac693a0e → 318ab5be35e0 → 445f908b73b4`。建议 A 选定公共模型后，将 C 的关键词、向量和约束改为其后的增量迁移，而不是再创建 `source_chunks`。实际迁移内容、数据回填和部署顺序应在合同确定后实施；本次没有对 B 的分支或数据库做修改。

## A 的新决定与仍待联调的入口

远程 `w7-scan-dispatch` 已发布 `A-decisions.md` 和 `owner-map.md`。A 已明确：当前版本指针由 scan 事务设置；采用 B 的关系四表；挂载使用服务端 allowlist 与只读目录；仅对新增版本派发解析任务。此快照包含配置、Compose 和决定文档，尚未出现 `services/scan/`、正式文件 Worker 分发或新的公共模型/迁移实现；决定文档不能代替联调证据。

A 的 Compose 使用宿主 PostgreSQL 端口 `15432`，并为 API/worker 加入 `./corpus:/source/corpus:ro`。后续整合应保留这些配置，同时采用 C 所需的 pgvector 数据库镜像和模型只读挂载，不能直接以任一分支整份覆盖另一份 Compose。

`owner-map.md` 将公共模型、schema、配置、迁移、API 路由组装和部署文件归 A，D 负责最终合并。C 当前相关修改仍是独立演示所需的草案，供 A 移植字段和接口意图；推到 C 分支供审阅不表示这些共享文件已获团队确认。

正式互审应在 A 提供可审阅版本后验证：目录授权和撤销、当前版本发布、解析后触发向量任务、关键词回退、证据 ID 一致性、迁移升级以及服务重启。此清单不是已经完成的互审记录。
