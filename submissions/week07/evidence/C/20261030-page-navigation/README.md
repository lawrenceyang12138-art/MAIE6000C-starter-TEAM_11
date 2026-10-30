# C：PPLX 页码导航修复与真实 PDF 复测（2026-10-30）

本轮在 PostgreSQL 和 SQLite 上分别重跑真实 PDF 扫描、解析、索引与本地 PPLX 检索：纯模型保持关键词 Top-1 **5/5**、语义 Top-3 **3/5**、混合 Top-3 **3/5**；启用通用物理页导航后，关键词 **5/5**、语义和混合均为 **5/5**。四份报告均完整执行 15 次检索，无降级、重复文件、来源解析错误或原文证据错误。独立导航回归在两种数据库均通过 **24/24 明确导航、12/12 歧义或不可用场景**。

导航增强已达到本轮 C **至少 4/5 候选门槛**，但纯模型仍未达到该门槛。增强成绩归属于带结构化页导航的系统定位能力，不能改写为模型主题语义能力提升。**4/5 尚非团队冻结验收线，B 人工 gold 审核仍为 `pending`，本报告不宣布团队验收通过。** 当前冻结 gold 自身限定为模板语料的来源定位 smoke test，并非语义质量 benchmark。

本轮最终全量测试为 **530 passed、2 skipped、0 failed、0 errors**，Ruff 通过。真实本地 HTTP 断开、超时、现有补索引及恢复验证也已完成并通过：从 0 恢复到 20 个兼容 chunk token 矩阵、416 个 token 向量，12 个页元数据版本就绪；在线 15 次检索全部命中，降级保持明确，恢复后 S02 返回正确末页。

## 分支、代码与冻结输入

| 项目 | 本轮记录 |
| --- | --- |
| 分支 | `codex/c-team-pdf-evaluation` |
| C 隔离工作区 | `D:\HKUST AIE\MAIE6000C\MAIE6000C-starter-TEAM_11\tmp\c-team-pdf-evaluation` |
| C 集成基线 / 本地 `develop` | `7522287126061da8977c253256e8f807143ab8b5` |
| 本地可用 `origin/develop` 快照 | `047b2ac8b6c584b366c3db8f211125a6b9febe4f`，已包含于上述基线 |
| 本轮实测产品代码 | `e364f5b1954847e9f78a1b10e32bf47dcb2ba2be` |
| 最终操作命令保护 / 测试代码 | `7ad3ff03c2745ca0c1ffb5e33185b419380b56be`；仅补录报告路径保护及对应 3 条测试 |
| 导航用例首次冻结 | `77a9af1213d5a7bb0f784da0b3a32b496acea088`；随后以 `f180beb82d1d5d0c8108029a9f861a2ad2461433` 固定身份及检出字节 |
| 历史 PPLX 产品代码 | `40879c44f2777db7dafd559cc97f5edc8b3f6714`，旧证据独立保留 |
| 团队 gold | `team11-gold-v1`，`submissions/week07/gold-queries.json` |
| 语料 manifest | `d-fixtures-v1`，`fixtures/manifest.json`，冻结根别名 `root-demo-01` |
| 团队答案 freeze | `team11-gold-freeze-v1`，冻结日期 `2026-10-16` |
| gold SHA-256 | `d1d7b7daf285ed8ad596546dc1cacb28bca7b23cd26edc748e7636e1a23db053` |
| manifest SHA-256 | `3ad53b3f8ccdc7ac6b84457fcedf9a735fe0ddf7ceb8004eb97b46ab17e3280f` |
| freeze SHA-256 | `2a1ca7744c3176cb9e4df69adaf2f13d087f3fe88d73cb71604a82a3fe88114d` |
| 独立导航 fixture SHA-256 | `cc49c7bdcf74337a32350dfbc9548ae63c39c118cdf7968f85869a1610f99bab` |

四份真实模型评估 JSON 均记录上述产品 SHA，执行时 tracked diff 为空；原始 JSON 还记录相关源码哈希、Git 状态、实际 argv、模型 manifest 和依赖版本。证据文件在产品提交之后生成，不应把证据提交的 SHA 替代实测产品 SHA。`.gitattributes` 保留本目录原始证据字节。已有 E5/PPLX 报告、手工 chunk 基准与冻结答案未覆盖；原工作区及其他角色分支保留，本轮未推送、未合入 `develop`。

真实模型与 HTTP 复测之后，最终审查为 `page-metadata` 增加固定团队 gold/freeze 和 SQLite 数据库的输出路径保护，拒绝在数据库或 PDF 操作前将报告写到这些输入上。该提交只改 `scripts/search_tools.py` 和其 CLI 测试，没有改变检索、页意图、元数据解析、模型、索引或评估代码。最终 530 项通过的全量测试和整根 12/12 补录复测使用 `7ad3ff0`；此前 527 项通过的原始报告也保留。

[完整性汇总](verification-summary.json) 还区分了历史检出换行与内容变化：旧 E5 证据中 14 个文件原 Git 为 LF、既有 Windows checkout 为 CRLF，其 Git blob 和换行规范化后内容均未变，不能宣称这些 checkout 字节等于原 Git 字节。旧 PPLX 证据、团队 gold/manifest/freeze 和导航冻结输入则均逐字节未改。历史手工 chunk 的关键词 **5/5**、语义 **4/5** 继续只作历史结果，不与本轮真实 PDF 分数混合。

## 来源适配与真实身份映射

