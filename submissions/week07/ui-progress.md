# 角色 D 截至 10 月 19 日的代码与交付记录

## 10.19 本轮实际代码补齐（当前状态）

基线为 `Role_D` 的 `ed05fa4`，以下是本次未提交工作区实际修改。
当前状态覆盖 10.17-10.19 的 D 前端与材料；后文的“实施前盘点”只保留为历史记录。

### 对照 10.17-10.19 的实际交付

| 计划节点 | 本轮实现 | 当前边界 |
| --- | --- | --- |
| 10.17 搜索/证据与失败提示 | 内容搜索调用 `POST /search`；默认 keyword，可显式选 hybrid/semantic；展示实际模式、降级原因、匹配理由与非概率分数。搜索命中按 `GET /evidence/{chunk_id}` 打开，并校验文件/版本/页码/ordinal/路径；空结果、请求失败、源失效分开处理。 | D 消费者代码已完成；当前 API 缺证据/文件等装配，真实浏览器链路未验收。 |
| 10.18 M1 修复与记录 | 修复整数公共 Job ID、null 当前版本、presence_status 与小写来源拒绝；防止旧搜索覆盖新查询/新 Root；新增 M1 表和范围/责任人表。 | M1 仍未通过，不把合同截图算真实产品证据，未代签。 |
| 10.19 关系/复核与前半稿 | 新增 `/graph`、`/review` 页面，最多 20 条候选；person/project/topic、规则来源、页码、版本及候选/确认/纠正/拒绝可区分；复核前验证源文，带 expected_revision，服务器回执后才更新状态；冲突/不确定写入必须重读。README 第 1-5 节和六步演示脚本已补。 | 关系控件按冻结合同独立验证；真实关系读取/复核写库待 A/B 路由装配。页面存在不代表 M1 已批准增量。 |

### 代码入口

- `frontend/src/api/http-adapter.js`：搜索、chunk 证据、关系读取、复核提交和
  failed Job 重试；不因错误返回 Mock，也不自动重放写请求。
- `frontend/src/retry-job-control.jsx`：仅对 failed Job 显示重试；要求 HTTP 202
  且 Job/Root 身份不变、状态为 pending。被拒绝或结果不确定时先重读 Job/Root，
  再允许下一次人工提交。
- `frontend/src/app.jsx`、`lib/use-search.js`、`lib/search.js`：内容检索、目录筛选分离，
  有效模式与源证据、请求竞争隔离；真实 API UI 不再调用旧的文件证据列表提案。
- `frontend/src/relations-page.jsx`：关系页与复核页；纠正必须提供已存在 entity ID，
  没有造实体或修改原始文件。成功保存会同步状态筛选和 revision。候选引用在核验前
  明示未核验；来源核验遇到网络或 503 等错误时隐藏缓存引用，复核仍禁用。
- `frontend/src/mock/relations.json`：显式 `VITE_MOCK_SCENARIO=relations` 的独立合成样例，
  可从授权目录一路操作搜索、三类候选和确认/纠正/拒绝；纠正样例 ID 为
  `entity-replacement`。内存决定在刷新后重置，未改原 16 文件语料，不是解析或产品证据。
  本地启动方式见 `frontend/README.md`。
- `.gitattributes`、`scripts/restore_d_fixture_checkout.mjs`：对冻结 D 语料防止换行改写；
  恢复脚本先校验全部 HEAD 字节与冻结 SHA，再仅修 checkout 的 CRLF 变化。
  本次 17 文件被恢复；18 个目标文件（含未变者）与 HEAD 字节完全一致，未重冻答案。

### 本轮验证（不得扩张成产品验收）

- Node 合同测试本轮复跑 **55/55 通过**（`test_d_integration` 与
  `test_d_search_review` 合并运行，含 retry adapter 合同）。
- Vitest **21/21 通过**（3 个测试文件），其中 11 个 React 工作流测试覆盖重试冲突重读与防重复、
  旧请求隔离、真实回执前不确认、
  双提交、冲突重读、来源不匹配、来源读取 503 时隐藏缓存引用、空列表与端点错误。
