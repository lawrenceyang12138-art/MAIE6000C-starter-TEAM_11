# W7 范围与阻断记录：2026-10-31 更新

目标分支：`feat/c-team-pdf-evaluation`；检查基线：`0e3d715`。
当前实现已完成 W7 核心流程。本轮按
[共享合同](../../docs/team11-w7-shared-contract.md) 第 9 节及
[验收矩阵](../../docs/w7-acceptance.md) 执行集成测试并修复缺陷。
18/18 自动门槛均已通过，详见本轮证据。本文不代替团队人工签字。

## 当前状态

| 等级 | 项目 | 状态与处理 |
| --- | --- | --- |
| P0 | 授权、挂载、目录、文件、证据、搜索、关系、复核和 retry 路由装配 | 已关闭：最终真实 HTTP/DB 202 检查/0 失败，包含真实 Worker 和持久身份 |
| P0 | 首次导入、重复扫描、混入异常三个真实浏览器场景 | 已关闭：`frontend-live-clean` 空库首导入 3/3，`frontend-live-mixed` 异常与复核 6/6；数据库对比证实重扫不重复 |
| P1 | 关系证据缺直接 chunk ID | 已关闭：提取自动生成关系，响应含 `chunk_id`；无有效证据仍禁止复核 |
| P1 | 复核成功响应未约定 | 已关闭：共享合同 6.6 定义 HTTP 200 与 decision revision；保留 append-only 和 409 冲突 |
| P1 | D 异常 manifest 与真实 parser taxonomy 不符 | 验收阻断已关闭：历史 freeze 原样保留，本轮明确采用 B/Compose 的 16 文件及实际原因，前后源 hash 不变；旧 corpus 不冒充当前输入 |
| P1 | 本地请求保护、AI 不可用时冷启动 | 已关闭：Host/Origin 写保护和 Compose 依赖修复；八类真实拒绝无 DB 写；无 AI 冷启动及空库首次搜索通过 |
| P1 | 组合树中的解析、UI、模型恢复边界 | 已关闭：精确 chunk、纠正选择、receipt、unreadable 安全拒绝、首次派发恢复、禁用 AI、原子关键词就绪、降级/恢复、迁移回滚、评估打包与 Git 缺席均已修复且验证；最终 Linux 744/0skip、前端检查全通过 |
| P2 | 单 Worker 无 lease/backoff、进程崩溃后 claimed job 恢复 | 当前 W7 明示限制；后续队列成熟度工作，不能宣称已实现 |

早期 10.19 记录所述“缺路由、缺 chunk_id、review 形状未知”是历史事实，
已由后续装配、B 的关系实现与共享合同更新覆盖。B/C 先前真实服务证据证明
各自记录版本的行为；当前 combined tree 已完成本轮真实检查，原始失败及修复后结果均保留在 `evidence/20261031-w7/`。

## W7 保留能力

手动授权只读目录；递归扫描文本 PDF；持久异步任务；当前版本和源身份；
关键词/语义/hybrid 检索与明确降级；页级证据；小范围 person/project/topic
关系和人工 confirm/correct/reject；显式失败和重试；正常重启持久性；
本地隐私与越界拒绝；真实健康与运维信号。

原 Week 4 提案的 `/graph`、手动 tag 和队列状态是草案。当前共享合同已将本轮
关系界面收敛为每版本最多二十条证据候选及复核，不以旧草案扩张本轮新 API。
API/Worker 在 AI 不可用时继续工作及 Host/Origin 保护仍是当前本地边界要求。

## W13/R1 与 stretch

监控、pause/resume 管理、范围移除/purge/export、DOCX/TXT/Markdown、OCR、
完整图谱和跨文件遍历、多 Worker lease/退避属于后续工作。移动、重命名、
执行预览和 undo 属 stretch，不计入 W7 放行项。原件始终保持只读。

人工金标审阅与团队签认保持单独状态；可以继续完成已授权的实现和测试，
不等待或伪造任何人的签字。
