# Sub2API OAuth Sleeper Plugin

[中文文档](README.zh-CN.md)

A sidecar admin page for Sub2API that proactively marks OAuth accounts as rate-limited when their recorded official usage windows reach a configurable threshold.

This project is intended for private LAN / trusted-admin deployments. It directly reads and writes the Sub2API PostgreSQL database; it does not call OpenAI, Anthropic, or Sub2API admin APIs.

## What it does

- Periodically scans Sub2API `accounts` rows where:
  - `deleted_at IS NULL`
  - `status = 'active'`
  - `type = 'oauth'`
  - `platform IN ('openai', 'anthropic')`, depending on settings
- Reads official usage/reset fields already stored by Sub2API in `accounts.extra` / account columns.
- If usage is greater than or equal to the configured threshold, writes:
  - `accounts.rate_limited_at = NOW()`
  - `accounts.rate_limit_reset_at = <official reset time>`
- Records plugin settings and trigger events in its own tables:
  - `plugin_oauth_sleeper_settings`
  - `plugin_oauth_sleeper_events`

## What it does not do

- Does not use OpenAI API keys.
- Does not use Anthropic API keys.
- Does not call OpenAI or Anthropic APIs.
- Does not call Sub2API admin APIs.
- Does not change the Sub2API application image or source code.
- Does not create or modify Sub2API schema except writing existing `accounts.rate_limited_at` / `accounts.rate_limit_reset_at` fields and creating plugin-owned tables.

## How it decides to sleep accounts

### OpenAI OAuth

Reads these keys from `accounts.extra`:

- `codex_5h_used_percent`
- `codex_5h_reset_at`
- `codex_7d_used_percent`
- `codex_7d_reset_at`

If a usage percentage is `>= threshold` and the reset time is in the future, that window is eligible. If multiple windows match, the plugin chooses the later reset time.

### Anthropic OAuth

Reads:

- `accounts.extra.session_window_utilization`
- `accounts.session_window_end`
- `accounts.extra.passive_usage_7d_utilization`
- `accounts.extra.passive_usage_7d_reset`

Anthropic utilization values are expected as fractions, so the plugin multiplies them by 100 before comparing to the threshold.

## Security model

By default this open-source copy exposes the plugin page and API without built-in authentication. That matches a trusted LAN deployment model, but it is dangerous on the public internet because the plugin can write rate-limit fields in your Sub2API database.

Recommended protections:

- Bind the reverse proxy only to a private LAN/VPN interface, or
- Put Basic Auth / SSO / firewall rules in front of the plugin path, and
- Never expose the plugin API unauthenticated to the public internet.

## Requirements

- Docker and Docker Compose v2
- A running Sub2API deployment backed by PostgreSQL
- Network reachability from this plugin container to the Sub2API PostgreSQL service
- Sub2API database fields compatible with the current OAuth usage fields listed above

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

## Quick start with Docker Compose

1. Clone this project:

```bash
git clone https://github.com/lwhfxmoss/sub2api-oauth-sleeper-plugin.git
cd sub2api-oauth-sleeper-plugin
```

2. Create config:

```bash
cp .env.example .env
nano .env
```

Minimum required change:

```env
DATABASE_URL=postgres://sub2api:<your-db-password>@postgres:5432/sub2api
SUB2API_DOCKER_NETWORK=sub2api_sub2api-network
PUBLIC_BASE_PATH=/custom/oauth-sleeper
```

3. Start the sidecar:

```bash
docker compose up -d --build
```

4. Check health from inside the Docker network or through your reverse proxy:

```bash
docker compose ps
curl http://127.0.0.1:8080/health
```

The compose file does not publish a host port by default. Expose it through your existing reverse proxy, or add a `ports:` mapping for local testing.

If your shell has `http_proxy` / `https_proxy` set, bypass proxies for local checks:

```bash
NO_PROXY=127.0.0.1,localhost curl http://127.0.0.1:8080/health
```

## Reverse proxy examples

### Caddy path mount

This exposes the plugin under `/custom/oauth-sleeper` on the same origin as Sub2API.

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

Then set:

```env
PUBLIC_BASE_PATH=/custom/oauth-sleeper
```

Open:

```text
http://<your-lan-host>/custom/oauth-sleeper
```

### Direct testing with a host port

For local testing, you may add this to `docker-compose.yml`:

```yaml
ports:
  - "8088:8080"
```

Then set:

```env
PUBLIC_BASE_PATH=
```

Open:

```text
http://127.0.0.1:8088/admin
```

## Configuration

`.env.example` contains all supported variables.

- `DATABASE_URL`: PostgreSQL connection string for the existing Sub2API database.
- `HOST`: listen address inside the container, usually `0.0.0.0`.
- `PORT`: listen port inside the container, default `8080`.
- `DEFAULT_SLEEP_THRESHOLD_PERCENT`: initial threshold used only when plugin settings are first created.
- `SCAN_INTERVAL_SECONDS`: initial scan interval used only when plugin settings are first created.
- `INCLUDE_OPENAI`: initial OpenAI scanning switch.
- `INCLUDE_ANTHROPIC`: initial Anthropic scanning switch.
- `PUBLIC_BASE_PATH`: public reverse-proxy path used by the web UI for API/static requests.
- `SUB2API_DOCKER_NETWORK`: existing Docker network shared with Sub2API/PostgreSQL.

After first startup, runtime settings are stored in `plugin_oauth_sleeper_settings` and can be changed from the UI.

## API

No authentication is built in by default. Protect these endpoints at your reverse proxy if needed.

- `GET /health`
- `GET /admin`
- `GET /api/status`
- `GET /api/settings`
- `PUT /api/settings`
- `POST /api/scan-once`
- `GET /api/events?limit=50`

Example settings update:

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

## Database notes

The plugin creates these tables if missing:

```sql
plugin_oauth_sleeper_settings
plugin_oauth_sleeper_events
```

It reads from Sub2API's existing `accounts` table and writes only these existing fields:

```sql
rate_limited_at
rate_limit_reset_at
updated_at
```

The update is conservative: it only writes when `rate_limit_reset_at` is null or earlier than the new official reset time.

## Operational recommendations

- Deploy disabled first if you are testing a new environment.
- Verify `GET /api/status` before enabling automatic scanning.
- Start with a conservative threshold such as `90`.
- Watch `plugin_oauth_sleeper_events` and Sub2API behavior after enabling.
- Keep this plugin on a private network unless you add external authentication.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Syntax checks:

```bash
python3 -m py_compile app/*.py
node --check app/static/app.js
```

## License

MIT
