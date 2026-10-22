# D 角色 10.19 验证记录

本目录证明前端消费者与显式模拟样例的行为，不是 API/数据库/Worker 的真实产品验收。
代码基线为 `Role_D` 的 `ed05fa4` 加未提交工作区修改；浏览器报告记录了受测源码 SHA-256。

| 记录 | 结果与边界 |
| --- | --- |
| [Node 报告](node-tests.tap) | 最新复跑 55/55，通过输出已刷新 |
| [Vitest 报告](vitest-results.json) | 最新复跑 21/21，含 11 项 React 工作流；已刷新 |
| [当前核验记录](verification.md) | 生产构建、Mock、固定语料核验与构建产物哈希 |
| [逐项完成审计](completion-audit.md) | 10.14-10.19 D 的交付与真实联调缺口 |
| [API 消费者浏览器报告](browser-contract-report.json) | 19 场景通过，含重扫、failed Job retry、来源 503 与恢复；固定 HTTP 响应；`product_acceptance: false` |
| [独立 Mock 浏览器报告](browser-mock-relations-report.json) | 5 场景通过，无 HTTP 拦截，无 API 请求；`product_acceptance: false` |
| [冻结答案原文校验](gold-source-check.json) | 16 文件哈希、10/10 PDF 源位置；B 人工复核 pending，未运行检索质量评测 |

两份浏览器报告均已重跑，并记录当前受测源码 SHA-256；这些哈希对应基线 `ed05fa4`，本次评审修复发生在其后。
截图均带模拟/合同水印，但**未纳入版本库**（32 张共 5.9 MB，见 `.gitignore`）：新增的
`retry-job-accepted.png`、`review-source-unavailable.png`、`review-source-recovered.png`
可用 `node scripts/capture_d_1019.mjs` 在本地重新生成。当前生产构建、fixture 与 gold 校验均通过；具体重放命令与样例启动步骤见
[前端说明](../../../../frontend/README.md)。

尚未满足的真实验收项、责任人与接口依赖见 [M1 检查表](../../m1-checklist.md)、
[范围决定](../../scope-decision.md) 和 [D 当前进度](../../ui-progress.md)。