- `npm run build` 生产构建通过（4,916 modules）；`node scripts/test_d_mock.mjs` 通过。
- `validate_d_fixtures.mjs`：16 文件、20 正常页校验通过；`validate_d_gold.py`：
  16 文件哈希及 10/10 真实 PDF 源位置通过。B 人工审核仍为 pending，检索质量未据此推断。
- `capture_d_1019.mjs` 本轮浏览器重放 **19 个场景通过、页面运行时错误 0**，
  包含搜索/证据、降级、空结果、503、失效证据、三种复核决定、409、缺关系端点、
  重扫、failed Job retry、来源读取 503 后引用隐藏及恢复、375/768/1024 宽度。
  已生成带水印的 retry、来源失败和恢复截图，并核对当前源码哈希。
- `capture_d_relations_mock.mjs` 本轮重放 5 个独立模拟场景，无 HTTP 拦截、
  无 API 请求、页面运行时错误 0。两份浏览器报告均明确 `product_acceptance: false`；
  只证明各自记录的消费者/模拟行为，不替代当前代码重放或真实服务验收。
- 后端模型/迁移/Worker 本轮未改；没有部署或重建数据库/容器，没有改写 `.env`。

本轮已刷新 [Node 原始输出](evidence/1019-D/node-tests.tap) 与
[Vitest JSON](evidence/1019-D/vitest-results.json)，数字与当前代码一致。
[构建与核验记录](evidence/1019-D/verification.md) 包含生产产物 SHA-256。
浏览器依赖已补入 `frontend/package.json` 与锁文件（`playwright-core@1.56.1`），
采用本机 Chrome 的独立无头会话，未访问用户已打开的浏览器。

验证命令：

```powershell
node --test scripts/test_d_integration.test.mjs scripts/test_d_search_review.test.mjs
node scripts/test_d_mock.mjs
node scripts/validate_d_fixtures.mjs
python scripts/validate_d_gold.py
cd frontend
npm test -- --run
npm run build
```

浏览器重放：`npm ci --ignore-scripts` 会安装固定版本的 `playwright-core`，不下载浏览器。
启动 API 模式本地前端，设置 `D_UI_URL` 后在 `frontend/` 运行
`npm run test:browser:contract`；显式关系 Mock 样例使用 `test:browser:mock`。
默认查找本机 Chrome，也可用 `D_BROWSER_EXECUTABLE` 指定已安装的 Chromium。
报告固定 `product_acceptance: false`。
旧 `capture_d_ui.mjs` 重跑输出已转到 `work/`，不再覆盖 10.16 历史截图。

### 文档与剩余依赖

已补：[Week07 前五节](README.md)、[六步脚本](demo-script.md)、[M1 检查表](m1-checklist.md)、
[范围/责任人记录](scope-decision.md)、[浏览器报告](evidence/1019-D/browser-contract-report.json)。
完整 12 页文字页纲见 [PPT 页纲](ppt-outline-D.md)，逐条完成审计见
[10.14-10.19 核查表](evidence/1019-D/completion-audit.md)。
其中真实数据链路、后端任务重试路由确认/装配、人工签认仍是未完成项；完整报告、最终 PPT/PDF、录像与
最终 release manifest 属于后续收口，未冒充今天已交付。

关系合同没有给 chunk ID，本轮使用 root+file 范围的 keyword search 定位页码，再读取
chunk 并核对完整 quote。无法定位时禁用复核；这受按文件去重搜索的限制，需 A/B 补
可直接定位证据的合同。复核成功响应暂消费 `200 {decision_revision}`，共享文档未指定
该封装，需 A/B 在路由装配时确认，不能当作已验证的真实后端响应。

## 10.19 实施前盘点（历史记录，已被上节更新）


本节以当前 `Role_D` 分支 `ed05fa4` 为准，补记排期中 10 月 17--19 日的
完成情况。`w7-integration-bootstrap` 上的记录单独标为历史集成分支证据，
不直接等同于当前分支已经交付。

### 按排期节点的判定