评估器复用已实现的团队 `expected[]` 和 `semantic_description` 适配。`file-xxx`、`version-xxx-v1` 属于冻结别名，不能直接当数据库 UUID。映射依次核对 manifest 中的别名、完整相对路径、内容 SHA-256，再限定实际授权根，解析为扫描所得文件和当前版本；记录方法为 `root_relative_path_sha256`。同名异路径、不同根、不同内容和历史版本不会仅因 basename 相同而匹配。

本轮 PostgreSQL 授权根为 `dc70538c-f5de-489a-85f7-e363d8cbaacc`，SQLite 为 `352099e0-c59b-4e6e-acb0-d14c3c88449a`。两者都使用受限 mount `c-eval-3becb1d821f8` 指向 `work/team-pdf-corpus`；数据库 UUID 分别保存，跨数据库不强行要求相同 ID。以下是 PostgreSQL 的预期来源映射，完整 SHA、就绪状态及 SQLite 映射见四份报告的 `source_resolutions`。

| query | 冻结文件 / 版本别名 | 扫描 file_id | 当前 version_id |
| --- | --- | --- | --- |
| K01 | `file-001 / version-001-v1` | `0d1e681b-a0b5-43e4-870f-7ba0ab569800` | `0f28272f-3930-42ea-9039-9ba9c71d5cba` |
| K02 | `file-002 / version-002-v1` | `27c7e025-a2a7-4df2-a01a-6cfff3f8c970` | `84ea61a6-c79a-4285-a004-28f6d17ddae4` |
| K03 | `file-003 / version-003-v1` | `965bea2d-6a45-4dde-a0eb-32acb1ff25c6` | `1a63e5ae-0d1f-4978-a4d7-7741d367d856` |
| K04 | `file-007 / version-007-v1` | `dfa81d4a-f523-4a14-bf2e-08ca6e6eee43` | `6429b113-73a2-403b-a1b2-f41322918e8e` |
| K05 | `file-008 / version-008-v1` | `9f8520c4-3f9f-4e24-b7a9-e3725dbaf9ae` | `67508b74-156f-4cb0-ad44-fb26816fcf62` |
| S01 | `file-009 / version-009-v1` | `e7e2eb76-f945-4036-a6fe-6cb9c856762e` | `c227fb7c-a048-41fd-a6e2-8484c4805ffe` |
| S02 | `file-010 / version-010-v1` | `3bcfa293-8c5e-415c-8c9d-354c528293f7` | `7667c3cb-b722-446c-b2b8-1963a618a8d7` |
| S03 | `file-011 / version-011-v1` | `f9ad80e5-86bb-4008-8c02-f2ef3b7ab534` | `1094ea09-aa00-4da0-9b48-36aa8b3f4195` |
| S04 | `file-012 / version-012-v1` | `3890a16e-373b-45f1-9071-46261c122f78` | `601121dd-ddbf-4dca-9348-3bb6fcf59d8c` |
| S05 | `file-006 / version-006-v1` | `46639550-7c41-445d-9648-3c98ab37ae83` | `06b962f4-e419-451b-8c93-d4941a154015` |

例如 S02 的完整路径为 `normal/team-beta/team11-demo-10.pdf`，内容 SHA-256 为 `44ca584ae43590e6c1a4ded0b3f8099a4d9261ccb0d9d92beede8a6dc39a872c`。搜索运行时不使用这张映射表，不读取 query ID、预期答案或 fixture manifest 来确定文件或页码。

评估保留 `corpus_mismatch`、`expected_page_missing`、`version_mismatch`、`index_not_ready`、`root_scope_required`、`root_not_authorized`、`file_missing` 等诊断。关键词 sidecar 与当前 PPLX token 矩阵分别检查；内容指纹、revision 或维度不兼容不能算向量就绪。每条返回结果都回读对应版本、页码、chunk 和原文，完整 PDF runner 进一步解析授权源路径并核验文件 SHA。

## 页码导航实现与失败行为

新增 C 派生表 `version_page_search_metadata`，以 `version_id` 外键连接权威版本，保存内容 SHA、字节数、parser revision、真实物理页数、`pdf-physical-pages-v1` 策略版本和时间戳。索引及显式补录复用授权路径解析，读取 PDF 结构获得物理页数，解析前后核对源文件身份；空白页也计入。页数不来自 gold、chunk 数或最大 chunk 页码。搜索只读数据库，不临时打开 PDF，不隐式建表。

`page_navigation.py` 保守识别中英文明确页导航：指定页、首页、末页、中间页和单页文档，支持阿拉伯/全角/中文页数。必须有“页 / page / leaf”语境，文档序号不绑定文件名；否定、冲突、范围及“中间件、最后更新、第三章”保持普通检索。奇数页取中心页，偶数页允许两个中心页，再按原有分数择优。完整 query 仍输入模型。

约束在每文件选最佳 chunk 和截断候选之前应用，返回页、chunk、原文和分数来自同一个候选，不增加人工分数。已知目标越界、目标为空白页、只有未知页码 chunk 或单页意图不适用时，不以其他页冒充；该文件不返回结果。元数据缺失或不兼容时保留普通排序，并在既有 `reason` 中写明 `page_metadata_missing`、`page_metadata_stale` 或 `page_metadata_schema_missing`。内部诊断另外记录目标页、是否应用、候选/目标 chunk 数及选中证据；公共请求/响应字段不变。

