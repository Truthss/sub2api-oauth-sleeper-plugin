from __future__ import annotations

import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def run_frontend_action(action: str, account_id: int) -> list[dict[str, str]]:
    script = f"""
const fs = require('fs');
const vm = require('vm');
const fetchCalls = [];
const elements = new Map();
const ids = [
  'message', 'enabled', 'threshold', 'interval', 'maxSleep',
  'includeOpenai', 'includeAnthropic', 'enabledStat', 'thresholdStat',
  'intervalStat', 'lastScanStat', 'triggeredStat', 'sleepingCountStat',
  'accountsBody', 'sleepingBody', 'eventsBody', 'refreshBtn', 'saveBtn',
  'scanBtn', 'accountsPrev', 'accountsNext', 'sleepingPrev', 'sleepingNext',
  'eventsPrev', 'eventsNext', 'accountsTotal', 'accountsPageInfo',
  'sleepingTotal', 'sleepingPageInfo', 'eventsTotal', 'eventsPageInfo'
];
const makeEl = () => ({{
  textContent: '',
  style: {{}},
  value: '',
  checked: false,
  disabled: false,
  innerHTML: '',
  onclick: null,
}});

for (const id of ids) {{
  elements.set(id, makeEl());
}}

globalThis.window = globalThis;
window.__OAUTH_SLEEPER_CONFIG__ = {{}};
globalThis.document = {{
  getElementById(id) {{
    if (!elements.has(id)) {{
      elements.set(id, makeEl());
    }}
    return elements.get(id);
  }},
}};

const jsonResponse = data => ({{
  ok: true,
  async json() {{ return data; }},
  async text() {{ return JSON.stringify(data); }},
}});

globalThis.fetch = async (url, opts = {{}}) => {{
  const path = String(url);
  const method = opts.method || 'GET';
  fetchCalls.push({{ url: path, method }});

  if (path.includes('api/status')) {{
    return jsonResponse({{
      enabled: false,
      threshold_percent: 0,
      scan_interval_seconds: 0,
      max_sleep_per_scan: 0,
      include_openai: true,
      include_anthropic: true,
      last_scan_at: null,
      last_scan_triggered: 0,
      last_scan_scanned: 0,
      sleeping_count: 0,
    }});
  }}
  if (path.includes('api/accounts')) {{
    return jsonResponse({{ items: [], meta: {{ total: 0, page: 1, page_size: 10, total_pages: 1 }} }});
  }}
  if (path.includes('api/sleeping-accounts')) {{
    return jsonResponse({{ items: [], meta: {{ total: 0, page: 1, page_size: 10, total_pages: 1 }} }});
  }}
  if (path.includes('api/events')) {{
    return jsonResponse({{ items: [], meta: {{ total: 0, page: 1, page_size: 10, total_pages: 1 }} }});
  }}
  if (path.includes('api/whitelist/')) {{
    return jsonResponse({{ ok: true }});
  }}
  throw new Error(`Unexpected fetch ${{path}}`);
}};

(async () => {{
  const source = fs.readFileSync('app/static/app.js', 'utf8');
  vm.runInThisContext(source, {{ filename: 'app.js' }});
  await load();
  fetchCalls.length = 0;
  await window[{json.dumps(action)}]({account_id});
  console.log(JSON.stringify(fetchCalls));
}})().catch(err => {{
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
}});
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip() or result.stdout.strip() or "node script failed")
    return json.loads(result.stdout.strip())


def test_add_whitelist_handler_posts_once_and_refreshes_lists() -> None:
    calls = run_frontend_action("addWhitelist", 42)

    assert_equal(calls[0], {"url": "/api/whitelist/42", "method": "POST"}, "add whitelist request")
    assert_equal(len(calls), 4, "add whitelist request count")


def test_remove_whitelist_handler_deletes_once_and_refreshes_lists() -> None:
    calls = run_frontend_action("removeWhitelist", 42)

    assert_equal(calls[0], {"url": "/api/whitelist/42", "method": "DELETE"}, "remove whitelist request")
    assert_equal(len(calls), 4, "remove whitelist request count")


if __name__ == "__main__":
    tests = [
        test_add_whitelist_handler_posts_once_and_refreshes_lists,
        test_remove_whitelist_handler_deletes_once_and_refreshes_lists,
    ]
    for test in tests:
        try:
            test()
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
            raise
        else:
            print(f"PASS {test.__name__}")