| 日期 / 排期要求 | 当前分支可核实的结果 | 判定 |
| --- | --- | --- |
| 10.17：接真实结果/证据接口，补齐错误状态和演示脚本 | API adapter、授权 202/Root/Job 校验、文件/证据字段校验、空集合/解析失败/源不可用/keyword-only 状态均已实现；但当前 API 仍只有 starter 路由、`/roots`、`/jobs/{整数}` 和 `/search`，缺少 D 页面实际调用的 `/mounts`、`/files`、`/evidence` 以及 retry 等完整产品接口。 | 部分完成。历史集成分支曾有 10.17 真实浏览器记录，但不在本分支 HEAD。 |
| 10.18：M1 关口验收 | 当前分支的 Node 契约测试 35/35、Vitest 9/9、API 模式生产构建通过；没有当前分支的真实 API/数据库/Worker 浏览器验收。Windows 工作区复跑固定语料和冻结答案校验时出现 SHA-256 不匹配（PDF/JSON 被 Git 自动换行为 CRLF），不能将旧的通过记录直接复用，也不能未经 B 确认重写冻结哈希。 | 未闭环，不判定 M1 通过。 |
| 10.19：关系/复核界面、提交文档前五节、更新演示脚本 | `scripts/demo_relation_review.py`、`services/parsing/graph.py` 和关系/复核迁移存在，可做后端逻辑演示；但前端 `Graph`、`Entities` 和 `Review` 仍明确显示 unavailable/placeholder，结果页仍是本地文件名过滤并标注 `not semantic search`。当前分支也没有完整的 `report.md`、Week07 README、最终 PPT/PDF、demo script 或 release manifest 收口提交。 | 未完成。 |

### 当前分支已经做到的部分

- 目录选择、扫描进度、文件列表和版本绑定证据查看三段前端流程可构建；
  API adapter 默认走真实 HTTP，Mock 需要显式选择，不会因请求错误静默回退。
- 16 个固定语料记录、12/3/1 状态模型、未知计数、重复扫描与旧版本证据隔离
  等规则已有适配器/状态测试和模拟契约测试覆盖。
- 当前复跑结果：`node --test scripts/test_d_integration.test.mjs` 为 35/35，
  `node scripts/test_d_mock.mjs` 通过，Vitest 为 9/9，`npm run build` 通过，
  `git diff --check` 通过。
- 关系模块的 Python 单元测试本次未能启动：当前解释器缺少 `fastapi` 依赖；因此
  本次复核不把关系/复核后端测试计为通过。
- `node scripts/validate_d_fixtures.mjs` 和 `python scripts/validate_d_gold.py`
  在本次 Windows checkout 分别因 fixture 文件和 gold/manifest 冻结 SHA 不匹配而
  失败；原因是仓库中的文本型 PDF/JSON 被 Git 自动转换为 CRLF。该问题应由版本
  化的换行/二进制属性修正或重新冻结流程解决，不能在 D 记录中伪装成 16 文件、
  10/10 当前复核已通过。

### 关系/复核工作的边界

当前仓库确实包含关系候选、证据和 append-only review revision guard 的解析模块，
也包含一个命令行演示脚本；这些只能证明后端代码/迁移的存在和可读性，不能证明
10.19 要求的浏览器关系/复核界面、HTTP 路由、真实数据库写入或截图已经完成。
同理，`w7-integration-bootstrap` 的 10.17 记录证明过一次真实集成路径（16/16、
12 searchable、4 unsupported，并打开过证据），但它属于另一分支，不能替代
`Role_D` 当前分支的收口证据。

### 截至 10.19 的结论与收口项

D 已完成 10.14--10.16 的前端契约、固定语料边界和模拟验证；10.17 的真实接线
与 10.18 的 M1 只达到“有历史集成证据、当前分支未闭环”；10.19 的关系/复核
界面和提交材料尚未完成。下一步必须在同一分支完成并留证：

1. 确认并接入 `/mounts`、`/files`、`/evidence`、搜索和 retry 的最终共享合同，
   用不拦截请求的浏览器流程重新跑 16 文件与异常状态。
2. 将搜索框从本地过滤改为真实 `POST /search`，或在提交材料中明确裁剪为
   keyword-only，并保留降级原因。
3. 决定并实现关系/复核 UI 的最小范围（候选关系、页码证据、confirm/correct/reject
   和 revision conflict），否则将其标成未实现而不在演示中宣称。
4. 补齐 `report.md`、Week07 README、D 的前五节材料、演示脚本/截图和 release
   manifest；重新做一次 M1 签字和版本哈希检查。

