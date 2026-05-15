# Sub2API OAuth 主动休眠插件

[English README](README.md)

这是一个 Sub2API 的 sidecar 管理插件，用于在 OAuth 账号的官方用量窗口达到阈值时，主动把账号标记为限流/休眠，直到官方 reset 时间。

本项目适合部署在**内网、VPN 或可信管理员网络**。插件会直接读写 Sub2API 的 PostgreSQL 数据库；它不会调用 OpenAI、Anthropic 或 Sub2API 管理 API。

## 功能概览

插件会定时扫描 Sub2API 数据库中的 `accounts` 表，筛选条件为：

- `deleted_at IS NULL`
- `status = 'active'`
- `type = 'oauth'`
- `platform IN ('openai', 'anthropic')`，具体取决于插件配置

插件读取 Sub2API 已经记录在数据库中的官方用量和 reset 时间字段。当使用率达到配置阈值时，插件会写入：

- `accounts.rate_limited_at = NOW()`
- `accounts.rate_limit_reset_at = <官方 reset 时间>`

Sub2API 主程序会基于这些字段识别账号处于限流/休眠状态。

插件还会维护自己的配置和事件表：

- `plugin_oauth_sleeper_settings`
- `plugin_oauth_sleeper_events`

## 它不会做什么

- 不使用 OpenAI API Key。
- 不使用 Anthropic API Key。
- 不调用 OpenAI / Anthropic API。
- 不调用 Sub2API 管理 API。
- 不修改 Sub2API 镜像或源码。
- 不新增或修改 Sub2API 表结构；只创建插件自己的表，并写入 Sub2API 已存在的 `accounts.rate_limited_at` / `accounts.rate_limit_reset_at` 字段。

## 休眠判断逻辑

### OpenAI OAuth

插件从 `accounts.extra` 读取：

- `codex_5h_used_percent`
- `codex_5h_reset_at`
- `codex_7d_used_percent`
- `codex_7d_reset_at`

如果某个窗口的使用率 `>= 阈值`，并且 reset 时间仍在未来，则该窗口命中。若多个窗口同时命中，插件会选择 reset 时间更晚的窗口。

### Anthropic OAuth

插件读取：

- `accounts.extra.session_window_utilization`
- `accounts.session_window_end`
- `accounts.extra.passive_usage_7d_utilization`
- `accounts.extra.passive_usage_7d_reset`

Anthropic 的 utilization 通常是小数形式，例如 `0.82`，插件会乘以 100 后再和阈值比较。

## 安全模型

开源默认版本**没有内置认证**。这是为了适配内网/可信网络的直接访问模式。

但请注意：这个插件可以修改 Sub2API 数据库中的账号限流字段，所以**不要无认证暴露到公网**。

建议：

- 只绑定内网 / VPN 地址；或
- 在 Caddy / Nginx / 网关层加 Basic Auth、SSO、IP 白名单、防火墙；并且
- 不要把插件 API 裸露到公网。

## 环境要求

- Docker
- Docker Compose v2
- 已运行的 Sub2API
- Sub2API 使用 PostgreSQL
- 插件容器能访问 Sub2API 的 PostgreSQL 服务
- Sub2API 数据库字段格式和本插件适配的 OAuth 用量字段一致

## Docker Compose 快速部署

### 1. 克隆项目

```bash
git clone https://github.com/your-name/sub2api-oauth-sleeper-plugin.git
cd sub2api-oauth-sleeper-plugin
```

### 2. 创建配置文件

```bash
cp .env.example .env
nano .env
```

至少需要修改：

```env
DATABASE_URL=postgres://sub2api:<your-db-password>@postgres:5432/sub2api
SUB2API_DOCKER_NETWORK=sub2api_sub2api-network
PUBLIC_BASE_PATH=/custom/oauth-sleeper
```

说明：

- `DATABASE_URL`：Sub2API PostgreSQL 数据库连接串。
- `SUB2API_DOCKER_NETWORK`：插件要加入的 Docker 网络，必须能访问 PostgreSQL 容器。
- `PUBLIC_BASE_PATH`：反代暴露给浏览器访问的路径。

### 3. 启动插件

```bash
docker compose up -d --build
```

### 4. 查看状态

```bash
docker compose ps
```

健康检查：

