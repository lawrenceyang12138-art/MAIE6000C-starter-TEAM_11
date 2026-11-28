# C：团队 PDF 检索与本地 PPLX 实测（2026-10-30）

本轮使用正常 PDF 扫描、解析和索引产物，在 PostgreSQL 与 SQLite 上均得到关键词 Top-1 **5/5**、语义 Top-3 **3/5**、混合 Top-3 **3/5**。15 次检索全部实际执行、无降级，来源与原文证据检查通过；语义结果仍低于 C 的 **4/5 候选门槛**。该门槛尚未成为团队冻结验收标准，B 人工 gold 审核仍为 **pending**，不能据此宣布团队验收通过。

冻结 gold 自身限定为 `Source-location smoke tests for the existing synthetic corpus; not a semantic-quality benchmark.`。这些模板 PDF 能验证来源定位及页码，不足以证明真实主题文档的通用语义质量。

## 代码、语料和答案版本

| 项目 | 本轮记录 |
| --- | --- |
| 分支 | `codex/c-team-pdf-evaluation` |
| C 隔离工作区 | `D:\HKUST AIE\MAIE6000C\MAIE6000C-starter-TEAM_11\tmp\c-team-pdf-evaluation` |
| 角色 C 集成基线 | `7522287126061da8977c253256e8f807143ab8b5` |
| 检查到的 develop | `047b2ac8b6c584b366c3db8f211125a6b9febe4f`，已包含于上述基线 |
| 实测产品代码 SHA | `40879c44f2777db7dafd559cc97f5edc8b3f6714` |
| gold | `submissions/week07/gold-queries.json`，`team11-gold-v1` |
| manifest | `fixtures/manifest.json`，`d-fixtures-v1`，冻结根别名 `root-demo-01` |
| freeze | `submissions/week07/gold-queries.freeze.json`，`team11-gold-freeze-v1`，冻结日期 `2026-10-16` |
| gold SHA-256 | `d1d7b7daf285ed8ad596546dc1cacb28bca7b23cd26edc748e7636e1a23db053` |
| manifest SHA-256 | `3ad53b3f8ccdc7ac6b84457fcedf9a735fe0ddf7ceb8004eb97b46ab17e3280f` |
| freeze SHA-256 | `2a1ca7744c3176cb9e4df69adaf2f13d087f3fe88d73cb71604a82a3fe88114d` |

原始工作区及其他角色分支保留；本轮没有推送、合入 develop 或操作其他角色分支。评估与测试的实际 Git 状态、相关源码哈希和执行参数保存在原始 JSON。证据文件的后续提交不改变上表的实测产品代码 SHA。

本目录的 `.gitattributes` 保留证据文件原始字节，防止 Git 自动转换换行后使已记录的 SHA-256 失效。

## 评估适配与搜索行为

评估器接受团队 `expected[]` 数组和 `semantic_description` 类型，同时保留旧基准格式。团队 `file-xxx`、`version-xxx-v1` 是冻结别名：先用 manifest 校验别名、完整相对路径与 SHA-256，再在指定真实授权根内解析为扫描生成的 `FileRecord.id` 与当前 `FileVersion.id`。匹配方法记录为 `root_relative_path_sha256`；不会只按 basename 绑定，也不会以历史版本替代当前内容。

就绪检查分别报告 `corpus_mismatch`、`expected_page_missing`、`version_mismatch`、`index_not_ready`，并区分 `root_scope_required`、`corpus_manifest_required`、`root_not_authorized`、`file_missing`。关键词 sidecar 与新模型 token 索引的就绪状态分别判断；内容、模型或维度不兼容的向量不算索引就绪。冻结文件只读，报告目的路径也不能覆盖输入和源文件。

PDF runner 调用已有扫描、解析、索引 handler，使用真实文件及解析页，不注入手工 chunk。此次是同步 handler 链路；统一 Worker 调度器未由该 runner 执行。重复扫描可以复用既有文件/版本 UUID，报告逐文件记录本次解析与索引状态。