搜索仍先过滤当前版本、授权范围和文件存在状态，再进行导航；撤销授权及旧版本不因导航重新出现。相同文件名的不同路径保持独立身份，最终每文件最多一条结果。关键词模式不启用导航；AI 完整降级时也保持原关键词行为。`partial_embeddings` 仍为降级，导航不能清除 `degraded`，降级结果不计为语义命中。

显式 `prepare-token-index` 现同时准备 C token 表与页元数据表；`page-metadata` 强制 `--root-id`，可再指定该根内的当前 `--version-id`。现有 `index` 自动尝试页数准备，并以 `page_count/page_metadata_error` 单独报告；元数据失败不阻断关键词、向量或原文证据。共享迁移、API 主装配和 Worker 未在本轮改动，由 A 整合。详细操作见 [页导航指南](../../../../../docs/search-page-navigation.md)。

## 精确分母与实测成绩

| 配置 | 关键词 Top-1 | 语义 Top-3 | 混合 Top-3 | C 候选门 | 原始报告 |
| --- | --- | --- | --- | --- | --- |
| PostgreSQL，`pplx_only` | 5/5 | 3/5 | 3/5 | 未达到 | [postgres-model-only.json](postgres-model-only.json) |
| SQLite，`pplx_only` | 5/5 | 3/5 | 3/5 | 未达到 | [sqlite-model-only.json](sqlite-model-only.json) |
| PostgreSQL，`pplx_page_navigation_v1` | 5/5 | 5/5 | 5/5 | 增强定位达到 | [postgres-navigation.json](postgres-navigation.json) |
| SQLite，`pplx_page_navigation_v1` | 5/5 | 5/5 | 5/5 | 增强定位达到 | [sqlite-navigation.json](sqlite-navigation.json) |

每份报告是 **10 条唯一 query、15 次实际检索**：K01–K05 各一次关键词检索，S01–S05 各一次 semantic 和一次 hybrid；分母严格为 **5 / 5 / 5**。四份共执行 60 次，但重复数据库与配置不合并成新的 20 题质量分母。关键词同时要求文件与页码 Top-1 正确；semantic/hybrid 要求文件和页码同时在 Top-3 内正确。所有模式均保存完整 Top-3。

每份语料为 **16 文件：12 正常 PDF、3 异常 PDF、1 不支持 DOCX**；12 正常 PDF 合计 **20 物理页、20 canonical chunk、20 兼容 token 矩阵、416 个 128 维 token 向量**。12 个当前可读 PDF 版本均有可信页数。四份报告的 `duplicate_files=0`、`degraded_queries=0`、`source_diagnostics=0`、`evidence_failures=0`、`on_disk_evidence_failures=0`，扫描/解析/检索前后源字节保持不变。这里“重复数 0”指返回结果没有重复文件，不表示要删除同内容的不同源文件。

### 逐题期望与实际证据

下表使用 PostgreSQL 的真实 chunk UUID；SQLite 的逐条 UUID 及完整版本/原文另存其原始 JSON。`Dnn` 仅为报告排版缩写：D01–D06 对应 `normal/team-alpha/team11-demo-nn.pdf`，D07–D12 对应 `normal/team-beta/team11-demo-nn.pdf`。它不参与运行时检索。所有下表执行 `degraded=false`，requested/effective mode 一致；S 行分别执行 semantic 和 hybrid，两个模式的文件/页码/命中结论一致。

| ID | 完整 query | 期望文件/页 | 纯模型实际 | 增强实际 | 增强 chunk_id |
| --- | --- | --- | --- | --- | --- |
| K01 | `Team 11 synthetic document 01` | D01 / p1 | #1 D01/p1，命中 | #1 D01/p1，命中 | `e9674d9b-4135-4ad3-9290-18debe35c94e` |
| K02 | `查找包含 Team 11 synthetic document 02 的文件` | D02 / p1 | #1 D02/p1，命中 | #1 D02/p1，命中 | `b65194b5-0960-4e78-bacb-ebe64b5bec71` |
| K03 | `Team 11 synthetic document 03` | D03 / p1 | #1 D03/p1，命中 | #1 D03/p1，命中 | `ea12b854-84e6-4886-ba02-7378e3d8236a` |
| K04 | `Team 11 synthetic document 07` | D07 / p1 | #1 D07/p1，命中 | #1 D07/p1，命中 | `972d20ee-b599-4d28-aa56-2d8fa094ea77` |
| K05 | `查找包含 Team 11 synthetic document 08 的文件` | D08 / p1 | #1 D08/p1，命中 | #1 D08/p1，命中 | `b8f43080-a761-45a6-b6b9-45540d30260f` |
| S01 | `Show the middle leaf in the ninth sample.` | D09 / p2 | #1 D09/p2，命中 | #1 D09/p2，命中 | `33aa97fa-73fc-4c39-a88e-8feedd1ccbd5` |
| S02 | `打开第十份资料的最后一页` | D10 / p3 | #1 D10/p1，未命中 | #1 D10/p3，命中 | `6979ace9-d472-42a3-ba48-69049111f6d0` |
| S03 | `Locate the opening leaf in the eleventh sample.` | D11 / p1 | #1 D11/p1，命中 | #1 D11/p1，命中 | `8aeb0fbd-5631-4731-b77d-35ee0f10d382` |
| S04 | `查看第十二份资料正中间的那一页` | D12 / p2 | #1 D12/p1，未命中 | #1 D12/p2，命中 | `48347d49-050c-430c-a220-6412ce4d1a59` |
| S05 | `找出第六份只有一页的资料` | D06 / p1 | #1 D06/p1，命中 | #1 D06/p1，命中 | `f6b6fb53-ceaa-48db-942c-f0bae3a60ac8` |