```bash
curl http://127.0.0.1:8080/health
```

注意：默认 `docker-compose.yml` 不暴露宿主机端口。生产环境建议通过已有 Caddy / Nginx 反代访问。

如果当前 shell 配置了 `http_proxy` / `https_proxy`，本机健康检查要绕过代理：

```bash
NO_PROXY=127.0.0.1,localhost curl http://127.0.0.1:8080/health
```

## Caddy 反代示例

以下示例把插件挂载到 `/custom/oauth-sleeper`：

```caddyfile
handle /custom/oauth-sleeper/api/* {
  uri strip_prefix /custom/oauth-sleeper
  reverse_proxy sub2api-oauth-sleeper-plugin:8080
}

handle /custom/oauth-sleeper/static/* {
  uri strip_prefix /custom/oauth-sleeper
  reverse_proxy sub2api-oauth-sleeper-plugin:8080
}

handle /custom/oauth-sleeper* {
  uri strip_prefix /custom/oauth-sleeper
  rewrite * /admin
  reverse_proxy sub2api-oauth-sleeper-plugin:8080
}
```

同时 `.env` 设置：

```env
PUBLIC_BASE_PATH=/custom/oauth-sleeper
```

访问：

```text
http://<your-lan-host>/custom/oauth-sleeper
```

## 本地端口测试

如果你只是本地测试，可以在 `docker-compose.yml` 里给服务加：

```yaml
ports:
  - "8088:8080"
```

然后 `.env` 设置：

```env
PUBLIC_BASE_PATH=
```

访问：

```text
http://127.0.0.1:8088/admin
```

## 配置项说明

`.env.example` 包含所有配置项：

- `DATABASE_URL`：Sub2API PostgreSQL 连接串。
- `HOST`：容器内监听地址，通常为 `0.0.0.0`。
- `PORT`：容器内监听端口，默认 `8080`。
- `DEFAULT_SLEEP_THRESHOLD_PERCENT`：首次初始化时的默认休眠阈值。
- `SCAN_INTERVAL_SECONDS`：首次初始化时的默认扫描间隔。
- `INCLUDE_OPENAI`：首次初始化时是否扫描 OpenAI OAuth。
- `INCLUDE_ANTHROPIC`：首次初始化时是否扫描 Anthropic OAuth。
- `PUBLIC_BASE_PATH`：浏览器访问插件时使用的反代路径。
- `SUB2API_DOCKER_NETWORK`：已有 Sub2API / PostgreSQL 所在的 Docker 网络。

注意：首次启动后，运行时配置会保存到 `plugin_oauth_sleeper_settings` 表中，之后可以直接在插件页面修改。

## API

默认没有内置认证。如需公网或半公网访问，请在反代层加认证。

接口：

- `GET /health`
- `GET /admin`
- `GET /api/status`
- `GET /api/settings`
- `PUT /api/settings`
- `POST /api/scan-once`
- `GET /api/events?limit=50`

示例：修改配置为开启、75% 阈值、30 秒扫描一次：

```bash
curl -X PUT http://127.0.0.1:8080/api/settings \
  -H 'Content-Type: application/json' \
  -d '{
    "enabled": true,
    "threshold_percent": 75,
    "scan_interval_seconds": 30,
    "include_openai": true,
    "include_anthropic": true
  }'
```

## 数据库说明

插件会自动创建两个表：

```sql
plugin_oauth_sleeper_settings
plugin_oauth_sleeper_events
```

插件读取 Sub2API 原有的 `accounts` 表，并只写入以下已有字段：

```sql
rate_limited_at
rate_limit_reset_at
updated_at
```

写入逻辑是保守的：只有当 `rate_limit_reset_at` 为空，或当前记录的 reset 时间早于新的官方 reset 时间时，才会更新。

## 运维建议

- 新环境建议先关闭自动扫描，确认状态后再启用。
- 启用前先访问 `GET /api/status`，确认能正确读取账号数量和配置。
- 初始阈值建议保守一些，例如 `90`。
- 启用后观察 `plugin_oauth_sleeper_events` 和 Sub2API 账号行为。
- 如果部署到非完全可信网络，请务必加反代认证。

## 开发运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

语法检查：

```bash
python3 -m py_compile app/*.py
node --check app/static/app.js
```

## 许可证

MIT
