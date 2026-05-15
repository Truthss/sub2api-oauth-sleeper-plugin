# 部署说明

[English deployment notes](DEPLOYMENT.md)

本项目设计为部署在现有 Sub2API 旁边的 sidecar 插件。

## 安全部署原则

为了部署这个插件，不需要修改或重建 Sub2API 主应用、PostgreSQL 或 Redis 容器。建议单独运行插件容器，并把它接入能访问 PostgreSQL 的现有 Docker 网络。

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