搜索只返回授权范围内、仍存在文件的当前可检索版本，每个文件保留一个最佳证据 chunk。测试覆盖当前版本、授权根、缺失文件、去重、缺失关键词 sidecar 时的语义/混合行为，以及旧 384 维列保留。每条 Top-3 结果均回读数据库 chunk 的版本、页码和原文，并检查磁盘 PDF；本轮来源诊断、数据库证据失败、磁盘证据失败均为 0。

新模型采用本地 ColBERT late interaction（不是 late chunking）：保留 token 多向量，以平均 MaxSim 排序，不做 dense pooling。C 自有 token 表使用 JSON / PostgreSQL JSONB；共享模型、既有迁移和旧 384 维 dense 列保留。此实测不代表使用 pgvector ANN 执行了新模型检索。

## 分母、实测成绩与历史对照

| 项目 | PostgreSQL / SQLite 本轮各自计数 |
| --- | --- |
| 唯一 query / 实际检索次数 | 10 / 15：K01–K05 各一次，S01–S05 各执行 semantic、hybrid 两次 |
| 关键词 / 语义 / 混合分母 | 5 / 5 / 5；两个数据库是复核，不合并为新的 10 题分母 |
| 语料 | 16 文件：12 正常 PDF、3 异常 PDF、1 不支持的 DOCX |
| 正常 PDF 页 / canonical source chunk | 20 / 20 |
| 关键词 sidecar / 兼容 chunk token 矩阵 | 20 / 20 |
| 单独 token 向量 / 每 token 维度 | 416 / 128；416 不是 chunk 数 |
| 同路径重复额外文件 / 同内容重复额外文件 | 0 / 0 |
| 返回重复文件 / 降级执行 | 0 / 0 |
| 解析状态 | 12 `basic_ready`、4 `unsupported` |

| 语料、模型及时间 | 关键词 Top-1 | 语义 Top-3 | 混合 Top-3 | 解释 |
| --- | --- | --- | --- | --- |
| 本轮 D 冻结 PDF，PPLX，PostgreSQL | 5/5 | 3/5 | 3/5 | 本轮真实链路 |
| 本轮 D 冻结 PDF，PPLX，SQLite | 5/5 | 3/5 | 3/5 | 独立数据库复核 |
| 同一 D 冻结 PDF，旧 E5，2026-10-29 | 5/5 | 3/5 | 3/5 | 历史真实 PDF 结果，保持原始报告 |
| 早期手工 chunk 基准 | 5/5 | 4/5 | 见历史 JSON | 历史结果，语料不同，不替代本轮成绩 |

旧 E5 版本为 `intfloat/multilingual-e5-small@614241f622f53c4eeff9890bdc4f31cfecc418b3`，历史实测代码 `2f98a44f8c1214b9310110b4721242678c9036e4`。旧 E5 失败题为 S02/S03；PPLX 修复 S03，但 S04 退化，因此总成绩没有提高。旧 E5 的 S05 在 Top-3 命中，首位是 09:p1；新模型将正确的 06:p1 排到第一。dense cosine 与 token MaxSim 的绝对分值不直接比较。

### 逐题 query 与完整 Top-3

以下 `NN:pM` 表示 `team11-demo-NN.pdf` 第 M 页，01–06 位于 `normal/team-alpha/`，07–12 位于 `normal/team-beta/`。括号为实际返回分值，保留六位；排名从左至右。全部记录 `requested_mode=effective_mode`、`degraded=false`、`degradation_reason=null`。关键词按 Top-1 评分，仍记录 Top-3；semantic/hybrid 按文件及页码同时正确的 Top-3 评分。成功题的正确结果均在第一位。

| ID | query | 冻结预期 | keyword Top-3 | 命中 |
| --- | --- | --- | --- | --- |
| K01 | `Team 11 synthetic document 01` | 01:p1 | 01:p1 (1.000000), 04:p1 (0.640000), 02:p1 (0.640000) | 是，rank 1 |
| K02 | `查找包含 Team 11 synthetic document 02 的文件` | 02:p1 | 02:p1 (0.400000), 04:p1 (0.320000), 01:p1 (0.320000) | 是，rank 1 |
| K03 | `Team 11 synthetic document 03` | 03:p1 | 03:p1 (1.000000), 04:p1 (0.640000), 01:p1 (0.640000) | 是，rank 1 |
| K04 | `Team 11 synthetic document 07` | 07:p1 | 07:p1 (1.000000), 04:p1 (0.640000), 01:p1 (0.640000) | 是，rank 1 |
| K05 | `查找包含 Team 11 synthetic document 08 的文件` | 08:p1 | 08:p1 (0.400000), 04:p1 (0.320000), 01:p1 (0.320000) | 是，rank 1 |

