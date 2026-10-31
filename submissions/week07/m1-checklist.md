# M1 检查表：2026-10-31 集成复核

目标分支：`feat/c-team-pdf-evaluation`；代码检查基线：`0e3d715`。
本轮实现与自动验收已完成，18/18 门槛通过。完整命令、工作树身份和原始结果见
[W7 验收矩阵](../../docs/w7-acceptance.md) 与
[本轮证据](evidence/20261031-w7/README.md)。人工签认单独记录。

## 三个真实场景

| 场景 | 放行要求 | 本轮状态 |
| --- | --- | --- |
| 首次导入 | 干净验收库，跨子目录正常 PDF；真实 UI 授权 → API → Worker → 搜索 → 原文；保存 root/job/chunk IDs 与截图 | 通过：`clean-database-before.json` 初始 roots/files/jobs 均 0；`frontend-live-clean/` 3/3，AI 禁用时单次关键词搜索即可打开原文 |
| 重复扫描 | 文件、版本、chunk、索引及活跃任务不重复；相同内容身份保持；源证据仍可读 | 通过：`http-db-final.json` 比较全部 UUID 集合，仅多一个 scan job，extract/embed 无新增；真实浏览器重扫通过 |
| 异常混入 | 正常文件继续完成；损坏、加密、无文字层及不支持格式有真实小写原因；无伪造文本；正常源证据可读 | 通过：`frontend-live-mixed/` 6/6；16 文件/16 版本/30 chunks，12 ready、4 unsupported，真实 corrupt/encrypted/no_text_layer/unsupported_format |

## 配套放行项

| 项目 | 验收要求 | 本轮状态 |
| --- | --- | --- |
| 关键词和源定位 | 历史 M1 目标关键词 5/5、冻结位置 10/10；证据与当前版本和源字节一致 | 通过：固定 Marker Top-1 5/5；`gold-source-checks.json` 冻结位置 10/10、hash 16/16；独立 PyMuPDF 物理页核对 30/30 chunks |
| 真模型与降级 | 实际本地 semantic/hybrid；AI 断连/超时显示 requested/effective mode 和原因；关键词和证据可用 | 通过：`model-modes.json` 真模型 ready/disconnected/restored；断连全过程停止 AI；超时和 UI 降级合同在自动测试中通过，未声称真实 UI 超时实验 |
| 关系和复核 | 自动 person/project/topic；直接 chunk 证据；confirm/correct/reject 追加历史；陈旧 revision 409 | 通过：真实 mixed 浏览器三决策与刷新持久化；HTTP/DB 核对 revision、append-only、409；证据直接取 chunk |
| 显式恢复 | 真实失败任务恢复后 retry 返回同一 job 的 202/pending；attempts 保留 | 通过：`backend-scenarios.json` job 71 源副本丢失后失败，恢复后重扫不隐式重试；显式 HTTP retry 同 job 完成、attempts 1→2、唯一 embed 73；UI receipt 合同通过 |
| 请求和路径边界 | 至少六种危险输入拒绝；本地 Host/Origin、越界路径与授权检查 | 通过：`runtime-safety-pages.json` 八类请求拒绝、DB 无写，102 检查/0 失败；Linux 真 symlink/FIFO 测试通过 |
| AI 独立启动 | AI 不能启动时 API/Worker、关键词和源证据仍可用 | 通过：初次无 AI 冷启动 HTTP/DB 202/0；空数据库浏览器在 AI 禁用下完成首次全流程 |
| 持久性和只读 | 正常重启后数据和复核仍可读；源文件前后 SHA-256 变化为零 | 通过：`restart.json` DB/API/Worker/frontend 换容器后 12 表摘要一致、三份源证据仍可读；17 原件 hash/size 不变；source mounts 只读 |
| 分支检查 | Ruff、Python/真实 PostgreSQL、Node/Vitest/build；记录镜像/版本和所有跳过原因 | 通过：最终 Linux 744 passed/0 skipped、Ruff clean；Vitest 56、Node 56、build/fixture/mock passed。镜像和版本见 `identity.json`；Windows 历史两项平台跳过均已在 Linux 执行 |

语义 4/5 是 C 早期候选阈值，未经团队冻结。页导航辅助结果与纯模型结果分别
报告；源定位验证不等同于语义质量或 B 的人工审阅。

## 历史证据与已关闭阻断

2026-10-19 的 Role_D 检查曾将三个真实场景记录为未运行。
`evidence/1019-D/browser-contract-report.json` 的 `product_acceptance` 为 false。
这些原始报告和截图脚本保留历史含义，不能自动转换为本轮产品验收。

此后 API 路由已装配；B 的提取路径已自动存候选关系；`chunk_id` 已直接指向
证据 API；复核成功响应已在共享合同明确为 HTTP 200 和
`{relationship_id, decision, decision_revision}`。这些旧接口缺口不再作为
当前阻断。B/C 历史真实服务证据保留在日期目录；本轮已对当前树完成重新构建和真实链路复测。

D 旧冻结 corpus 的异常状态/代码与 B/Compose corpus 不同。保留旧冻结答案，
使用新版本验收清单记录实际源文件与结果，不能改金标迎合搜索结果。

## 人工签认

A/B/C/D 签认：本次自动审计未提供。B 金标人工审阅：仍以原金标记录为准。
实现和自动验证可以完成，团队人工批准另行记录，不由工具代签。
