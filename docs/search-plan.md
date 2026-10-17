# C：检索、模型与评测

实现日期：2026-10-15；发布说明更新于 2026-10-16。C 的独立模块通过 `feat/c-search-model-evaluation` 分支供团队审阅；公共合同、真实 PDF 联调及团队封板仍待完成。发布范围和测试时效见 [分支审阅说明](../submissions/week07/C-branch-review.md)。

## 实现与边界

- `services/search/text.py`：NFKC 规范化、英文单词与连续中文双字切分；词不会跨标点拼接。
- `services/search/retrieval.py`：PostgreSQL 全文检索、pgvector 精确余弦查询、加权混合排序及按文件聚合。
- `services/search/embeddings.py`：本地多语言 E5 与内部 HTTP 客户端；运行时只读取本地模型。
- `services/search/indexing.py`：向量 Worker 处理函数；每批最多 16 段，所有批次成功后才发布向量，不自行提交事务。
- `services/search/evaluation.py`：冻结答案评测，文件和页码必须同时正确；降级结果不计为语义成功。
- `scripts/search_tools.py`：模型准备、迁移、样例导入、向量索引和评测命令。

扫描授权和公共队列分发归 A，PDF 解析及证据读取归 B，界面归 D。当前 C 分支尚无这些文件助手入口，C 提供独立可运行的导入适配器和向量处理函数。这里的 `source_*` 模型与迁移是供 A 整合的合同草案；合并前须核对 A/B 的最终字段，不能将 C 的样例导入描述为真实扫描/解析。复查时已发现远程 `w7-parsing` 分支包含 B 的实现，字段与迁移有实际差异，详见 [合同差异清单](search-contract-differences.md)。

## 本地模型合同

模型为 `intfloat/multilingual-e5-small`，固定 revision `614241f622f53c4eeff9890bdc4f31cfecc418b3`，模型标识为两者以 `@` 连接的完整字符串，向量维度为 384。模型采用 E5 的 `query: ` / `passage: ` 前缀、attention-mask mean pooling 与 L2 归一化，CPU 推理默认 4 线程。模型文件为固定 revision 的 safetensors 与 tokenizer 文件；准备脚本生成逐文件 SHA-256 清单，运行时验证清单并指定 `local_files_only=True`、`trust_remote_code=False`。

唯一联网下载入口是显式命令 `download-model`。搜索、索引和 AI 请求路径均不下载模型，不调用云端模型，不把文本传给公共 API。模型缓存位于 Git 忽略的 `models/multilingual-e5-small/`，需单独复制到备用设备。首次加载包含文件校验和模型初始化，应在演示前预热 `/embeddings`，避免首次请求触发 API 的 10 秒超时降级。模型使用方式受其原始模型许可证约束，项目不重新分发模型权重到 Git。

内部 `POST /embeddings` 输入：

```json
{"texts": ["Database backup instructions"], "kind": "passage"}
```

返回 `model`、`dimensions` 和 `vectors`。一次 1–16 段，每段 1–2000 字符；tokenizer 最多 512 token，超出会截断。解析方应提供短且带页码的块。索引现有长块时只嵌入前 2000 字符，原文本完整保留供关键词检索。查询最长 500 字符、最多 64 个去重检索词。向量须为 384 维有限数值且 L2 范数在 0.99–1.01 内，否则拒绝。

## 数据与索引

`source_files` 记录文件身份、路径、当前哈希及状态；`source_versions` 记录版本、哈希、当前标识及模型元信息；`source_chunks` 保存版本外键、块序号、原文本、起止页码、检索词及 `vector(384)`。版本号和块序号分别有唯一约束，每个文件最多一个当前版本。SQLite 使用 JSON 保存向量，供测试和本地开发使用。

PostgreSQL 对 `to_tsvector('simple', search_terms)` 建 GIN 索引。英文按完整词匹配；中文用双字词检索，支持没有中文分词插件的 PostgreSQL。短语和文件名命中提供额外分数。pgvector 使用 `<=>` 进行精确余弦距离计算；目前的小型演示语料不启用近似向量索引，不声称大规模检索性能。

搜索只读取文件/版本均 `ready`、当前版本且文件哈希与版本哈希相同的数据。授权、挂载有效性和磁盘原件核验由 A/B 的入口负责；搜索不打开磁盘文件，也不会把返回路径当成授权。A/B 的批量 SQL 写入若绕过 ORM 事件，必须显式填充规范化的 `search_text` 和 `search_terms`。

## 排序与返回

`keyword` 完全不依赖 AI。`semantic` 使用语义候选，`hybrid` 合并两个通道。关键词分数为去重词覆盖率 × 0.8、完整短语命中 +0.2、文件名命中 +0.25，最终限制到 0–1；语义分数为余弦相似度的非负部分。混合默认权重为关键词 0.65、语义 0.35，并除以权重和。它是可解释的加权排序，没有独立 cross-encoder reranker。

