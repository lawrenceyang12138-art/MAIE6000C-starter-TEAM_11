# C：团队 PDF 检索验证记录

验证窗口为 2026-10-29 至 2026-10-30（Asia/Shanghai）；目录日期是本轮启动日期。
已完成实现、真实 PDF 链路及降级恢复验证。关键词 Top-1 **5/5**；真实 E5
语义 Top-3 **3/5**，未达到 C 候选 **4/5** 门槛；混合 Top-3 **3/5**。
该语义门槛尚未成为团队冻结门槛，混合检索没有另行冻结的验收门槛。
B 人工 gold 审核仍为 **pending**，本报告不构成团队统一验收通过。

## 分支、基线及修改范围

- 隔离 worktree：`tmp/c-team-pdf-evaluation`；分支 `codex/c-team-pdf-evaluation`。
- 本地 develop 基线：`7522287126061da8977c253256e8f807143ab8b5`。
- HTTPS fetch 实际观察到的远程 develop：
  `047b2ac8b6c584b366c3db8f211125a6b9febe4f`，已包含在上述本地基线中。
  原 SSH fetch 的公钥认证失败，随后改用 HTTPS 读取；未推送。
- 主实现：`353620b3cd808a1673afe842be22dad4f5836672`。
  HTTP 在线/断连/超时/0→20 补向量验证在此提交执行。
- 最终代码：`2f98a44f8c1214b9310110b4721242678c9036e4`。
  此提交补充报告输出路径保护，防止覆盖冻结输入或 PDF；最终 PostgreSQL、
  SQLite 评估及完整测试在此提交执行。每份 JSON 另含源码 SHA-256 和实际命令。
- README、W7 合同、search plan/handoff、B handover、D gold/freeze 已检查；
  未发现 AGENTS.md。原工作区仍在 `feat/c-search-model-evaluation`，原有
  `.codex/`、`frontend/`、`tmp/` 未提交内容保留。没有合入 develop。
- 修改集中于 `services/search/`、搜索评估 CLI、对应测试及 C 文档。
  shared models、Alembic、API 主装配、Worker 均未修改。

适配器支持 `expected[]` 和 `semantic_description`，通过授权 root UUID、
manifest 的完整相对路径、文件 SHA-256 和当前版本映射实际扫描 ID；不以同名
文件或 mock ID 充当真实来源。无有效授权范围时不执行全局搜索。缺页、旧版本、
内容不符、索引未就绪等情况有独立诊断，错误样本保留在分母中。
检索修复将完全缺失 search sidecar 的 chunk 也纳入向量完整性检查，避免漏报
`partial_embeddings`。本地模型准备与加载都校验固定的六个可信文件哈希。

## 冻结输入和正常扫描链路

| 输入 | 版本 | SHA-256 |
| --- | --- | --- |
| gold | `team11-gold-v1` | `d1d7b7daf285ed8ad596546dc1cacb28bca7b23cd26edc748e7636e1a23db053` |
| manifest | `d-fixtures-v1` | `3ad53b3f8ccdc7ac6b84457fcedf9a735fe0ddf7ceb8004eb97b46ab17e3280f` |
| freeze | `team11-gold-freeze-v1` | 各原始报告的 `answer_version.freeze_sha256` |

冻结答案未改。准确语料为 16 个文件：12 个正常 PDF、20 页，3 个异常 PDF，
1 个不支持的 DOCX。重复内容组、额外重复文件、重复路径和返回结果的重复文件
均为 **0**。D 明确将它定义为编号占位文本的 **source-location smoke**，
并非真实主题内容的语义质量基准。历史手工 chunk 的 5/5、4/5 继续是历史结果。

runner 将 manifest 的精确文件集合暂存到 `work/team-pdf-corpus`，使用现有
扫描→PDF 解析→chunk 持久化→关键词索引→真实本地向量处理函数；本轮每个文件
均重新解析，避免沿用人工注入的 chunk。最终为 12 个 `basic_ready` 文件、
20 个索引 chunk、20 个真实向量。冻结输入、暂存来源和每条证据的磁盘哈希均核对。
重复运行保持不变来源的 file/version/chunk ID。

PostgreSQL 使用真实 Alembic 链到 `20261015_0002`，数据库为 C 专用容器中的
`team11_c_pdf`；PostgreSQL **16.15**、pgvector **0.8.7**。
镜像标识为 `sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a`。
SQLite 使用 ORM 测试 schema，因为现有共享迁移的 ALTER COLUMN 不兼容 SQLite；
该替代路径已明确标记，不算迁移通过证据。

