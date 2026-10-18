# C 关键词降级验证

2026-10-15 独立模块验证，语料为合成文本块。

实际启动独立 API、AI 和 worker，完成 10 条混合请求后结束 AI 进程，再执行五条关键词基准。全部返回正确文件与页码，并明确 degraded。

| 查询 | 实际文件 | 页码 | 实际模式 | 降级原因 |
|---|---|---|---|---|
| kw-1 | fixture-expenses | 1–1 | keyword | ai_unavailable |
| kw-2 | fixture-access | 1–1 | keyword | ai_unavailable |
| kw-3 | fixture-backup | 2–3 | keyword | ai_unavailable |
| kw-4 | fixture-retention | 2–2 | keyword | ai_unavailable |
| kw-5 | fixture-attendance | 3–3 | keyword | ai_unavailable |

原始证据：[Docker HTTP](evidence/C/http-docker-python311.json)、[本机 HTTP](evidence/C/http-check.json)。超时路径使用 HTTP 客户端超时和 API 回归测试验证；本记录不把模拟超时写成实际等待十秒的停服测试。模型运行路径只读本地文件，失败没有云端回退。
