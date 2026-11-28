# 10.19 当前工作区核验

基线：`Role_D` / `ed05fa4b0c9665032fd069bdd46a22521ea69b1c` 加当前未提交修改。
本记录核验 D 消费者代码，不代表真实 API、数据库、Worker 或 M1 验收通过。

| 检查 | 实际结果 |
| --- | --- |
| `node --test scripts/test_d_integration.test.mjs scripts/test_d_search_review.test.mjs` | 55/55；原始输出见 [node-tests.tap](node-tests.tap) |
| `npm test -- --run`（frontend） | 21/21，3 文件；其中 11 项 React 工作流；见 [vitest-results.json](vitest-results.json) |
| `npm run build`（frontend） | 通过，4,916 modules，默认 API 模式 |
| `node scripts/test_d_mock.mjs` | 通过 |
| `node scripts/validate_d_fixtures.mjs` | 16 文件、20 正常 PDF 页通过 |
| `python scripts/validate_d_gold.py --report submissions/week07/evidence/1019-D/gold-source-check.json` | 16 文件哈希、10/10 PDF 源位置通过；B 人工审核 pending，检索质量未评测 |
| `node scripts/capture_d_1019.mjs`，API 生产预览 `127.0.0.1:4173` | 19/19 HTTP 合同浏览器场景，页面错误 0 |
| `node scripts/capture_d_relations_mock.mjs`，显式 relations Mock `127.0.0.1:5190` | 5/5，无 HTTP 拦截、API 请求 0、页面错误 0 |

最新补丁明确区分未核验/已核验候选引用，且在来源读取失败时隐藏缓存引用；
React 回归覆盖 HTTP 503 下引用隐藏、复核禁用且不提交决定。

Vitest 和构建最初因沙箱拒绝 Vite 临时配置文件写入而无法启动；经批准使用所需
文件系统权限后通过。另已安装并锁定 `playwright-core@1.56.1`，使用本机 Chrome
155.0.8059.82 的独立无头配置验证 UI；没有下载浏览器或修改后端/全局代理设置。

生产产物 SHA-256（位于被忽略的 `frontend/dist/`，并非 release manifest）：

| 产物 | SHA-256 |
| --- | --- |
| `index.html` | `d31149fba77b28a7fabe6088ae8e611872e836eb170c9f57d2b3cc30eedb26b2` |
| `assets/index-BprOwqTF.css` | `bb15e3912e0d76b60e2f02a7c68c89bcf2faf3bccb7d1868ff375dd1c0e88791` |
| `assets/index-CtyrbQDj.js` | `cd45e8a95f9c56ace1e1d873dcc6001a5b0b4e1f0b58e388456b042d167d0145` |

两份浏览器报告均记录当前源文件哈希，覆盖 failed Job retry 与本次引用补丁的
失败/恢复路径。已目视检查新来源失败、重试、三种决定及移动端截图。Mock 首次冷启动
导航曾超时，确认同一服务仍在运行后将导航等待改为 DOM 就绪并单独允许 30 秒，重跑通过。
报告和截图均不构成真实产品证据，`product_acceptance: false`。

真实首次导入、重复扫描、异常混入、失败任务恢复、复核写库及成员签认仍见
[M1 检查表](../../m1-checklist.md) 与 [范围记录](../../scope-decision.md)。
本轮运行态只读复查：8000 API、3000 现有入口均连接被拒绝；`docker ps -a` 在获准
访问后仍报 Docker Desktop Linux Engine 管道不存在。未用静态预览或 Mock 顶替真实服务。
