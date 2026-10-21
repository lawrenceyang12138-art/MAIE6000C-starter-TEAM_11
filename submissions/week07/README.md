# Team 11 - Week07 提交草稿（2026-10-19）

本稿按课程模板补齐第 1-5 节。它是 D 的集成说明初稿，不是最终提交或四人签认。
检查基线为 `Role_D` 的 `ed05fa4` 加本次工作区修改；未创建 checkpoint tag。
角色边界：A 负责装配/API/扫描，B 负责解析/关系，C 负责检索，D 负责 UI/验收与材料。

## 1. What currently works

D 前端已有目录选择、异步进度、文件列表、内容搜索和源证据查看流程。
内容搜索现在调用共享 `POST /search`，默认关键词，可显式选择混合或语义模式；
不会用浏览器过滤冒充检索。搜索结果展示文件、版本、页码、片段、匹配理由与排序分数，
实际降级时显示请求/有效模式。证据改为按 `chunk_id` 获取并校验身份。

关系页与复核页已实现共享接口消费者：每版本最多 20 条，区分候选、确认、纠正、拒绝；
复核先验证来源，提交带 expected_revision，冲突后必须重读。以上均有自动测试，
但当前仓库后端路由尚未装配齐，不能称为完整真实产品链路已工作。

证据：[D 进度](ui-progress.md)、[消费者合同](../../docs/frontend-integration-contract.md)、
[浏览器合同报告](evidence/1019-D/browser-contract-report.json)。

## 2. Live demo sequence

六步详见 [演示脚本](demo-script.md)。真实演示先决条件为 A/B/C 的路由、Worker、
数据库、冻结语料和模型版本就绪；合同截图始终保留水印。

1. 选择服务返回的只读挂载与相对目录。
2. 创建授权，核对 HTTP 202、Root/Job 与异步计数。
3. 在结果页提交关键词，打开对应 chunk 的原文，核对版本/页码。
4. 演示异常、空结果和失效来源；按显式按钮重试读取。
5. 在模型可用/不可用时分别检查有效搜索模式与降级原因。
6. M1 放行后展示有来源的候选关系，执行确认/纠正/拒绝与 revision 冲突。

## 3. Current implementation status

### Implemented

- D：HTTP adapter、搜索/证据 UI、关系/复核界面、并发与重复提交保护、测试。
- 冻结 16 文件及 10 查询源位置校验；Windows 换行损坏已恢复为原冻结字节，未改哈希。
- C 的 `/search` 已存在于当前后端；B 的解析、关系读取与追加复核函数存在。

### Partially implemented

- HTTP 产品装配：当前后端的授权仍为嵌套 root/job，文件及关系/证据路由未齐。
- M1：未取得当前分支真实数据库/Worker 下的三场景证据与四人签认。
- 关系界面：合同测试通过；真实读取、复核写库和成功响应封装仍待 A/B 联调确认。
- 查询答案：自动源位置核验通过，B 人工复核状态仍为 pending；不代表语义质量通过。

### Not yet implemented / verified

- 真实 PDF 首次/重复/混入异常的整条浏览器验收；真实失败任务重试接口接线。
- 当前分支的 5/5 检索、10/10 端到端证据与语义 Top-3 实测签认。
- 文件移动/整理/撤销、完整自动知识图谱、OCR；这些不在本轮 D 增量实现范围。
- 最终演示视频、12 页 PPT/PDF、第二设备、最终 release manifest 与成员声明。

## 4. Architecture status

实际前端是 React/Vite，HTTP adapter 通过同源 `/api` 访问 FastAPI；Mock 为显式构建选项。
前端只提交授权请求、读取服务状态、发搜索及复核请求，不在浏览器运行解析或生成版本状态。
目标后端为 A 扫描/派发、B PDF/chunk/关系、C 搜索侧索引，共用 PostgreSQL canonical models。
现有后端仍保留 starter case/job 路径，因此不能从组件存在推断文件 Job 已正确派发。

相对原设计，本轮限定本地只读源、文本 PDF、单 Worker 和小规模候选关系；不引入远程模型。
共同接口与职责见 [共享合同](../../docs/team11-w7-shared-contract.md)，UI 的暂定复核成功封装
与关系 quote 定位限制见 [D 消费者合同](../../docs/frontend-integration-contract.md)。

## 5. Current evidence of integration

| 边界 | 当前证据 | 能证明的范围 |
| --- | --- | --- |
| DB write path | `services/parsing/persist.py`、`graph.py` 与迁移 | 持久化/追加复核代码存在；本轮未验证真实复核写库 |
| API path | `/search` 后端 + D adapter；55 项 Node 契约测试 | 请求/校验及错误行为；不证明缺失路由已经存在 |
| worker path | 现有 Worker 与分发模块 | 当前 D 工作未改派发；M1 扫描到检索仍待真实验证 |
| AI path | [C 交接](../../docs/search-integration-handoff.md) + D 降级显示测试 | C 的已有能力和 UI 消费行为；不替代当前现场停 AI 试验 |
| operational signal | `health/metrics` 既有路由；D 显示未知/失败状态 | 前端没有伪造健康就绪；本轮未部署服务 |

10.19 的浏览器报告明确标为 `product_acceptance: false`。真实验收缺口与责任人见
[M1 检查表](m1-checklist.md) 和 [范围记录](scope-decision.md)。第 6-10 节和最终材料按
10.20-10.23 排期继续收口；本稿不冒充完整提交。