| ID | query | 冻结预期 | semantic Top-3 | hybrid Top-3 | S/H 命中 |
| --- | --- | --- | --- | --- | --- |
| S01 | `Show the middle leaf in the ninth sample.` | 09:p2 | 09:p2 (0.776348), 10:p2 (0.767969), 12:p2 (0.767813) | 09:p2 (0.271722), 10:p2 (0.268789), 12:p2 (0.268735) | 是 / 是，rank 1 |
| S02 | `打开第十份资料的最后一页` | 10:p3 | 10:p1 (0.712317), 11:p3 (0.704184), 12:p3 (0.703161) | 10:p1 (0.249311), 11:p3 (0.246465), 12:p3 (0.246106) | 否 / 否，页码错误 |
| S03 | `Locate the opening leaf in the eleventh sample.` | 11:p1 | 11:p1 (0.811745), 10:p1 (0.811266), 12:p1 (0.810963) | 11:p1 (0.284111), 10:p1 (0.283943), 12:p1 (0.283837) | 是 / 是，rank 1 |
| S04 | `查看第十二份资料正中间的那一页` | 12:p2 | 12:p1 (0.769519), 10:p1 (0.761303), 11:p1 (0.760847) | 12:p1 (0.269332), 10:p1 (0.266456), 11:p1 (0.266296) | 否 / 否，页码错误 |
| S05 | `找出第六份只有一页的资料` | 06:p1 | 06:p1 (0.744691), 12:p1 (0.740329), 10:p1 (0.739433) | 06:p1 (0.260642), 12:p1 (0.259115), 10:p1 (0.258801) | 是 / 是，rank 1 |

PostgreSQL 第一名 chunk 如下；S/H 同行表示两次真实执行返回同一第一名。各自 Top-3 的完整 `chunk_id`、`version_id`、根 ID、原文、逐条证据读取及磁盘检查保存在 [postgres-local.json](postgres-local.json)。SQLite 重新扫描生成不同 UUID，保留在 [sqlite-local.json](sqlite-local.json)，不能混用两库 ID。

| query | 第一名 chunk_id |
| --- | --- |
| K01 | `e9674d9b-4135-4ad3-9290-18debe35c94e` |
| K02 | `b65194b5-0960-4e78-bacb-ebe64b5bec71` |
| K03 | `ea12b854-84e6-4886-ba02-7378e3d8236a` |
| K04 | `972d20ee-b599-4d28-aa56-2d8fa094ea77` |
| K05 | `b8f43080-a761-45a6-b6b9-45540d30260f` |
| S01 semantic / hybrid | `33aa97fa-73fc-4c39-a88e-8feedd1ccbd5` |
| S02 semantic / hybrid | `614ee017-d804-4fb5-b6eb-2e6a7bf0f4ac` |
| S03 semantic / hybrid | `8aeb0fbd-5631-4731-b77d-35ee0f10d382` |
| S04 semantic / hybrid | `e8f2f1c5-f559-4e0d-a1d9-6053445c3646` |
| S05 semantic / hybrid | `f6b6fb53-ceaa-48db-942c-f0bae3a60ac8` |

### S02、S04 失败定位

[failure-analysis.json](failure-analysis.json) 使用同一模型、参数和索引重放四个失败执行，完整范围为 12 个可检索文件。正确文件在两题中都是 rank 1；预期页索引及证据存在，失败属于文件内部选页，而非来源映射、模型不可用、候选截断或缺失索引。

| query | 第一页分值 | 预期页分值 | semantic 错页领先分差 | hybrid 错页领先分差 |
| --- | --- | --- | --- | --- |
| S02 | 10:p1 = 0.7123169898986816 | 10:p3 = 0.7119545340538025 | 0.0003624558448791504 | 0.0001268595457077082 |
| S04 | 12:p1 = 0.7695187330245972 | 12:p2 = 0.7693147659301758 | 0.00020396709442138672 | 0.00007138848304744094 |

