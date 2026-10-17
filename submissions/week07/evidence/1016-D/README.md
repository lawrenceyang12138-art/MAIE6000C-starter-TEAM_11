# 10 月 16 日角色 D 证据索引

本目录收录实际运行的检查输出及 **8 张已视觉检查的模拟契约截图**。生产构建、9 项 Vitest、35 项 Node 测试和 8 个浏览器场景通过。**真实 API/数据库/Worker 联调尚未完成**；截图均带 NOT PRODUCT EVIDENCE 水印，不可当作真实服务验收。

| 文件 | 证据范围 | 不证明什么 |
| --- | --- | --- |
| `adapter-tests.tap` | Node 内置测试的原始结果，35 项契约/进度/源证据边界测试 | 非 HTTP 实际服务、非组件/浏览器测试 |
| `gold-source-check.json` | 从源 PDF 提取并校验 10 个页码位置，核验整个语料哈希 | 非检索命中率、非 B 的人工签核 |
| `vitest-report.json` | 2 个测试文件、9 个适配器/辅助函数测试通过 | 非 React 组件测试、非真实服务 |
| `browser-contract-report.json` | 8 个浏览器场景、0 页面运行时异常、1 次授权 POST | 所有 `/api` 被模拟；`product_acceptance: false` |
| `build-verification.md` | API 模式生产构建结果、锁文件与产物哈希 | 非已部署容器的版本确认 |
| `docker-readonly.md` | 容器状态、健康探针原因及宿主机只读 HTTP 检查 | 没有启动/重建服务、没有验证数据库内容 |
| `verification.md` | 命令结果、视觉检查范围及历史环境阻塞处理 | 非产品验收签字 |

## 截图索引

| 场景 | 截图 | 可观察结果 |
| --- | --- | --- |
| 授权 | [authorization-contract.png](authorization-contract.png) | 配置挂载点及相对目录，无绝对宿主路径 |
| 进度 | [progress-contract-12-3-1.png](progress-contract-12-3-1.png) | 16 总数、12 可检索、3 失败、1 不支持；扫描与文件阶段分离 |
| 空集合 | [state-empty-contract.png](state-empty-contract.png) | 正常空响应，不是接口错误 |
| 解析失败 | [state-failed-contract.png](state-failed-contract.png) | EMPTY_FILE、保留文件记录、无页证据 |
| 源不可用 | [state-source-unavailable-contract.png](state-source-unavailable-contract.png) | 隐藏缓存段落与证据，不请求已知失效源 |
| keyword-only | [state-keyword-only-contract.png](state-keyword-only-contract.png) | 显式降级标记，版本绑定关键词证据仍可见 |
| 未知计数 | [state-unknown-counts-contract.png](state-unknown-counts-contract.png) | 破折号，无进度条，不将扫描完成冒充就绪 |
| 接口错误 | [state-api-error-contract.png](state-api-error-contract.png) | 安全的 HTTP 503 提示，禁用授权，不静默回退 Mock |

结果页截图使用本地文件名过滤，非语义检索结果。验证目标是 API 模式的本地生产构建预览，不是现有 Docker 容器；浏览器脚本依旧拦截所有 `/api`。真实联调截图必须另取并注明服务版本，不能删除水印冒充真实运行。
