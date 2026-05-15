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

## AI 部署指引（给自动化 Agent）

本区块专门给 AI / 自动化 Agent 使用。目标是让 Agent 能在已有 Sub2API 旁边部署本插件，同时不破坏正在运行的业务。

### 不可违反的原则

- 不要重建、重启或修改 Sub2API 主应用容器。
- 不要重建、重启或修改 Sub2API 使用中的 PostgreSQL / Redis 容器。
- 不要修改 Sub2API 源码、镜像或数据库表结构。
- 不要把插件无认证暴露到公网。
- 接真实数据库测试前，必须确认用户知道 `保存配置` 和 `立即扫描一次` 会真实写库。
- 如果只是验收页面，优先先接测试 PostgreSQL；接真实库时避免额外部署第二个自动扫描实例与现有生产插件并发写库。

### Agent 需要收集的信息

Agent 不应猜测这些值，必须从宿主机实际环境读取或让用户提供：

- Sub2API 项目目录：通过用户给出的路径、`docker ps`、容器 label、compose 文件位置或常见路径定位。
- PostgreSQL 容器名/服务名：通过 `docker ps --format '{{.Names}}'`、`docker inspect`、Sub2API compose 文件确认。
- PostgreSQL 数据库名、用户名、密码：优先从 Sub2API 的 `.env`、`docker-compose.yml`、容器环境变量读取；如果读不到，再让用户提供。
- Docker 网络名：通过 `docker inspect <sub2api-or-postgres-container>` 查看 `NetworkSettings.Networks`，选择插件容器能访问 PostgreSQL 的那个网络。
- 插件访问方式：内网直连端口、Caddy/Nginx 路径反代、VPN 地址或仅本机测试。
- 是否已有一个生产版本插件在运行：如果已有，不要再启动第二个自动扫描实例连接同一个真实库，除非用户明确要求。

### 推荐发现命令

```bash
# 查看正在运行的相关容器
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'

# 查看某个容器所在 Docker 网络
POSTGRES_CONTAINER=<postgres-container-name>
docker inspect "$POSTGRES_CONTAINER" \
  --format '{{json .NetworkSettings.Networks}}'

# 查看容器环境变量，寻找 POSTGRES / DATABASE 相关配置
# 注意：输出可能包含密码，Agent 不应把真实值发到公开聊天或提交到 Git。
docker inspect "$POSTGRES_CONTAINER" \
  --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -Ei 'POSTGRES|DATABASE|DB_'

# 如果知道 Sub2API 主容器名，也可以查看它的数据库连接环境变量
SUB2API_CONTAINER=<sub2api-container-name>
docker inspect "$SUB2API_CONTAINER" \
  --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -Ei 'POSTGRES|DATABASE|DB_'
```

### 生成 `.env` 的规则

Agent 应创建 `.env`，但不要把真实 `.env` 提交到 Git。

```env
DATABASE_URL=postgres://<db-user>:<db-password>@<postgres-service-or-container-name>:5432/<db-name>
HOST=0.0.0.0
PORT=8080
DEFAULT_SLEEP_THRESHOLD_PERCENT=90
SCAN_INTERVAL_SECONDS=60
INCLUDE_OPENAI=true
INCLUDE_ANTHROPIC=true
PUBLIC_BASE_PATH=/custom/oauth-sleeper
SUB2API_DOCKER_NETWORK=<docker-network-that-can-reach-postgres>
```

配置说明：

- `DATABASE_URL`：必须指向 Sub2API 正在使用的 PostgreSQL。主机名通常是同一 Docker 网络里的 Postgres 服务名/容器名，而不是宿主机公网域名。
- `HOST` / `PORT`：容器内部监听地址和端口，通常保持默认。
- `DEFAULT_SLEEP_THRESHOLD_PERCENT`：首次初始化插件配置表时写入的默认阈值；插件运行后以数据库表 `plugin_oauth_sleeper_settings` 为准。
- `SCAN_INTERVAL_SECONDS`：首次初始化插件配置表时写入的默认扫描间隔；插件运行后以数据库表为准。
- `INCLUDE_OPENAI` / `INCLUDE_ANTHROPIC`：首次初始化时是否启用对应平台扫描。
- `PUBLIC_BASE_PATH`：浏览器访问插件时的外部路径。如果通过 `/custom/oauth-sleeper` 反代，就设为 `/custom/oauth-sleeper`；如果直接用 `http://host:port/admin`，可留空。
- `SUB2API_DOCKER_NETWORK`：插件容器加入的外部 Docker 网络，必须和 PostgreSQL 可互通。

### 部署策略

- **安全验证优先**：先用独立测试 PostgreSQL 验证镜像、页面和扫描逻辑，再接真实库。
- **真实库只读验收**：如果只是让用户看真实数据，建议禁用额外自动扫描，避免多个插件实例同时写同一个 `accounts` 表。
- **生产启用**：确认只保留一个自动扫描实例连接真实库，再启用扫描。
- **局域网访问**：如果用户要求从其他终端访问，可以在 compose 中临时加端口映射，例如 `0.0.0.0:18090:8080`，并确保防火墙仅允许可信网段。
- **反代访问**：如果挂到 Caddy/Nginx 路径，必须同步设置 `PUBLIC_BASE_PATH`，否则前端 API/static 路径会错。

### 验证清单

部署后 Agent 至少要验证：

```bash
docker compose ps
NO_PROXY=127.0.0.1,localhost curl http://127.0.0.1:8080/health
curl http://<lan-host-or-reverse-proxy>/custom/oauth-sleeper/api/status
```

如果有代理环境变量，访问 `127.0.0.1`、`localhost`、内网 IP 时要设置 `NO_PROXY`，避免请求被代理送出。

还应确认：

- 插件容器是新增 sidecar，不是替换 Sub2API 主容器。
- Sub2API 主容器、PostgreSQL、Redis 的启动时间没有变化。
- `/api/status` 返回的 `enabled`、`threshold_percent`、`scan_interval_seconds` 符合预期。
- 页面能加载，并能看到当前设置和事件列表。
- 如果执行 `POST /api/scan-once`，必须明确这是写真实数据库的操作。

### 常见错误

- `DATABASE_URL` 使用了公网域名：容器内通常应该使用 Docker 网络里的 Postgres 服务名/容器名。
- `SUB2API_DOCKER_NETWORK` 填错：插件容器无法解析或连接 Postgres。
- `PUBLIC_BASE_PATH` 与反代路径不一致：页面打开但 API 或静态资源 404。
- 宿主机代理影响本地验证：`curl 127.0.0.1` 被代理导致异常，使用 `NO_PROXY`。
- 同一个真实库跑多个自动扫描实例：可能造成重复扫描、重复事件或并发写库；生产应避免。

## Docker Compose 快速部署

### 1. 克隆项目

```bash
git clone https://github.com/lwhfxmoss/sub2api-oauth-sleeper-plugin.git
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