S02 预期 chunk 为 `6979ace9-d472-42a3-ba48-69049111f6d0`，版本 `7667c3cb-b722-446c-b2b8-1963a618a8d7`；S04 预期 chunk 为 `48347d49-050c-430c-a220-6412ce4d1a59`，版本 `601121dd-ddbf-4dca-9348-3bb6fcf59d8c`。每文件只返回最佳 chunk，所以只增大文件 Top-k 不能让同一文件的正确页重新出现。

这五个语义 query 的词法分均为 0，当前 hybrid 为 `(0.65 × keyword + 0.35 × semantic) / (0.65 + 0.35)`，在本语料上退化为语义分的 0.35 倍，排序完全相同，没有词法纠正收益。模板的序号及页关系可能造成近分选页，但本轮没有证明其可泛化为模型的主题语义缺陷，也没有修改冻结答案或按题调参。

## AI 断开、超时与现有补向量命令

[http-runtime.json](http-runtime.json) 在独立 `team11_c_runtime` PostgreSQL 数据库运行真实本地 AI HTTP 服务及搜索接口，`passed=true`、`stage=complete`。初始 20 个关键词 sidecar、0 个 token 矩阵；对 12 个当前 PDF 版本运行现有 `scripts.search_tools index` 后恢复为 **20 个 chunk 矩阵 / 416 个 token 向量**。全部源 ID 与 16 个源文件字节保持不变。

| 场景 | requested_mode | effective_mode | degraded | 原因及验证 |
| --- | --- | --- | --- | --- |
| AI 在线 | keyword / semantic / hybrid，各 5 次 | 与 requested 相同 | false | 15 次真实 HTTP 搜索；原文证据可读 |
| 实际停止 AI | semantic / hybrid | keyword | true | `ai_unavailable`；关键词和证据仍可用 |
| 实际延迟 HTTP 超过 10 秒 | semantic / hybrid | keyword | true | `ai_timeout`；两次实测各约 10.25 秒 |
| AI 恢复并再次补索引 | hybrid | hybrid | false | 索引命令成功，恢复非降级检索 |

降级的 semantic/hybrid 结果不计为语义命中。AI 断开时首次 index 返回码 1、`embedded_count=0`、`embedding_error=ai_unavailable`；同一命令在服务预热后返回码 0、无 embedding error。运行报告保留失败命令、12 条恢复命令及恢复后检索。在线 HTTP 搜索耗时约 0.031–0.453 秒，包含逐条证据读取；不是冷启动耗时。原生模型冷加载约 17.203 秒，超过 10 秒请求预算，因此运行验证先预热，预算为 120 秒；index 子进程预算为 180 秒。

专用恢复 API/UI 不在本轮必做范围。恢复操作是先准备并预热本地模型，再对仍存在的当前版本重复运行 index；检查兼容 token 矩阵数量与 `embedding_error`，不能仅看 Worker 的 completed 状态。

## 可复现模型与参数

完整配置及 14 个模型文件的固定 SHA-256 见 [configuration.json](configuration.json)，实际依赖清单见 [requirements-actual.txt](requirements-actual.txt)。

| 配置 | 本轮固定值 |
| --- | --- |
| 模型 | `perplexity-ai/pplx-embed-v2-late-0.6b` |
| revision | `7bba8e7cf2075dec747fa8557f41eb90e70361ed` |
| 本地相对目录 | `models/pplx-embed-v2-late-0.6b` |
| 表示 / 分值 | `token_multivector` / `maxsim_mean`；token L2 归一化，按 query token 数取平均，公共分值限制到 0–1 |
| 输出维度 | 每 token 128；形状为 batch × 可变 token 数 × 128 |
| 编码接口 | Sentence Transformers 原生 `MultiVectorEncoder.encode_query/encode_document` |
| query / passage 前缀 | `[Q] ` / `[D] `，保留尾随空格 |
| query / document 模型 token 上限 | 1024 / 4096 |
| 每 passage 输入限制 | 1–2000 字符；chunk 嵌入取前 2000 字符，原文保留 |
| query 字符 / 检索不同 token 上限 | 500 / 64 |
| embedding 请求 / 原生 forward batch | 最多 16 段 / 最多 4 段 |
| parser 分块目标 / overlap / 最小值 | 700 / 120 / 80 字符 |
| 设备与数值 | CPU、float32、4 线程；无 GPU |
| 关键词 / 语义权重 | 0.65 / 0.35 |
| 候选上限 | 按请求模式评分后取每文件最佳 chunk，再保留最多 200 个候选文件 |
| 评估 top_k | 记录 3，关键词评分 1，语义/混合评分 3 |
| API 默认 / 最大 top_k | 10 / 50 |
| AI HTTP timeout | 10 秒；进程内 local 模式没有 HTTP deadline |
| 推理网络 | 本地模型；无云端回退、无旧 E5 回退 |
| 模型 manifest SHA-256 | `dae099e3f314bb7969ea9aacabaa44b81938416d3fe77fc12f65cd6e5087f4d7` |

