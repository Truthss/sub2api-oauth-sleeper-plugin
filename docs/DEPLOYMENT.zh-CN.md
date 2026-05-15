# 部署说明

[English deployment notes](DEPLOYMENT.md)

本项目设计为部署在现有 Sub2API 旁边的 sidecar 插件。

## 安全部署原则

为了部署这个插件，不需要修改或重建 Sub2API 主应用、PostgreSQL 或 Redis 容器。建议单独运行插件容器，并把它接入能访问 PostgreSQL 的现有 Docker 网络。

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

## 部署步骤

1. 复制配置模板：

```bash
cp .env.example .env
```

2. 修改 `.env`：

```env
DATABASE_URL=postgres://sub2api:<your-db-password>@postgres:5432/sub2api
SUB2API_DOCKER_NETWORK=sub2api_sub2api-network
PUBLIC_BASE_PATH=/custom/oauth-sleeper
```

3. 启动插件：

```bash
docker compose up -d --build
```

4. 配置反向代理，把插件路径转发到插件容器。

5. 打开管理页面，确认状态正常后再启用自动扫描。

## Caddy 路由模板

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

`.env` 中保持：

```env
PUBLIC_BASE_PATH=/custom/oauth-sleeper
```

访问：

```text
http://<your-lan-host>/custom/oauth-sleeper
```

## 验证命令

```bash
docker compose ps
curl http://127.0.0.1:8080/health
```

如果当前 shell 配置了 `http_proxy` / `https_proxy`，本机健康检查要绕过代理：

```bash
NO_PROXY=127.0.0.1,localhost curl http://127.0.0.1:8080/health
```

通过反代访问时：

```bash
curl http://<your-lan-host>/custom/oauth-sleeper/api/status
```

## 安全提醒

开源默认版本没有内置认证。它可以写入 Sub2API 数据库中的账号限流字段，因此：

- 不要无认证暴露公网。
- 推荐仅内网 / VPN 访问。
- 如需公网访问，请在 Caddy / Nginx / 网关层添加 Basic Auth、SSO、IP 白名单或其他认证机制。