以下列出 semantic/hybrid 完整 Top-3 的文件、页和公共分数；每个排名项的 chunk、版本、原文、分通道分数和证据读取结果仍以相应 JSON 的 `queries[].ranked_results[]` 为准。分数是接口保留六位后的数值，排序内部保持完整精度。

| ID / 模式 | 纯模型 Top-3（按排名） | 导航增强 Top-3（按排名） |
| --- | --- | --- |
| S01 semantic | D09/p2 `0.776348`；D10/p2 `0.767969`；D12/p2 `0.767813` | D09/p2 `0.776348`；D10/p2 `0.767969`；D12/p2 `0.767813` |
| S01 hybrid | D09/p2 `0.271722`；D10/p2 `0.268789`；D12/p2 `0.268735` | D09/p2 `0.271722`；D10/p2 `0.268789`；D12/p2 `0.268735` |
| S02 semantic | D10/p1 `0.712317`；D11/p3 `0.704184`；D12/p3 `0.703161` | D10/p3 `0.711955`；D11/p3 `0.704184`；D12/p3 `0.703161` |
| S02 hybrid | D10/p1 `0.249311`；D11/p3 `0.246465`；D12/p3 `0.246106` | D10/p3 `0.249184`；D11/p3 `0.246465`；D12/p3 `0.246106` |
| S03 semantic | D11/p1 `0.811745`；D10/p1 `0.811266`；D12/p1 `0.810963` | D11/p1 `0.811745`；D10/p1 `0.811266`；D12/p1 `0.810963` |
| S03 hybrid | D11/p1 `0.284111`；D10/p1 `0.283943`；D12/p1 `0.283837` | D11/p1 `0.284111`；D10/p1 `0.283943`；D12/p1 `0.283837` |
| S04 semantic | D12/p1 `0.769519`；D10/p1 `0.761303`；D11/p1 `0.760847` | D12/p2 `0.769315`；D10/p2 `0.761079`；D11/p2 `0.760635` |
| S04 hybrid | D12/p1 `0.269332`；D10/p1 `0.266456`；D11/p1 `0.266296` | D12/p2 `0.269260`；D10/p2 `0.266378`；D11/p2 `0.266222` |
| S05 semantic | D06/p1 `0.744691`；D12/p1 `0.740329`；D10/p1 `0.739433` | D06/p1 `0.744691`；D05/p1 `0.735825`；D03/p1 `0.734715` |
| S05 hybrid | D06/p1 `0.260642`；D12/p1 `0.259115`；D10/p1 `0.258801` | D06/p1 `0.260642`；D05/p1 `0.257539`；D03/p1 `0.257150` |

### 为什么纯模型仍为 3/5

失败集中在同一正确文件内的页选择，不是文件召回、解析编号、版本指针或证据丢失。S02 的 p1 比期望 p3 高约 `0.0003624558`；S04 的 p1 比期望 p2 高约 `0.0002039671`。系统每文件保留一个证据 chunk，较高的 p1 因此使期望页无法出现在该文件的 Top-3 返回项中。S02 错页 chunk 为 `614ee017-d804-4fb5-b6eb-2e6a7bf0f4ac`，S04 为 `e8f2f1c5-f559-4e0d-a1d9-6053445c3646`。

历史只读研究已经核对 batch、已存向量和官方 MaxSim；原生平均 MaxSim 最大差异约 `1.07e-7`，远小于上述分差。参见保留的 [PPLX 原始失败分析](../20261030-pplx/failure-analysis.json) 和 [原生模型核验](../20261030-pplx/native-model.json)。本轮关闭导航的两份报告再次保留同样失败。S01–S05 关键词贡献均为 0，调整混合权重只会缩放排序；扩大文件 Top-k 也不会改变每文件的最佳页。模板页的文本高度相似，late-interaction 相似度并不保证服从“最后/中间”这种相对物理页指令。

修复据 query 的通用页意图和经验证物理页数限制候选后，再沿用模型分数选择文件证据。它不提高期望页的模型分数，不修改答案；S02 增强选择的分数反而略低于其原错页。这解释了为什么系统定位可达 5/5，而纯模型基线仍应报告为 3/5。

## 独立 24+12 导航回归

冻结集不是团队 gold 的复制。它有 36 个唯一 case、11 个新 PDF，覆盖中英文、未见文件名、1/2/3/4/7/10 页、偶数双中心页、空白尾页及中页、同页多 chunk、越界、未知页码、缺失/过期元数据、否定/冲突/范围和无导航语境。fixture 在实现前冻结，答案未按结果修改。

| 数据库 | 明确导航 | 歧义/不可用 | 增强执行 | 无导航对照 | 证据/行为/诊断失败 |
| --- | --- | --- | --- | --- | --- |
| PostgreSQL | 24/24 | 12/12 | 72/72 | 72 次 | 0 / 0 / 0 |
| SQLite | 24/24 | 12/12 | 72/72 | 72 次 | 0 / 0 / 0 |

每个 case 分别执行 semantic/hybrid，因此每数据库有 72 次增强和 72 次对照；双数据库共 288 次，不扩大 36 个唯一 case 的分母。两套 PDF 都经真实扫描、解析、索引，合计各 **43 物理页、45 chunk**；读取证据及源字节校验通过。缺失/过期元数据与未知页码为正常入库后显式注入的 3 类测试故障。