各通道先为每份文件选最佳块，再最多取 200 份文件，避免长文档挤占所有候选。合并后按分数排序、每文件只保留一个证据块，`top_k` 默认 10、最大 50。`total` 是有界候选池中的去重文件数，超过候选上限时不是整个语料的精确命中总数。返回文件、版本、块、页码、原文节选、理由以及三种分数。稳定排序优先同分块的原始序号，再用 ID 打破平局。

## 降级与失败隔离

- `EMBEDDING_ENABLED=false`：`ai_disabled`；AI 连接失败/503：`ai_unavailable`；超时：`ai_timeout`。
- 模型或维度不同：`embedding_model_mismatch`；向量格式错误：`invalid_embedding_response`。
- 没有兼容向量：`embeddings_not_ready`；部分块尚未向量化：`partial_embeddings`。

前几类失败将 `effective_mode` 切换为 `keyword`，返回 HTTP 200、`degraded=true` 与明确原因。部分向量可用时保留所请求的 hybrid/semantic 模式并标注 `partial_embeddings`；纯语义结果只包含已向量化的文件，混合模式仍包含关键词结果。语义评测遇到任何降级均不计为语义成功。模型校验清单结构损坏返回安全的 `local_model_unusable`，AI 接口响应 503，搜索通过 HTTP 客户端回退关键词。数据库不可用仍按实际错误失败，不会伪造为空结果。向量处理失败返回 `IndexResult.embedding_error`，基本文本和旧向量保留；A 的调度器负责记录错误、重试和事务。

## 评测解释

`fixtures/search/` 为手写合成资料，共 12 份文档、15 个带页码的块，查询为 5 关键词 + 5 语义。答案在首次 E5 评测前冻结，保留 JSON 哈希和逐项结果。关键词要求 Top-1 文件和页码正确；语义要求 Top-3 中至少一个结果的文件和页码同时正确，目标 4/5。

当前实际结果：关键词 5/5，语义 4/5，重复文件 0。`sem-2` 找到了账户手册但选到第 3 页，预期为第 1 页，所以计为失败。该结果未通过修改答案消除。样本很小，只能说明内部功能烟雾测试情况；团队真实 PDF 答案、UI 及证据链须由 B/D 再独立核对。

## Windows CMD 本地验证

在仓库根目录执行。仓库声明 Python 3.11；当前 Anaconda base 为 Python 3.13，已验证本地逻辑，Docker 使用声明的 3.11。

```cmd
python -m pip install -e ".[dev,embeddings]"
python -m scripts.search_tools download-model
python -m scripts.search_tools migrate
python -m scripts.search_tools seed
python -m scripts.search_tools evaluate
python -m scripts.verify_search_local
python -m scripts.verify_search_http
python -m pytest -q tests/unit tests/integration -m "not postgres"
python -m ruff check .
```

如果当前 base 的 Python 版本超出项目 `requires-python`，应切换到 Python 3.11 环境安装项目；不要使用 `--ignore-requires-python` 掩盖依赖约束。当前机器已有依赖后可直接运行后续验证命令。

PostgreSQL 版本可给命令追加 `--database-url postgresql+psycopg://postgres:postgres@127.0.0.1:55432/team11_c_verify`。该地址是本次独立验证容器的本地测试库，部署时替换为实际地址。运行 PostgreSQL 测试：

```cmd
python -c "import os,pytest; os.environ['SEARCH_TEST_DATABASE_URL']='postgresql+psycopg://postgres:postgres@127.0.0.1:55432/team11_c_verify'; raise SystemExit(pytest.main(['-q','tests/unit','tests/integration']))"
```

Compose 已切换 pgvector 镜像、把本地模型只读挂载到 AI，并在镜像安装 CPU 模型依赖。先准备模型与 `.env`，再启动：

```cmd
python -c "from pathlib import Path; p=Path('.env'); p.write_bytes(Path('.env.example').read_bytes()) if not p.exists() else None"
python -c "import subprocess; subprocess.run(['docker','compose','up','--build'],check=True)"
```

独立验证程序临时启动本机 API/AI/worker，使用空闲 loopback 端口；验证结束自动停止这些子进程。不会执行 Git 提交或远程操作。

完整测试（含真实 smoke 与 PostgreSQL），在独立测试数据库运行：

```cmd
python -m scripts.verify_search_http --database-url postgresql+psycopg://postgres:postgres@127.0.0.1:55432/team11_c_verify --pytest-output work/pytest-all.xml
```

复查已修正 starter 测试文件的误后缀，原有两项 API 测试可以正常收集。当前完整套件为 49 项，包含一项真实 HTTP smoke；不要把未启动服务时的 smoke skip 当成完整验收。
