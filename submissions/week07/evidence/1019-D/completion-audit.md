# D 10.14-10.19 逐项完成审计

依据用户给定排期的第 4-9 页任务卡。核查基线：`Role_D` / `ed05fa4` 加当前工作区。
“代码已实现”只说明 D 消费者或显式模拟样例；真实集成要求独立判断。

| 日期 / D 要求 | 当前可检查产物与验证 | 结论 |
| --- | --- | --- |
| 10.14：16 文件、manifest、至少 2 子目录 | fixtures 清单 12/3/1，16 哈希、20 正常页检查通过 | 完成；异常类型与 10.16 B 计划存在差异，未擅换冻结语料 |
| 10.14：3 个界面骨架、12 场景、12 页 PPT 页纲 | select/scan/results；ui-acceptance 历史 12 场景及当前增量；完整 12 页文字页纲 | 完成 D 初稿；最终 PPT/PDF 属后续日期 |
| 10.15：授权、进度、结果/证据可操作 | app、HTTP/Mock adapter、55 Node 与 21 Vitest；独立 Mock 从授权到证据通过 | D 完成；真实后端接线未闭环 |
| 10.16：授权/进度切真实服务、12/3/1 截图 | 默认 API、严格 202/ID/计数；合同截图 | 部分完成；当前分支缺真实文件管理装配，未有真实截图 |
| 10.16：10 答案冻结及与 B 核对、四类状态 | 冻结 hash 与 10/10 PDF 源位置通过；空/解析失败/来源不可用/keyword-only 独立显示 | 自动检查完成；B 人工审核 pending，非检索质量证据 |
| 10.17：搜索/证据/失败重试操作 | POST search、按 chunk 证据、显式 Job retry/rescan；当前 19 浏览器合同场景通过 | D 代码完成；真实接口/Worker 恢复未验证 |
| 10.17：600 字六步脚本与 10.18 验收表 | demo-script 六步和前置条件；m1-checklist 三场景 | 文档完成；真实流程截图未完成 |
| 10.18：干净库三种真实浏览器场景 | checklist 各行明确未运行；无伪造任务 ID、计数或签名 | 未完成，待 A/B/C 路由、Worker、数据库和语料 |
| 10.18：复验修复、范围与责任人 | scope-decision、D 修复测试和当前进度 | D 修复与记录完成；四人继续/裁剪决定未签认 |
| 10.19：关系/复核各一页，候选/确认/拒绝可分 | graph/review，三实体类型、来源/版本/页码、三类决定、revision guard；19 HTTP 合同 + 5 Mock 浏览器场景 | D 完成冻结合同消费者；真实 B 候选未接齐 |
| 10.19：接真实关系读取、README 1-5、六步脚本修订 | adapter 调用 canonical relations/reviews；README 与 demo-script 已填充 | 文档/消费者完成；真实关系路由/写库仍缺 |

本轮代码增量还包含来源读取失败隐藏缓存引用、明确未核验标签、来源恢复与任务重试的
浏览器验证，以及固定 playwright-core 依赖和可复现 npm 命令。

## 当前依赖的直接证据

`services/api/app/main.py` 当前仅装配 health/metrics、starter cases/jobs、search、roots；
创建 Root 返回嵌套 root/job，未装配 mount/directory/files/evidence/relations/reviews/retry。
`services/parsing/graph.py` 有关系读取和追加复核函数，但函数存在不等于 HTTP 已接通。
另一分支 `w7-integration-bootstrap` 的历史集成不等于本分支通过。

本轮只读运行态检查：`127.0.0.1:8000/openapi.json` 与
`127.0.0.1:3000/api/openapi.json` 均连接被拒绝；经所需权限重试 `docker ps -a`
后仍报告 Docker Desktop Linux Engine 命名管道不存在。未启动或重建 Docker 服务。
本轮启动的 4173 API 模式静态预览、5190 合成 Mock 服务不能替代这些真实后端。

真实浏览器三场景、真实关系复核写库、B 具名审核与四人 M1 签认仍未完成。
计划规定 D 不代写后端和不以模拟替代真实验收；故保留阻断，不将本次代码完成等同于
全部 10.19 产品进度通过。待接口进入当前集成基线后，用 [六步脚本](../../demo-script.md)
做不拦截请求的复验。无需重写当前 D 前端或重新冻结旧答案。