本集使用特意偏向前页的确定性手工 token 向量，报告明确 `model_inference=false`、`hand_constructed_token_vectors_not_PPLX_inference`，验证的是导航行为，不是模型质量。真实 PPLX 质量仅来自前述四份模型报告。原始全量 case、双模式、对照排名及诊断见 [PostgreSQL](navigation-regression-postgres.json) 和 [SQLite](navigation-regression-sqlite.json)。PG 使用真实 Alembic `upgrade head` 后显式准备 C 表；SQLite 使用 ORM 测试 schema，不宣称验证了共享 PostgreSQL 迁移的 SQLite 兼容性。

## 本地模型与参数冻结

本轮保留现有模型、revision、完整 query、前缀、分块、向量和权重。启用导航不要求重建兼容 PPLX 向量，只需补录新页元数据；缺向量恢复继续复用现有 `index` 命令。

| 配置 | 固定值 |
| --- | --- |
| 模型 / revision | `perplexity-ai/pplx-embed-v2-late-0.6b` / `7bba8e7cf2075dec747fa8557f41eb90e70361ed` |
| 本地目录 | `models/pplx-embed-v2-late-0.6b` |
| 模型 manifest SHA-256 | `dae099e3f314bb7969ea9aacabaa44b81938416d3fe77fc12f65cd6e5087f4d7` |
| 表示 / 维度 / 分数 | `token_multivector` / 每 token 128 / `maxsim_mean`，逐 token L2 归一化 |
| 编码 | 原生 `MultiVectorEncoder.encode_query/encode_document`；无 dense pooling |
| query / passage 前缀 | `[Q] ` / `[D] `，保留尾随空格 |
| 每 chunk 输入 / 模型 token 上限 | 前 2000 字符；query 1024 / document 4096 tokens |
| query 字符 / 检索不同 token 上限 | 500 / 64 |
| parser chunk 目标 / overlap / 最小值 | 700 / 120 / 80 字符 |
| 请求 batch / 原生 forward batch | 最多 16 / 4 输入 |
| 推理设备 / dtype / 线程 | CPU / float32 / 4 |
| 关键词 / 语义权重 | 0.65 / 0.35，按和归一化 |
| 候选数 | 200 个文件；先约束页，再按模式为每文件选最佳 chunk |
| 评估 top_k | 完整记录 3；关键词评分 1，语义/混合评分 3 |
| API 默认 / 最大 top_k | 10 / 50 |
| AI HTTP timeout | 10 秒；直接 local 推理没有 HTTP deadline |
| 页元数据策略 / 偶数中心页 | `pdf-physical-pages-v1` / 两个中心页均允许，按已有分数选 |
| 网络与回退 | 验证后的本地文件或本地 AI HTTP；无云端回退、无 E5 回退 |

实际运行环境：Python 3.11.5、torch 2.8.0 CPU、transformers 5.22.0、sentence-transformers 6.2.0、torchvision 0.23.0、Pillow 12.1.0、huggingface-hub 2.4.0、SQLAlchemy 2.0.43、pypdf 6.20.1、psycopg 3.2.9、pgvector Python 0.4.1、FastAPI 0.116.1、httpx 0.28.1。服务器为 PostgreSQL 16.15、pgvector 0.8.7；SQLite 3.41.2。token 矩阵使用 C JSON/JSONB 表进行精确 MaxSim，不能据此声称使用了 pgvector ANN。旧共享 384 维列仍保留但不参与 PPLX。

## 实际命令与重放

以下均从上文 C worktree 执行。`***` 是原始 JSON 的密码脱敏占位，重放时换成获授权本地数据库密码，不能按字面执行。`*-command.json` 保存实际绝对解释器/输出路径、argv、开始/结束时间、环境、returncode 和 stdout/stderr；此处用等价相对路径排版。

四次真实 PDF 检索均已完整执行。纯模型因质量门未达返回 1，增强返回 0；`status=evaluated` 不等于进程中途失败。

```powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:USE_TF = '0'
.\.venv-pplx\Scripts\python.exe -m scripts.evaluate_team_pdf --database-url postgresql+psycopg://postgres:***@127.0.0.1:55432/team11_c_pdf --backend local --no-page-navigation --output submissions/week07/evidence/C/20261030-page-navigation/postgres-model-only.json
.\.venv-pplx\Scripts\python.exe -m scripts.evaluate_team_pdf --database-url postgresql+psycopg://postgres:***@127.0.0.1:55432/team11_c_pdf --backend local --page-navigation --output submissions/week07/evidence/C/20261030-page-navigation/postgres-navigation.json
.\.venv-pplx\Scripts\python.exe -m scripts.evaluate_team_pdf --database-url sqlite:///work/team-pdf-clean.db --backend local --no-page-navigation --output submissions/week07/evidence/C/20261030-page-navigation/sqlite-model-only.json
.\.venv-pplx\Scripts\python.exe -m scripts.evaluate_team_pdf --database-url sqlite:///work/team-pdf-clean.db --backend local --page-navigation --output submissions/week07/evidence/C/20261030-page-navigation/sqlite-navigation.json
```

PG 评估采用实际 Alembic 迁移链至 `20261015_0002` 后显式准备 C 派生表；SQLite 只验证既有 ORM 测试 schema。四次都调用正常扫描、PDF 解析、关键词索引与本地模型向量索引，未使用手工 source chunk 代替。同步 handler runner 未证明统一 API→队列→Worker 调度。

