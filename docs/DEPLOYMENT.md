# Deployment Notes

[中文部署说明](DEPLOYMENT.zh-CN.md)

This project is designed as a sidecar next to an existing Sub2API deployment.

## Safe deployment principle

Do not modify or recreate the main Sub2API application, PostgreSQL, or Redis containers just to deploy this plugin. Run it as a separate container and connect it to the existing Docker network that can reach PostgreSQL.

## AI deployment block

This section is written for AI agents / automation agents. The goal is to deploy this plugin next to an existing Sub2API deployment without breaking the running service.

### Non-negotiable rules

- Do not recreate, restart, or modify the main Sub2API application container.
- Do not recreate, restart, or modify the PostgreSQL / Redis containers used by Sub2API.
- Do not modify Sub2API source code, images, or database schema.
- Do not expose this plugin unauthenticated to the public internet.
- Before connecting to a real production database, make sure the operator understands that `Save settings` and `Scan once` can write to the real database.
- For UI-only validation, prefer a test PostgreSQL first. When connecting to the real database, avoid running an extra automatic scanner if a production scanner is already active.

### Information the agent must collect

Do not guess these values. Read them from the host or ask the operator:

- Sub2API project directory: from the user's path, `docker ps`, container labels, compose file locations, or known deployment directories.
- PostgreSQL container/service name: from `docker ps`, `docker inspect`, or the Sub2API compose file.
- PostgreSQL database name, username, and password: preferably from Sub2API `.env`, `docker-compose.yml`, or container environment variables; ask the operator if unavailable.
- Docker network name: inspect `NetworkSettings.Networks` on the Sub2API or PostgreSQL container and choose a network that lets this plugin reach PostgreSQL.
- Plugin exposure method: LAN-only host port, Caddy/Nginx path reverse proxy, VPN-only address, or local-only testing.
- Whether another production copy of this plugin is already running. If yes, do not start a second automatic scanner against the same real database unless explicitly requested.

### Recommended discovery commands

```bash
# List relevant running containers
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'

# Inspect Docker networks for the PostgreSQL container
POSTGRES_CONTAINER=<postgres-container-name>
docker inspect "$POSTGRES_CONTAINER" \
  --format '{{json .NetworkSettings.Networks}}'

# Inspect environment variables for database-related settings.
# Warning: output may contain secrets. Do not paste real values into public chat or commit them to Git.
docker inspect "$POSTGRES_CONTAINER" \
  --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -Ei 'POSTGRES|DATABASE|DB_'

# If the Sub2API app container is known, inspect its DB connection variables too.
SUB2API_CONTAINER=<sub2api-container-name>
docker inspect "$SUB2API_CONTAINER" \
  --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -Ei 'POSTGRES|DATABASE|DB_'
```

### `.env` generation rules

The agent should create `.env`, but must never commit the real `.env` to Git.

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

Configuration notes:

- `DATABASE_URL`: must point to the PostgreSQL database used by Sub2API. Inside Docker, the host is usually the PostgreSQL service/container name on the shared Docker network, not a public domain.
- `HOST` / `PORT`: listen address and port inside the plugin container; defaults are usually correct.
- `DEFAULT_SLEEP_THRESHOLD_PERCENT`: initial threshold inserted only when plugin settings are first created. After startup, runtime settings live in `plugin_oauth_sleeper_settings`.
- `SCAN_INTERVAL_SECONDS`: initial scan interval inserted only when plugin settings are first created. After startup, runtime settings live in the database.
- `INCLUDE_OPENAI` / `INCLUDE_ANTHROPIC`: initial platform switches.
- `PUBLIC_BASE_PATH`: public path used by the browser. Use `/custom/oauth-sleeper` for a path reverse proxy; leave empty for direct `http://host:port/admin` access.
- `SUB2API_DOCKER_NETWORK`: external Docker network the plugin joins; it must be able to reach PostgreSQL.

### Deployment strategy

- **Validate safely first**: test image build, UI, and scan behavior against an isolated test PostgreSQL before using the real database.
- **Real database UI validation**: if the goal is only to show real data, disable any extra automatic scan loop to avoid two plugin instances writing the same `accounts` table.
- **Production enablement**: ensure only one automatic scanner points to the real database before enabling scanning.
- **LAN access**: if the operator needs access from another device, add a temporary host-port mapping such as `0.0.0.0:18090:8080` and restrict it to trusted networks.
- **Reverse proxy access**: when mounting under a Caddy/Nginx path, set `PUBLIC_BASE_PATH` to the same path or API/static URLs will break.

### Verification checklist

After deployment, verify at least:

```bash
docker compose ps
NO_PROXY=127.0.0.1,localhost curl http://127.0.0.1:8080/health
curl http://<lan-host-or-reverse-proxy>/custom/oauth-sleeper/api/status
```

If proxy environment variables are present, set `NO_PROXY` for `127.0.0.1`, `localhost`, and LAN IPs so local checks are not sent through the proxy.

Also confirm:

- The plugin container is a new sidecar, not a replacement for the Sub2API app container.
- Sub2API app, PostgreSQL, and Redis container start times did not change.
- `/api/status` returns the expected `enabled`, `threshold_percent`, and `scan_interval_seconds` values.
- The admin page loads and shows settings/events.
- If calling `POST /api/scan-once`, the operator has explicitly accepted that it writes to the real database.

### Common mistakes

- Using a public domain in `DATABASE_URL`: inside Docker, use the PostgreSQL service/container name on the shared network.
- Wrong `SUB2API_DOCKER_NETWORK`: the plugin cannot resolve or connect to PostgreSQL.
- Mismatched `PUBLIC_BASE_PATH`: the page loads but API/static requests return 404.
- Host proxy variables affecting local checks: `curl 127.0.0.1` may go through a proxy; use `NO_PROXY`.
- Running multiple automatic scanners against the same real database: this can cause duplicate scans, duplicate events, or concurrent writes. Avoid it in production.

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

## Verification

```bash
docker compose ps
curl http://127.0.0.1:8080/health
```

If your shell has `http_proxy` / `https_proxy` set, bypass proxies for local checks:

```bash
NO_PROXY=127.0.0.1,localhost curl http://127.0.0.1:8080/health
```

## Security

This project intentionally has no built-in authentication in the open-source default. Keep it on a trusted LAN/VPN or add authentication at your reverse proxy.
