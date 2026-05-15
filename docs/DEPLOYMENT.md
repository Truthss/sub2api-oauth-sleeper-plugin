# Deployment Notes

[中文部署说明](DEPLOYMENT.zh-CN.md)

This project is designed as a sidecar next to an existing Sub2API deployment.

## Safe deployment principle

Do not modify or recreate the main Sub2API application, PostgreSQL, or Redis containers just to deploy this plugin. Run it as a separate container and connect it to the existing Docker network that can reach PostgreSQL.

## Steps

1. Copy `.env.example` to `.env`.
2. Set `DATABASE_URL` to your Sub2API PostgreSQL DSN.
3. Set `SUB2API_DOCKER_NETWORK` to the Docker network shared by Sub2API/PostgreSQL.
4. Set `PUBLIC_BASE_PATH` to the path where your reverse proxy exposes this plugin.
5. Start the plugin with `docker compose up -d --build`.
6. Add reverse-proxy routes for the plugin path.
7. Open the admin page and verify status before enabling scanning.

## Caddy route template

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

## Security

This project intentionally has no built-in authentication in the open-source default. Keep it on a trusted LAN/VPN or add authentication at your reverse proxy.