实际环境为 Python 3.11.5、torch 2.8.0（原生 build `2.8.0+cpu`）、transformers 5.22.0、sentence-transformers 6.2.0、torchvision 0.23.0、Pillow 12.1.0、huggingface-hub 2.4.0、SQLAlchemy 2.0.43、pypdf 6.20.1、psycopg 3.2.9、pgvector Python 0.4.1、FastAPI 0.116.1、httpx 0.28.1；PostgreSQL 16.15、服务器 pgvector 0.8.7。PG 使用实际 Alembic `upgrade head` 至 `20261015_0002`，再准备 C token schema。

[native-model.json](native-model.json) 验证离线原生编码、token 维度/范数及官方平均 MaxSim 的数值一致性：最大误差 `1.0728836064011205e-7`，排序一致。该诊断使用本地 ignored helper；JSON 保存了实际命令，不将它视为已提交的产品入口。

## 实际命令与重放步骤

以下从上文 C worktree 执行。数据库 URL 中 `***` 是报告脱敏值，重放时替换为已授权本地数据库密码；端口 55432 和三个库属于 C 实测环境。`requirements-actual.txt` 是实际环境审计，含本机 wheel 和 editable 路径，不能直接当作跨机器的完整安装锁文件。

新机器可先创建 Python 3.11 虚拟环境并安装仓库 `.[dev,embeddings]`，按上述依赖版本核对 CPU wheel。标准准备命令如下，是重放操作说明：

```powershell
python -m venv .venv-pplx
.\.venv-pplx\Scripts\python.exe -m pip install -e ".[dev,embeddings]"
.\.venv-pplx\Scripts\python.exe -m scripts.search_tools download-model --model-path models/pplx-embed-v2-late-0.6b
```

首次实际网络下载来自 ignored `work/download_pplx_model.py`，读取官方固定 revision 的 14 个文件，16 路、16 MiB Range，总计 **2,397,842,839 字节**，进程成功退出，文件校验见 [model-download.json](model-download.json)。长会话的完整启动参数及解释器路径未保留，这是首次下载的证据限制，不能声称首次网络下载由上述标准 CLI 完成。

产品 `download-model` 的本轮实际验证是：将官方文件硬链接到隔离 probe，不复制 manifest，使用空 HF 缓存且显式断网，由产品命令重新生成 manifest 并核对全部 14 个固定哈希，返回 0，源文件与源 manifest 不变；probe 随后清理。实际命令和全部环境参数见 [model-preparation.json](model-preparation.json)：

```powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$env:HF_HOME = 'D:\HKUST AIE\MAIE6000C\MAIE6000C-starter-TEAM_11\tmp\c-team-pdf-evaluation\work\c-model-preparation-probe-qrjkupua\.hf-home'
.\.venv-pplx\Scripts\python.exe -m scripts.search_tools download-model --model-path "D:\HKUST AIE\MAIE6000C\MAIE6000C-starter-TEAM_11\tmp\c-team-pdf-evaluation\work\c-model-preparation-probe-qrjkupua"
```

这段 probe 环境仅适用于已暂存官方文件的检查，不用于首次联网准备。正常本地评估使用已验证的 `models/pplx-embed-v2-late-0.6b`。以下 PDF 与运行验证命令均实际执行，完整 argv 保存在对应 JSON：

