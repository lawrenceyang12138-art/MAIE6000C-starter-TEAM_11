# 验证记录 2026 年 10 月 16 日

## 用户补充授权后的结果

- 依赖安装：通过。仅为本次进程清除失效的本地代理，使用 npm 官方仓库，禁用安装脚本，安装 155 个包，生成 `frontend/package-lock.json`；未改全局 npm/系统代理或现有 `.env`。`npm ls --depth=0` 确认全部 8 个直接依赖版本一致。
- `npm run build`：API 模式生产构建通过，4910 modules；构建产物与哈希见 `build-verification.md`。
- `npm test -- --run --reporter=verbose --reporter=json --outputFile=../submissions/week07/evidence/1016-D/vitest-report.json`：2 个文件、9/9 通过。测试对象为 Mock 适配器和状态辅助函数，不是 React 组件。
- `node --test scripts/test_d_integration.test.mjs`：35/35 通过，0 fail，0 skipped；使用注入的 fetch/Response，未连接实际 API。
- `node scripts/test_d_mock.mjs`：通过。验证模拟 202、进度、16 条记录、空目录、版本证据与失败状态。
- `node scripts/validate_d_fixtures.mjs`：通过。16 文件、20 个正常 PDF 页、12/3/1 分组及全部哈希一致。
- `python scripts/validate_d_gold.py`：通过。10 条查询、10 个真实页码/原文位置、16 个语料哈希；B 审核 pending；检索评测 not_run。
- `node scripts/capture_d_ui.mjs`：在 API 模式生产构建预览 `http://127.0.0.1:4173` 上通过 8/8 浏览器场景，页面运行时异常 0，授权 POST 1 次；使用独立无头 Chrome 155.0.8059.82、1440×1000、reduced motion。所有 `/api` 请求由脚本拦截，**不是产品联调**。
- 视觉检查：8 张 PNG 已逐张查看；授权表单、12/3/1、四类状态、未知计数及 HTTP 503 提示清晰可见，无横向溢出，均保留 NOT PRODUCT EVIDENCE 水印。结果页先以文件名过滤，再选中文件，确保文件行和检查器完整呈现。
- Docker 只读：`compose ps`、`ps -a`、限定字段 `inspect`、前端最近日志、`compose config --quiet` 均已执行。前端 running/unhealthy，其他四个核心服务 created；健康探针 `localhost -> ::1` 被拒绝，但宿主机 `/health` 与 `/select` 返回 200。源码已改 IPv4 健康地址，未重建/启动/停止容器。详情见 `docker-readonly.md`。
- `git diff --check`：通过；有仓库换行转换提示，没有空白错误。

## 历史阻塞与处理

早前安装因本地代理 `127.0.0.1:7897` 不可达失败，安装/Docker 的审批服务曾返回 503。用户本轮明确授权后重新申请并成功执行。普通构建/测试又遇到沙箱对 Vite 临时配置文件的 EPERM，已按流程申请正常权限后成功执行，未规避审批。

## 仍未验证

真实文件管理 API、数据库/Worker/AI 全链路、真实语料 12/3/1、真实服务截图、真实 AI 停机降级、B 人工复核均未完成。没有连接用户现有浏览器会话，没有修改 A/B/C 的后端、迁移和 Worker。

以上为本地开发与模拟契约证据，不是语义搜索效果报告、性能结果或产品验收签字。