## 实际结果和逐 query 记录

10 条冻结 query 执行 **15 次搜索**：5 次 keyword、5 次 semantic、5 次 hybrid。
各自分母是 **5、5、5**，没有缩减失败分母。所有模式记录 Top-3，keyword 仅按
Top-1 判分，要求文件和页码都正确。真实 PostgreSQL 与 SQLite 结果一致。
15 次均没有降级，来源诊断、证据失败、磁盘证据失败及结果重复数均为 0。

下表用 `编号:p页码` 表示 `team11-demo-NN.pdf`；01–06 位于
`normal/team-alpha/`，07–12 位于 `normal/team-beta/`。
语义与混合本轮的完整 Top-3 相同，但在原始 JSON 中分别记录并分别计分。

| ID | query | 模式 | 预期 | 实际 Top-3（按排名） | 命中排名 / 命中 |
| --- | --- | --- | --- | --- | --- |
| K01 | Team 11 synthetic document 01 | keyword | 01:p1 | 01:p1, 04:p1, 02:p1 | 1 / 是 |
| K02 | 查找包含 Team 11 synthetic document 02 的文件 | keyword | 02:p1 | 02:p1, 04:p1, 01:p1 | 1 / 是 |
| K03 | Team 11 synthetic document 03 | keyword | 03:p1 | 03:p1, 04:p1, 01:p1 | 1 / 是 |
| K04 | Team 11 synthetic document 07 | keyword | 07:p1 | 07:p1, 04:p1, 01:p1 | 1 / 是 |
| K05 | 查找包含 Team 11 synthetic document 08 的文件 | keyword | 08:p1 | 08:p1, 04:p1, 01:p1 | 1 / 是 |
| S01 | Show the middle leaf in the ninth sample. | semantic / hybrid | 09:p2 | 09:p2, 10:p2, 12:p3 | 1 / 是 |
| S02 | 打开第十份资料的最后一页 | semantic / hybrid | 10:p3 | 10:p2, 09:p3, 12:p3 | 无 / 否 |
| S03 | Locate the opening leaf in the eleventh sample. | semantic / hybrid | 11:p1 | 12:p1, 10:p1, 09:p1 | 无 / 否 |
| S04 | 查看第十二份资料正中间的那一页 | semantic / hybrid | 12:p2 | 12:p2, 11:p2, 09:p2 | 1 / 是 |
| S05 | 找出第六份只有一页的资料 | semantic / hybrid | 06:p1 | 09:p1, 12:p1, 06:p1 | 3 / 是 |

[postgres-local.json](postgres-local.json) 的 `queries[]` 是逐条完整原始记录：
query、expected、映射后的真实 file/version ID、requested/effective mode、
degraded、hit、expected_matches、完整 `ranked_results`（每项含 rank、页码、
chunk_id、分数和 evidence 原文）。`on_disk_evidence` 记录磁盘哈希核验。
[summary.json](summary.json) 也保留这 15 条的完整 Top-3。

S02 找对文件但取到第 2 页而非第 3 页，严格计失败；S03 预期文件未进入 Top-3。
未通过更改 gold、文件去重规则或插入手写 chunk 消除失败。
真实模型评估 CLI 因候选质量门槛未通过而退出 **1**，完整 JSON 正常生成；
`evaluation_valid=true` 与 `candidate_gate_passed=false` 分别记录评估有效性和质量门槛。

## 真实降级和恢复

[http-runtime.json](http-runtime.json) 在单独的 `team11_c_runtime` 数据库启动
本地 AI/API，完成 15 次 HTTP 搜索和所有返回 chunk 的 `/evidence/{chunk_id}`
读取；随后真正停止 AI 进程，并用延迟 10.5 秒的 HTTP 服务触发 10 秒 deadline。

| 情况 | requested (`mode`) | effective_mode | degraded | 原因 | 证据 / 语义计分 |
| --- | --- | --- | --- | --- | --- |
| AI 断开 | keyword | keyword | false | null | 关键词及原文可用 |
| AI 断开 | semantic / hybrid | keyword | true | ai_unavailable | 关键词及原文可用；不计模型命中 |
| AI 超时 | semantic / hybrid | keyword | true | ai_timeout | 关键词及原文可用；不计模型命中 |

