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

## Quick start with Docker Compose

1. Clone this project:

```bash
git clone https://github.com/your-name/sub2api-oauth-sleeper-plugin.git
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