两次独立回归实际命令如下，均返回 0。专用 PG 回归库不与团队 PDF 或恢复库共用。

```powershell
.\.venv-pplx\Scripts\python.exe -m scripts.verify_page_navigation --database-url postgresql+psycopg://postgres:***@127.0.0.1:55432/team11_c_navigation_20261030 --work-dir work/page-navigation-final-postgres --output submissions/week07/evidence/C/20261030-page-navigation/navigation-regression-postgres.json
.\.venv-pplx\Scripts\python.exe -m scripts.verify_page_navigation --database-url sqlite:///work/page-navigation-final.db --work-dir work/page-navigation-final-sqlite --output submissions/week07/evidence/C/20261030-page-navigation/navigation-regression-sqlite.json
```

显式 schema 准备、单版本及整根页数补录也已实际执行，全部返回 0；整根 **12/12** 就绪、错误 0，单版本 **1/1** 就绪。补录使用该数据库授权根对应的源 mount；跨机器操作前应按现有服务配置正确设置 `SOURCE_MOUNTS`，不能替换成同名或未授权目录。

```powershell
.\.venv-pplx\Scripts\python.exe -m scripts.search_tools prepare-token-index --database-url postgresql+psycopg://postgres:***@127.0.0.1:55432/team11_c_pdf
.\.venv-pplx\Scripts\python.exe -m scripts.search_tools page-metadata --database-url postgresql+psycopg://postgres:***@127.0.0.1:55432/team11_c_pdf --root-id dc70538c-f5de-489a-85f7-e363d8cbaacc --version-id 0f28272f-3930-42ea-9039-9ba9c71d5cba --output submissions/week07/evidence/C/20261030-page-navigation/metadata-version.json
.\.venv-pplx\Scripts\python.exe -m scripts.search_tools page-metadata --database-url postgresql+psycopg://postgres:***@127.0.0.1:55432/team11_c_pdf --root-id dc70538c-f5de-489a-85f7-e363d8cbaacc --output submissions/week07/evidence/C/20261030-page-navigation/metadata-root.json
```

新机器的模型联网准备、离线校验和常规恢复操作见 [页导航操作指南](../../../../../docs/search-page-navigation.md) 与 [模型准备历史证据](../20261030-pplx/model-preparation.json)。下面是操作入口，不声称本轮再次联网下载；导航本身不改模型文件：

```powershell
.\.venv-pplx\Scripts\python.exe -m scripts.search_tools download-model --model-path models/pplx-embed-v2-late-0.6b
.\.venv-pplx\Scripts\python.exe -m scripts.search_tools index --database-url YOUR_DATABASE_URL --version-id CURRENT_VERSION_UUID --backend http --ai-url http://127.0.0.1:8100 --timeout 10
```

先准备且预热本地服务，再对当前可读版本重复现有 index，检查 `embedding_error=null`、`embedded_count=chunk_count` 以及独立 `page_metadata_error`。模型不可用时保留明确错误；不自动下载或转云端，不以 Worker completed 代替就绪检查。

## 测试、降级与 HTTP 恢复状态

本轮实际全量测试与 Ruff 命令：

```powershell
$env:SEARCH_TEST_DATABASE_URL = 'postgresql+psycopg://postgres:***@127.0.0.1:55432/team11_c_navigation_20261030'
.\.venv-pplx\Scripts\python.exe -m pytest -q tests/unit tests/integration --junitxml=submissions/week07/evidence/C/20261030-page-navigation/pytest-final-results.xml
.\.venv-pplx\Scripts\python.exe -m ruff check .
```

[最终 JUnit](pytest-final-results.xml) 记录 **532 用例：530 passed、2 skipped、0 failures、0 errors**，suite 时间 99.448 秒，命令输出约 99.47 秒。5 个 PostgreSQL 搜索测试和 6 个 PostgreSQL 队列并发测试均实际执行。两个 skip 是 Windows 缺少 symlink 创建权限的扫描测试，不跟随目录链接和拒绝越界根链接的场景不能据本机跳过声称通过。Ruff 返回 0，输出 `All checks passed!`。先前在检索基线 `e364f5b` 的 [529 用例 / 527 通过报告](pytest-results.xml) 和对应命令输出保留；新增 3 项覆盖团队 gold、freeze 和 SQLite 数据库报告路径保护，并逐一验证受保护字节及 SHA 未变。

首次全量测试曾为 521 passed、2 skipped、6 setup errors，原因是新 C 测试库未在 `public` schema 安装 `vector`，队列用例的共享表初始化失败。执行 `CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public` 后完整重跑，上述 6 个用例全部通过；不是通过更改测试或跳过它们获得最终结果。原始失败摘要与修复记于 [verification-summary.json](verification-summary.json)。

相关用例覆盖中英文解析、目标页约束先于去重/截断、偶数中页、同页多 chunk、缺失/过期元数据、页数准备身份校验、旧版本、撤销授权、缺失文件、同名异路径、缺向量、AI 不可用/超时、关键词回退及证据一致性。结构化导航不能消除 `degraded`；断开/超时路径应继续报告 requested `mode`、`effective_mode=keyword`、`degraded=true` 及 `ai_unavailable/ai_timeout`，回退关键词及原文证据仍须可用。