实际包含搜索及证据读取的耗时为 **10.250 秒 / 10.234 秒**。降级行即便定位正确，
`location_hit=true` 也不会变成语义 `hit=true`。另有
[sqlite-model-missing.json](sqlite-model-missing.json) 的 `local_model_missing`
实测，以及 `off` 报告中的 `ai_disabled`。

在 AI 未启动时，现有 index CLI 返回 `ai_unavailable`，关键词索引和源 chunk
保留。恢复本地 AI、预热后，对全部当前 PDF version 执行现有 `search_tools index`，
向量由 **0/20 → 20/20**；再断开、超时、恢复及重复索引后仍为 **20/20**，
所有来源字节和 file/version/chunk ID 不变。没有新增恢复 API/UI。

## 固定模型、参数和运行命令

[configuration.json](configuration.json) 固定完整配置和六个模型文件 SHA-256；
[requirements-actual.txt](requirements-actual.txt) 保存干净环境的实际版本。
模型为 `intfloat/multilingual-e5-small`，revision
`614241f622f53c4eeff9890bdc4f31cfecc418b3`，384 维，
`query: ` / `passage: ` 前缀，attention-mask mean pooling 后 L2 归一化。
batch=16、CPU threads=4、输入最多 2000 字符/512 tokens；解析 chunk=700、
overlap=120、min=80；权重 keyword=0.65、semantic=0.35，candidate=200/channel，
评估 top_k=3（keyword 判分 k=1），API 默认 10/最大 50；HTTP timeout=10 秒。
进程内 local backend 没有 HTTP deadline，此限制单独记录。
实际为 Python **3.11.5**、Torch **2.8.0**、Transformers **4.57.1**，无云端回退。

在隔离 worktree 中执行的主要 PowerShell 命令如下。完整绝对路径 argv 在各 JSON
的 `command` 及 summary 的 `tests.command_record` 中，连接密码已在 runner 输出脱敏。
这里的 postgres/postgres 是 C 专用本机测试容器的演示凭据。

```powershell
python -m venv .venv-clean
.\.venv-clean\Scripts\python.exe -m pip install work/wheels/torch-2.8.0-cp311-cp311-win_amd64.whl -e '.[dev,embeddings]' --timeout 120 --progress-bar off --disable-pip-version-check
.\.venv-clean\Scripts\python.exe -m pip check

$env:HF_HUB_OFFLINE='1'
.\.venv-clean\Scripts\python.exe -m scripts.search_tools download-model

.\.venv-clean\Scripts\python.exe -m scripts.evaluate_team_pdf --database-url postgresql+psycopg://postgres:postgres@127.0.0.1:55432/team11_c_pdf --backend local --output submissions/week07/evidence/C/team-pdf-20261029/postgres-local.json
.\.venv-clean\Scripts\python.exe -m scripts.evaluate_team_pdf --database-url sqlite:///work/team-pdf-clean.db --backend local --output submissions/week07/evidence/C/team-pdf-20261029/sqlite-local.json
.\.venv-clean\Scripts\python.exe -m scripts.verify_team_search_runtime --database-url postgresql+psycopg://postgres:postgres@127.0.0.1:55432/team11_c_runtime --evaluation submissions/week07/evidence/C/team-pdf-20261029/postgres-runtime-before.json --model-path models/multilingual-e5-small --timeout 10 --output submissions/week07/evidence/C/team-pdf-20261029/http-runtime.json

$env:SEARCH_TEST_DATABASE_URL='postgresql+psycopg://postgres:postgres@127.0.0.1:55432/team11_c_pdf'
.\.venv-clean\Scripts\python.exe -m pytest -q tests/unit tests/integration --junitxml=submissions/week07/evidence/C/team-pdf-20261029/pytest-results.xml
.\.venv-clean\Scripts\python.exe -m ruff check .
git diff --check
```

本机先从官方固定 revision 下载模型，再离线运行上述准备命令，六个哈希校验通过；
不是在 offline 模式下声称重新下载。安装时使用的本地 Torch wheel 仅用于复用本机
下载，新机器可按 `docs/search-team-pdf-evaluation.md` 的普通 pip + download-model
步骤联网准备，然后离线运行。模型权重、venv、数据库及暂存文件均未加入 Git。
原 `.venv` 继承系统包，升级后模型预热曾超时；失败 JSON 已保留。最终使用完全
独立、`include-system-site-packages=false` 的 `.venv-clean`，`pip check` 通过。