```powershell
.\.venv-pplx\Scripts\python.exe -m scripts.evaluate_team_pdf --database-url postgresql+psycopg://postgres:***@127.0.0.1:55432/team11_c_pdf --backend local --output submissions/week07/evidence/C/20261030-pplx/postgres-local.json
.\.venv-pplx\Scripts\python.exe -m scripts.evaluate_team_pdf --database-url sqlite:///work/team-pdf-clean.db --backend local --output submissions/week07/evidence/C/20261030-pplx/sqlite-local.json
.\.venv-pplx\Scripts\python.exe -m scripts.evaluate_team_pdf --database-url postgresql+psycopg://postgres:***@127.0.0.1:55432/team11_c_runtime --backend off --output submissions/week07/evidence/C/20261030-pplx/postgres-runtime-before.json
.\.venv-pplx\Scripts\python.exe -m scripts.verify_team_search_runtime --database-url postgresql+psycopg://postgres:***@127.0.0.1:55432/team11_c_runtime --evaluation submissions/week07/evidence/C/20261030-pplx/postgres-runtime-before.json --model-path models/pplx-embed-v2-late-0.6b --timeout 10 --output submissions/week07/evidence/C/20261030-pplx/http-runtime.json
```

两个 local PDF 评估均已完整执行，但语义 3/5 未达到候选 4/5，质量门返回码为 1。off 初始评估同样预期返回 1：关键词 5/5，语义/混合各 0/5，token 索引为 0。它们的 `status=evaluated`，不是进程未完成；跨报告一致性审计检查执行状态与质量状态，结果为通过、diagnostics 为空，见 [cross-run-diagnostics.json](cross-run-diagnostics.json)。

运行验证内实际成功的首条补向量命令如下。45524 是当次临时 AI 端口，手工恢复时改为当前服务 URL；其余 11 个版本的实际命令同样保存在 HTTP JSON：

```powershell
.\.venv-pplx\Scripts\python.exe -m scripts.search_tools index --database-url postgresql+psycopg://postgres:***@127.0.0.1:55432/team11_c_runtime --version-id 214199c2-c5db-4e77-b79b-76adec46682b --backend http --ai-url http://127.0.0.1:45524 --timeout 10.0
```

正常应用库已有共享表但缺 C token 表时，可先运行下面的产品操作命令；这是交接步骤，未声称本轮单独执行过此 argv，PDF runner 已完成等效 schema 准备：

```powershell
.\.venv-pplx\Scripts\python.exe -m scripts.search_tools prepare-token-index --database-url postgresql+psycopg://postgres:***@127.0.0.1:55432/team11_c_runtime
```

实际测试命令如下，执行环境、源码前后哈希、JUnit 来源及返回码见 [pytest-run.json](pytest-run.json)：

```powershell
$env:SEARCH_TEST_DATABASE_URL = 'postgresql+psycopg://postgres:***@127.0.0.1:55432/team11_c_pdf'
.\.venv-pplx\Scripts\python.exe -m pytest -q tests/unit tests/integration --junitxml="D:\HKUST AIE\MAIE6000C\MAIE6000C-starter-TEAM_11\tmp\c-team-pdf-evaluation\submissions\week07\evidence\C\20261030-pplx\pytest-results.xml"
```

JUnit 记录 **376 用例，374 passed、2 skipped、0 failures、0 errors**，用时约 71.798 秒。5 个 PostgreSQL 搜索用例全部执行；两个 skip 是 Windows 创建 symlink 权限不足的扫描用例，分别验证目录 symlink 不跟随和根 symlink 越界拒绝。JUnit SHA-256 为 `8ae3fe45b9ebeb72a0a30993625707774f6aa2aafb8b489dcb3a80b7768aa102`。

另已实际运行并通过 `.\.venv-pplx\Scripts\python.exe -m ruff check .` 和 `.\.venv-pplx\Scripts\python.exe -m pip check`。

## 旧模型清理与证据保留