本轮 [http-recovery.json](http-recovery.json) 在独立 `team11_c_recovery_20261030` 库返回 `stage=complete`、`passed=true`，命令返回 0。[runtime-bootstrap.json](runtime-bootstrap.json) 为它的 AI-off 扫描解析初始状态：20 个关键词 sidecar、0 个 token 矩阵、12 个可信页数版本；关键词 **5/5**，semantic/hybrid 均 **0/5**，10 次降级，初始命令返回 1 符合预期。

该准备命令已经实际执行：

```powershell
.\.venv-pplx\Scripts\python.exe -m scripts.evaluate_team_pdf --database-url postgresql+psycopg://postgres:***@127.0.0.1:55432/team11_c_recovery_20261030 --backend off --page-navigation --output submissions/week07/evidence/C/20261030-page-navigation/runtime-bootstrap.json
.\.venv-pplx\Scripts\python.exe -m scripts.verify_team_search_runtime --database-url postgresql+psycopg://postgres:***@127.0.0.1:55432/team11_c_recovery_20261030 --evaluation submissions/week07/evidence/C/20261030-page-navigation/runtime-bootstrap.json --page-navigation --output submissions/week07/evidence/C/20261030-page-navigation/http-recovery.json
```

| 场景 | 精确执行数与实际行为 |
| --- | --- |
| AI 运行前失败索引 | 现有 index 返回 1，`embedding_error=ai_unavailable`、`embedded_count=0`；页数仍准备成功 |
| 预热后补向量 | 对 12 个当前可读版本运行现有 index，恢复 20 个兼容矩阵 / 416 token 向量，12 个页元数据版本就绪 |
| 在线搜索 | 15 次 HTTP 请求全部命中，5 关键词+5 semantic+5 hybrid，requested/effective 一致、无降级，逐条证据可读 |
| 实际停止 AI | 3 个常规探针：keyword 保持非降级，semantic/hybrid 明确转 keyword，`degraded=true`、`ai_unavailable`；关键词与原文可用 |
| 明确页导航时停止 AI | 额外 2 个 semantic/hybrid 探针均转 keyword、`ai_unavailable`，`navigation_assistance_applied=false`、`semantic_hit=false` |
| 实际 HTTP 超时 | 2 个常规 semantic/hybrid 探针均转 keyword、`ai_timeout`；实测约 10.250 / 10.282 秒 |
| 明确页导航时超时 | 额外 2 个 semantic/hybrid 探针均转 keyword、`ai_timeout`，导航未应用、`semantic_hit=false`；约 10.250 / 10.265 秒 |
| AI 恢复 | 同一 index 再次返回 0；普通 hybrid 恢复非降级，另对 S02 的 hybrid 搜索 #1 返回 D10/p3，命中且原文可读 |

断开探针包括那次无需 AI 的 keyword 请求，不能把所有 3 次都写成降级；需要 AI 的 8 个断开/超时请求（常规 2+2、导航 2+2）均准确降级。常规探针即使关键词命中，也因 `degraded=true` 而 `hit=false`；明确导航探针单独记录 `semantic_hit=false`。这些探针验证故障行为，不添加进 5/5 语义质量分母。

恢复后的 S02 chunk 为 `baaaef37-ec7e-4874-9157-f478b4ac0b0c`，当前 version 为 `1cc59349-b806-41f9-88f2-0964755e41ed`，Top-1 混合分数 `0.249184`，`degraded=false`，证据身份和源 SHA 核验通过。最终 `source_identities_unchanged=true`、`all_corpus_bytes_unchanged=true`，16 个源文件及全部 canonical ID 保持不变。HTTP 报告中的 `resolved_expected.semantic_ready=false` 来自 AI-off 初始报告的输入解析快照；恢复后实时就绪应读 `recovered/final_vector_chunks=20`、`recovered/final_token_vectors=416` 及在线响应，不能把输入快照误当恢复后的数据库状态。

运行验证使用 120 秒模型预热预算、180 秒索引子进程预算，普通 AI HTTP 请求仍为 10 秒。首次成功补索引的实际命令如下；44786 是本轮临时本地 AI 端口，手工恢复需替换当前服务端口，其余版本命令保存在原始 JSON：

```powershell
.\.venv-pplx\Scripts\python.exe -m scripts.search_tools index --database-url postgresql+psycopg://postgres:***@127.0.0.1:55432/team11_c_recovery_20261030 --version-id 03cd3902-cea3-437d-8677-0acfb3fe5801 --backend http --ai-url http://127.0.0.1:44786 --timeout 10.0
```

本轮真实本地 HTTP 故障/恢复验证通过；它不代替统一团队 Compose 的部署验收。专用恢复 API/UI 不在本轮范围。

## 异常 PDF 分类差异与 A/B/D 交接

以下四条分类差异从正常解析结果原样保留，没有为满足 manifest 强制改写 B 的解析状态；它们不改变 5/5/5 检索分母。

| 文件 | 冻结 status / error | 实际 status / error |
| --- | --- | --- |
| `abnormal/corrupt.pdf` | `failed / CORRUPT_PDF` | `unsupported / unsupported_format` |
| `abnormal/empty.pdf` | `failed / EMPTY_FILE` | `unsupported / unsupported_format` |
| `abnormal/truncated.pdf` | `failed / TRUNCATED_PDF` | `unsupported / corrupt` |
| `unsupported/team11-unsupported-notes.docx` | `unsupported / UNSUPPORTED_FORMAT` | `unsupported / unsupported_format` |