最终测试为 **349 passed、2 skipped、0 failed**，351 cases；2 个 skip 均因
Windows 无法创建测试 symlink。10 个 PostgreSQL 测试实际运行。Ruff 和 diff check
通过。覆盖范围包括版本切换、授权 active/paused/revoked、root/file 范围交集、
missing/unavailable、按文件去重、缺失/部分向量、超时/断开、证据关联、冻结预检和
禁止报告覆盖输入。新模型准备校验测试也通过。

AI 恢复的日常命令：先对本地服务 `/embeddings` 用 60 秒客户端 timeout 预热，
再对缺失或不兼容向量的每个**当前可读版本**执行：

```powershell
.\.venv-clean\Scripts\python.exe -m scripts.search_tools index --database-url YOUR_DATABASE_URL --version-id CURRENT_VERSION_UUID --backend http --ai-url http://127.0.0.1:8100 --timeout 10
```

检查 `embedding_error=null`、`embedded_count=chunk_count`，再验证 semantic/hybrid。
也可用 `--backend local --model-path models/multilingual-e5-small` 本机补向量。

## A / B / D 交接及未完成依赖

1. **A+B+D：统一语料尚未完成。** Compose 挂载 B 的 `tests/fixtures/regression`
   和 parsing 样本；D freeze 指向 `fixtures/normal/team-*`、abnormal 及 DOCX。
   路径、哈希、页数不同，本报告只能说明对未修改 D 语料的结果。A 需让 API/Worker
   使用相同的只读 mount/授权范围；若改用 B 语料，B/D 需发布新 gold/freeze。
2. **B+D：gold 人工复核 pending。** 审核所有 excerpt、页码和 acceptable locations；
   决定编号占位语料能否支撑质量验收。语义 4/5 为 C 候选门槛；不能沿用历史
   手写 chunk 的 4/5 作为团队 PDF 成绩，也不能将降级定位计作模型命中。
3. **B+D：4 项异常分类差异。** D 期望 corrupt/empty/truncated 为 failed，
   实际 parser 均给 unsupported；对应错误为 unsupported_format / unsupported_format /
   corrupt。DOCX 状态相同，但 D uppercase mock error 与实际 lowercase 不同。
   完整差异在 `pipeline.frozen_classification_differences`，检索分母未改。
4. **A：环境和向量就绪。** 提供 pgvector、上述固定权重、相同 mounts 和授权配置，
   首次模型预热后检查向量覆盖。Worker 当前遇到 embedding_error 仍标 completed，
   失败只在日志；请统筹失败状态/重试。当前已验证的恢复方法是手动 index CLI。
5. **A：共享迁移与装配。** SQLite ALTER COLUMN 兼容性归 A；本轮不修改共享模型、
   迁移、API 主装配或 Worker。真实生产 handlers 已运行，整体 Compose API→队列→
   Worker 的统一语料验收、备用电脑部署均未运行。
6. **工具限制。** 支持字段形状的未知 gold schema_version 目前仍接受；direct local
   推理没有总 deadline。HTTP 验证脚本首次预热限 65 秒、单个索引子命令限 90 秒，
   适合本轮 1–3 页小 PDF；连接不可达数据库的初始快照没有专门的超时参数。

## 原始证据索引

- `postgres-local.json`、`sqlite-local.json`：最终干净环境真实 E5 PDF 评估。
- `http-runtime.json`、`postgres-runtime-before.json`：HTTP 协议、真实超时及 0→20 恢复。
- `postgres-off.json`、`sqlite-off.json`、`sqlite-model-missing.json`：关闭/缺模型降级。
- `gold-source-check.json`：D 的只读来源校验（本身不是检索评估或 B 人审）。
- `pytest-results.xml`：最终完整测试记录；`summary.json` 索引上述文件的哈希和大小。
- `postgres-local-backup-runtime.json`：早期 Torch 2.0.0/Transformers 4.32.1 的真实
  3/5 结果，作为过程证据保留；不与最终固定软件环境混计。
- `http-runtime-inherited-env-failed.json`、`sqlite-migration-initial-failed.json`：
  环境预热失败、共享 SQLite 迁移失败的原始记录；均未隐藏或当作成功。
- `model-preparation.json`、`configuration.json`、`requirements-actual.txt`：模型准备、
  固定参数与实际依赖版本。源码与输入的哈希另见每个 runner 的 JSON。