## 10 月 16 日历史记录（原文保留）

结论：D 侧真实 API 接线代码、文件阶段计数、四类状态处理、10 条答案冻结与源 PDF 页码检查已交付。用户补充授权后，前端依赖与锁文件、生产构建、9 项 Vitest、8 个浏览器契约场景及带水印截图均已完成，Docker 只读检查也已完成。**当日整体验收尚未完成**：A 的文件管理后端未进入当前仓库，B 未人工复核答案，仍无真实 API/数据库/Worker 联调证据。不能把单元测试和模拟接口截图当作产品链路已经通过。

## 当日任务对照

| 排期要求 | 已交付 | 验收状态 |
| --- | --- | --- |
| 授权和进度页接真实服务 | API 默认模式、同源 `/api` 代理、202/响应形状检查、读请求重试、提交防重复 | D 代码与适配器测试通过；真实服务待 A |
| 文件与异常计数，显示 12/3/1 | 独立读取 Root 的当前文件阶段计数；扫描完成后仍可继续处理；无计数显示未知 | 本地与浏览器契约测试通过；真实数据库计数待联调 |
| `ui-progress.md` 和真实联调截图 | 本记录、契约说明、测试原始输出和截图采集脚本 | 记录已交付；真实截图未生成 |
| 与 B 核对并冻结 10 条答案 | 5 关键词 + 5 描述式查询、中英混合、跨两个目录、固定文件/版本/页码/原文 | 自动源位置检查 10/10；B 人工复核待完成 |
| 四类 UI 状态及截图 | 空集合、解析失败、源不可用、keyword-only 分开显示；4 张对应截图均保留水印 | 浏览器契约场景及视觉检查通过；真实源/模型场景待联调 |

## 已实现的接线与边界

`frontend/src/api/http-adapter.js` 读取真实 HTTP 状态、Root/Job ID 和响应数据。请求错误不会自动换成演示 JSON。`frontend/src/api/adapter.js` 修复了原来直接构造 Mock 未传入数据的问题；只有显式选择 Mock 才会加载模拟适配器。

进度页分别读取 `GET /jobs/{job_id}` 和 `GET /roots/{root_id}`。Root 的 `file_counts` 是 D 侧消费字段提案，详见 `docs/frontend-integration-contract.md`，尚不是 A 已确认的共享合同。计数来源不明确时显示未知，不复用扫描 Job 的 100% 冒充处理就绪。扫描结束但文件仍在处理时继续轮询；解析失败和不支持的文件保留记录，因此 16 个记录不代表 16 个解析成功。

错误页不直接展示后端堆栈或原始 detail；超时不自动重放授权 POST。文件源不可用、过期、丢失、不可读或发生版本冲突时，隐藏缓存段落及全部证据行，并从本地段落过滤中排除失效内容；已知失效源不会再次请求证据。收到证据后还会对照当前文件的相对路径与已知总页数，拒绝路径不符或越界页码。刷新当前版本会清理旧证据，晚到的旧请求不会污染新 Root。重新读取挂载点会清空旧选择，避免已移除挂载点留下可提交的旧目录。结果输入框明确为本地过滤，不宣称语义检索。Graph、Review、Preview 和文件整理仍未实现。

前端 Compose 端口限制为 `127.0.0.1`；没有修改 A/B/C 所有的 Python 服务、公共模型、迁移和 Worker。未覆盖现有 `.env`：如果其中仍是 `FRONTEND_DATA_MODE=mock`，需要在授权范围内自行改为 API 模式并重建。`.gitignore` 只开放 D 的交付与 `frontend/src/lib`，保留其他提交目录的原忽略边界。

只读检查发现现有前端容器的健康检查将 `localhost` 解析为 `::1`，而 Nginx 只监听 IPv4；宿主机访问 `/health` 与 `/select` 均为 HTTP 200。已将仓库 Dockerfile 和 Compose 的前端健康检查改为 `127.0.0.1`，配置校验通过；**未启动、停止或重建任何容器，运行中容器仍使用旧配置**。现有容器的端口还绑定 `0.0.0.0/[::]:3000`，与仓库预期的本机绑定不同，后续获准重建时才会应用。详见 `evidence/1016-D/docker-readonly.md`。

## 冻结答案的证据等级

