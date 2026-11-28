# Docker 只读检查记录

日期：2026-10-16，Asia/Shanghai。用户仅授权只读 Docker 检查；未执行 up/start/restart/build/exec/down 等操作，未修改运行中容器或卷。

## 容器快照

| Compose 服务 | State | Health |
| --- | --- | --- |
| frontend | running | unhealthy |
| api | created | 未启动 |
| db | created | 未启动 |
| ai | created | 未启动 |
| worker | created | 未启动 |

命令为 `docker compose ps --format json`、`docker compose ps -a --format json`，以及仅取前端健康检查字段的 `docker inspect`。最近 25 行前端日志显示 Nginx 正常启动及已有页面请求，不代表业务后端健康。

## unhealthy 的直接证据

容器健康检查配置：

```text
wget --no-verbose --tries=1 --spider http://localhost/health
```

健康检查日志反复返回 exit code 1：

```text
Connecting to localhost ([::1]:80)
wget: can't connect to remote host: Connection refused
```

仓库 `frontend/nginx.conf` 仅设置 `listen 80;`（IPv4）。宿主机只读 HTTP 检查：

```text
GET  http://127.0.0.1:3000/health -> HTTP 200, body: ok
HEAD http://127.0.0.1:3000/select -> HTTP 200, Content-Type: text/html
```

因此现有容器的 unhealthy 来自探针访问 IPv6 loopback 失败，不是已证明 Nginx 页面无法服务。HTTP 200 仅证明静态页面响应，不证明文件管理 API、JS 运行时、Worker 或数据库就绪。

## 本地源配置修正与尚未部署的差异

- `frontend/Dockerfile` 和 `compose.yaml` 中前端探针已改为 `http://127.0.0.1/health`。
- `docker compose config --quiet` 通过，退出码 0。
- 现有容器仍使用旧探针。没有获准或执行重建，因此没有声称健康状态已恢复。
- 现有容器绑定 `0.0.0.0:3000` 和 `[::]:3000`；仓库前端配置为 `127.0.0.1:3000`。此差异也尚未应用，不能声称现有容器已经仅本机可访问。
- 当前仓库 API 只有 starter 的 health/metrics/cases/jobs 路由，未提供 mounts/roots/files/evidence 产品接口。即使另获授权启动现有后端，也不能直接完成 D 的真实产品链路验收。
