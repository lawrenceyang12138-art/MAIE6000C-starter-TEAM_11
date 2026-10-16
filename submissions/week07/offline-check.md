# C 离线推理与失败隔离

2026-10-15 独立模块验证；不是第二电脑验收。

验证脚本阻断外部 socket 连接，仅允许 loopback 供本机事件循环、API 和数据库测试通信。在此状态下实际加载固定 revision 的本地 E5，关键词 Top-1 5/5、语义 Top-3 4/5，10 条 hybrid 返回 HTTP 200；关闭 AI 配置后五条关键词均可用。原始记录见 [Docker 离线检查](evidence/C/offline-docker-python311.json)。这证明运行时外网连接阻断下仍可推理，不等于已完成物理断网截图或备机部署。

实际停止 AI 进程的五条查询见 [degrade.md](degrade.md)。向量处理第二批失败时，首次索引的文本保持可用；重建时已有向量及模型元信息也不变，未发布部分新向量。对应参数化回归在完整 49 项测试中执行，结果见 [测试 XML](evidence/C/pytest-docker-python311.xml)。