[model-removal.json](model-removal.json) 记录仅在 C 隔离工作区及 C 专属评估库清理旧 E5：权重目录 7 文件 / 492,795,388 字节，旧下载分段缓存 32 文件 / 470,644,946 字节，合计 **963,440,334 字节**。删除 60 条旧 derived dense embedding（PG PDF、PG runtime、SQLite clean 各 20），canonical source chunk 及全部源身份保持不变。权重及下载分段需重新下载才能恢复；历史证据、旧配置、冻结答案逐字节保留。未清理原始其他角色工作区或全局 HF 缓存。

## 给 A、B、D 的交接及未完成依赖

A 需准备固定 revision 的新模型、上述新运行时和可承受 CPU 内存/冷启动的环境；按 14 个文件哈希复制到离线备机。统一服务启动或 Worker 索引链需接入 C token schema 准备及当前版本补索引；共享 models、迁移和 API 主装配仍由 A 统筹。搜索继续使用相同的只读挂载、授权根、当前版本、文件存在性过滤。现有 Worker 可在 `IndexResult.embedding_error` 非空时标记 completed；completed 不等于向量就绪，重试语义需 A 统一处理。本轮已验证现有 index 恢复命令。

B/D 需确认唯一公共语料。D 的 `fixtures/normal/team-*` 与 B/Compose 回归语料 `tests/fixtures/regression` 的路径、内容哈希及页数不一致，不能按同名文件合并。B 人工 gold 审核保留 pending；如需主题语义质量评估，应审核新的语料及问题并另建 freeze，不能修改当前答案来改善分数。D 尚未冻结 C 的 4/5 门槛；混合检索也没有单独团队门槛。

还需对齐以下四条冻结分类差异，检索正常 PDF 分母不因这些差异改变：

| 文件 | 冻结 status / error | 实际 status / error |
| --- | --- | --- |
| `abnormal/corrupt.pdf` | `failed / CORRUPT_PDF` | `unsupported / unsupported_format` |
| `abnormal/empty.pdf` | `failed / EMPTY_FILE` | `unsupported / unsupported_format` |
| `abnormal/truncated.pdf` | `failed / TRUNCATED_PDF` | `unsupported / corrupt` |
| `unsupported/team11-unsupported-notes.docx` | `unsupported / UNSUPPORTED_FORMAT` | `unsupported / unsupported_format` |

未运行统一团队 Compose 下的 API→队列→Worker 全链路，也未在备机部署；B 人工审核未完成。当前精确 MaxSim 会加载 JSON token 矩阵，大语料的性能尚未验证。直接 local 推理没有 HTTP 超时，超时结论来自独立 HTTP 实测。当前语义候选门槛仍失败。云端回退、完整图谱、前端改造和专用恢复 UI/API 均不在本轮范围。

## 原始证据索引

| 文件 | 内容 |
| --- | --- |
| [summary.json](summary.json) | 机器可读汇总、逐题结果、历史对照、源状态与证据哈希 |
| [configuration.json](configuration.json) | 模型、固定 revision、14 个文件哈希及全部参数 |
| [postgres-local.json](postgres-local.json) / [sqlite-local.json](sqlite-local.json) | 正常扫描/解析/索引、15 次逐条 Top-3、版本/页码/chunk/原文与磁盘核验 |
| [postgres-runtime-before.json](postgres-runtime-before.json) | 独立恢复库，AI off 时的 0 token 索引基线 |
| [http-runtime.json](http-runtime.json) | 实际断开、超时、补向量、恢复及逐条 HTTP 证据 |
| [failure-analysis.json](failure-analysis.json) | S02/S04 各页精确 MaxSim、正确页 rank/分差与完整文件范围 |
| [native-model.json](native-model.json) | 原生编码、范数、官方平均 MaxSim 对齐 |
| [model-download.json](model-download.json) / [model-preparation.json](model-preparation.json) | 官方固定文件下载校验 / 产品 CLI 离线准备实测 |
| [model-removal.json](model-removal.json) | 旧模型、下载缓存、60 条旧向量清理及源身份保留 |
| [pytest-run.json](pytest-run.json) / [pytest-results.xml](pytest-results.xml) | 实际测试 argv、执行环境和 JUnit |
| [cross-run-diagnostics.json](cross-run-diagnostics.json) | 跨报告模型、冻结答案、Git/source provenance、执行完成状态一致性检查 |
| [requirements-actual.txt](requirements-actual.txt) | 运行环境实际依赖审计 |