`gold-queries.json` 与 `gold-queries.freeze.json` 锁定答案文件及整个 `fixtures/manifest.json` 的 SHA-256；校验器只读，不自动重写答案或哈希。使用 pypdf 从真实 PDF 的指定页提取原文，验证了 10 个位置及 16 个文件哈希；不依赖 Mock 中虚构的 excerpt。

现有正常样本只包含编号和重复模板文本，描述式查询主要是编号/页面的换一种表述。它们可用于字段与页码定位冒烟测试，**不足以支撑真实主题检索质量、语义 Top-3 命中率或 W07 全链路验收**。5 条描述式查询不复用源文本英文关键词，但这不等于已经验证模型理解能力。B 的签名状态固定为 `pending`；未冒充组员确认。若 B 换用更有内容的语料，应另立版本、重新人工确认，不能为了检索分数改本版答案。

还有一项语料缺口：当前 3 个异常文件是空文件、截断 PDF、损坏 PDF，不是当天 B 计划中的加密、损坏、无文字层三类。D 未替换源样本或伪造后端错误状态；需要 B 提供相应用例后重新冻结语料。

## 实际运行的验证

从仓库根目录运行：

```powershell
node --test scripts/test_d_integration.test.mjs
node scripts/test_d_mock.mjs
node scripts/validate_d_fixtures.mjs
python scripts/validate_d_gold.py
git diff --check
```

新增契约/进度测试 **35/35 通过**；原有 Mock 校验通过；固定语料 **16 文件、20 页、12/3/1、SHA-256 校验通过**；固定答案 **10/10 原文位置通过**。

用户补充授权后，在本次安装进程中停用失效的 `127.0.0.1:7897` 代理，直连 npm 官方仓库安装了 155 个包并生成 `frontend/package-lock.json`，未修改全局 npm/系统代理。生产 API 模式的 `npm run build` 通过（4910 modules）；Vitest 的 2 个文件、**9/9 测试通过**，范围是适配器与状态辅助函数，不是 React 组件测试。

对 `127.0.0.1:4173` 的生产构建预览运行了独立无头浏览器：**8/8 契约场景通过**，包含授权、12/3/1 进度、四类状态、未知计数、HTTP 503 错误；页面运行时异常 0，授权 POST 仅 1 次。已知源失效/零页不取证据；keyword-only 仍能显示版本证据。8 张 1440×1000 PNG 均带 `HTTP CONTRACT FIXTURE — NOT PRODUCT EVIDENCE` 水印，并已逐张视觉检查。结果页截图使用前端文件名过滤，以同时完整展示选中文件与检查器，不是语义搜索结果。

所有截图均拦截 `/api` 并返回模拟接口数据，因此报告固定为 `product_acceptance: false`。原始报告、截图索引和构建产物哈希见 `evidence/1016-D/`。只读 Docker 检查显示前端 `running/unhealthy`，API、DB、AI、Worker 均为 `created` 未运行；未对后端执行写操作。

仍未完成：真实 API/Worker/数据库联调、真实 AI 停机降级、B 人工签核及真实服务截图。早前的依赖/审批阻塞属于历史记录，本轮已解除，不能继续列为当前阻塞。

## 补齐真实验收所需交接

1. A 提供文件管理接口并确认 D 消费合同，尤其 Root 当前版本的 `file_counts` 和真实 Job 标识。不能将 starter 的 `GET /jobs/{整数}` 当作产品合同。
2. B 核对 10 条答案的文件、版本和页码，提供具备主题内容及当天三类异常的最终语料；留下具名审核记录。若改动语料，建立新的冻结版本。
3. 获准启动/重建服务后应用健康检查及本机端口绑定修正；本轮授权仅含 Docker 只读检查，未执行这些部署操作。启动 starter 服务本身也不能补齐尚未实现的产品接口。
4. 用不含请求拦截的独立流程连接真实服务跑首次扫描，取得数据库有 16 记录及 12/3/1 计数的证据，拍真实授权/进度截图。不要把模拟截图脚本误用作真实验收。真实源不可用、模型降级、重复扫描和版本变化分别由 A/B/C 的真实服务验证，D 收口记录。

本记录保留这些缺口，不宣称 10.16 已全部通过或 W07 已达标。