A 需将新 `version_page_search_metadata` 与 C token schema 的准备纳入统一部署/共享迁移，准备 PostgreSQL/pgvector、固定哈希本地模型和同一只读授权源挂载。索引调度应分别处理 `page_metadata_error` 与 `embedding_error`，确保对当前版本恢复。现有 Worker 可能在 embedding error 非空时仍标 completed；失败/重试语义仍由 A 统筹。共享模型、迁移、API 主装配与 Worker 未由本轮导航修改。统一服务重启、队列索引与备机部署仍需 A 验证。

B 需完成预期原文/物理页/可接受来源的人审，保留 `pending` 直至实际批准。源物理页计数包括空白页，chunk 页未知时不能填造；parser revision 变化后需显式重新准备匹配元数据。B/D 还需对齐上述异常分类及错误码；本轮不替其改答案。

B/D/A 需确定唯一团队语料。D 的 `fixtures/normal/team-*` 与 B/Compose 的 `tests/fixtures/regression` 路径、哈希及页数不同，不能按文件名互换。当前结果仅针对原始 D freeze。若评估真实主题语义能力，应新建经 B 审核的统一语料、主题问题与 freeze，并由团队明确门槛；保留本轮纯模型失败及增强归因。D 可复用现有响应和证据接口；前端改造未纳入。

已知限制包括：B 人审未完成；4/5 只是 C 候选而非团队冻结线；此批模板 PDF 不是主题盲测；SQLite 不是共享迁移证据；两条 Windows symlink 测试未运行；精确 JSON token MaxSim 的大规模性能未验证；直接 local 模式无 HTTP deadline；统一团队 Compose API→队列→Worker、重启和备机尚未验证。云端回退、完整图谱、专用恢复 UI/API 和前端改造均不在本轮范围。

## 原始证据索引

| 文件 | 内容 |
| --- | --- |
| [verification-summary.json](verification-summary.json) | 产品 SHA、测试、HTTP、冻结/历史完整性和限制汇总 |
| [profile-comparison.json](profile-comparison.json) | 四配置汇总、逐题对照与纯模型历史结果一致性 |
| [model-config.json](model-config.json) | 未变模型/参数及全部 14 个官方固定文件 SHA-256 |
| [artifact-hashes.json](artifact-hashes.json) | 原始交付证据文件 SHA-256 清单 |
| [postgres-model-only.json](postgres-model-only.json) / [sqlite-model-only.json](sqlite-model-only.json) | 纯 PPLX 3/5 基线、15 次逐条 Top-3、版本/chunk/页/原文和源身份 |
| [postgres-navigation.json](postgres-navigation.json) / [sqlite-navigation.json](sqlite-navigation.json) | 页导航增强 5/5、逐文件页数/目标/应用诊断、完整原始结果 |
| [postgres-model-only-command.json](postgres-model-only-command.json) / [postgres-navigation-command.json](postgres-navigation-command.json) | PostgreSQL 实际命令、环境、返回码与输出 |
| [sqlite-model-only-command.json](sqlite-model-only-command.json) / [sqlite-navigation-command.json](sqlite-navigation-command.json) | SQLite 实际命令、环境、返回码与输出 |
| [navigation-regression-postgres.json](navigation-regression-postgres.json) / [navigation-regression-sqlite.json](navigation-regression-sqlite.json) | 36 冻结 case、每库 72 增强+72 对照、证据及导航诊断 |
| [navigation-regression-postgres-command.json](navigation-regression-postgres-command.json) / [navigation-regression-sqlite-command.json](navigation-regression-sqlite-command.json) | 两库导航回归的实际命令及成功退出记录 |
| [prepare-search-schema-command.json](prepare-search-schema-command.json) | 显式 schema 准备实测 |
| [metadata-root.json](metadata-root.json) / [metadata-version.json](metadata-version.json) | 整根 12/12、单版本 1/1 物理页数补录 |
| [metadata-root-command.json](metadata-root-command.json) / [metadata-version-command.json](metadata-version-command.json) | 授权根/当前版本补录实际命令及输出 |
| [metadata-root-final.json](metadata-root-final.json) / [metadata-root-final-command.json](metadata-root-final-command.json) | 最终输出保护提交后的整根补录复测，12/12 就绪 |
| [runtime-bootstrap.json](runtime-bootstrap.json) / [runtime-bootstrap-command.json](runtime-bootstrap-command.json) | 独立恢复库 AI-off 初始状态，不是 HTTP 恢复通过证据 |
| [http-recovery.json](http-recovery.json) / [http-recovery-command.json](http-recovery-command.json) | 本轮真实本地在线、断开、超时、现有补索引与恢复的全部 HTTP/证据及实际命令 |
| [pytest-final-command.json](pytest-final-command.json) / [pytest-final-results.xml](pytest-final-results.xml) | 最终 530 passed、2 skipped 的实际测试及 JUnit |
| [ruff-final-command.json](ruff-final-command.json) | 最终 Ruff 实际命令及通过输出 |
| [pytest-command.json](pytest-command.json) / [pytest-results.xml](pytest-results.xml) / [ruff-command.json](ruff-command.json) | 检索基线下先前 527 passed、2 skipped 与 Ruff 原始记录 |
| [artifact-hashes.json](artifact-hashes.json) | 本目录交付文件的原始字节 SHA-256 索引 |
| [历史 PPLX 目录](../20261030-pplx/README.md) | 历史纯模型 3/5、页内分差、模型校验与旧模型清理，保持独立 |

所有新结论以本目录独立原始证据为准；继续保留本轮纯模型失败、原冻结答案及全部历史报告。
