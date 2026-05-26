from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def assert_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def run_node(script: str) -> Any:
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip() or result.stdout.strip() or "node script failed")
    output = result.stdout.strip()
    return json.loads(output) if output else None


def base_vm_script(body: str, base_path: str = "") -> str:
    return f"""
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
  'sleepingTotal', 'sleepingPageInfo', 'eventsTotal', 'eventsPageInfo',
  'writeGuardTitle', 'writeGuardText'
];
const makeEl = () => ({{
  textContent: '',
  className: '',
  style: {{}},
  value: '',
  checked: false,
  disabled: false,
  innerHTML: '',
  onclick: null,
  dataset: {{}},
}});
for (const id of ids) elements.set(id, makeEl());
globalThis.window = globalThis;
window.__OAUTH_SLEEPER_CONFIG__ = {{ basePath: {json.dumps(base_path)} }};
globalThis.document = {{
  getElementById(id) {{
    if (!elements.has(id)) elements.set(id, makeEl());
    return elements.get(id);
  }},
}};
const jsonResponse = data => ({{
  ok: true,
  status: 200,
  async json() {{ return data; }},
  async text() {{ return JSON.stringify(data); }},
}});
globalThis.fetch = async (url, opts = {{}}) => {{
  const path = String(url);
  fetchCalls.push({{ url: path, method: opts.method || 'GET', body: opts.body || null }});
  if (path.includes('api/status')) {{
    return jsonResponse({{
      enabled: true,
      threshold_percent: 90,
      scan_interval_seconds: 60,
      max_sleep_per_scan: 3,
      include_openai: true,
      include_anthropic: true,
      last_scan_at: null,
      last_scan_triggered: 0,
      last_scan_scanned: 0,
      sleeping_count: 0,
      sleeping_accounts: [],
    }});
  }}
  return jsonResponse({{
    items: [],
    meta: {{ total: 0, page: 1, page_size: 10, total_pages: 1 }},
  }});
}};
const source = fs.readFileSync('app/static/app.js', 'utf8');
vm.runInThisContext(source, {{ filename: 'app.js' }});
{body}
"""


def test_api_joins_runtime_base_path_without_double_slash() -> None:
    script = base_vm_script(
        """
(async () => {
  fetchCalls.length = 0;
  await api('api/status');
  console.log(JSON.stringify(fetchCalls[0]));
})().catch(err => { console.error(err.stack || String(err)); process.exit(1); });
""",
        base_path="/custom/oauth-sleeper/",
    )

    call = run_node(script)

    assert_equal(call["url"], "/custom/oauth-sleeper/api/status", "mounted api url")


def test_api_uses_root_path_when_base_path_empty() -> None:
    script = base_vm_script(
        """
(async () => {
  fetchCalls.length = 0;
  await api('api/status');
  console.log(JSON.stringify(fetchCalls[0]));
})().catch(err => { console.error(err.stack || String(err)); process.exit(1); });
""",
        base_path="",
    )

    call = run_node(script)

    assert_equal(call["url"], "/api/status", "root api url")


def test_api_raises_response_text_on_non_ok_response() -> None:
    script = base_vm_script(
        """
globalThis.fetch = async () => ({
  ok: false,
  status: 400,
  async text() { return 'bad request'; },
});
(async () => {
  try {
    await api('api/status');
  } catch (err) {
    console.log(JSON.stringify({ message: err.message }));
    return;
  }
  throw new Error('expected api failure');
})().catch(err => { console.error(err.stack || String(err)); process.exit(1); });
"""
    )

    error = run_node(script)

    assert_equal(error["message"], "400 bad request", "api error message")


def test_save_sends_max_sleep_and_platform_switches() -> None:
    script = base_vm_script(
        """
$('enabled').checked = true;
$('threshold').value = '88';
$('interval').value = '45';
$('maxSleep').value = '4';
$('includeOpenai').checked = true;
$('includeAnthropic').checked = false;
(async () => {
  fetchCalls.length = 0;
  await save();
  const put = fetchCalls.find(call => call.url === '/api/settings' && call.method === 'PUT');
  console.log(JSON.stringify(JSON.parse(put.body)));
})().catch(err => { console.error(err.stack || String(err)); process.exit(1); });
"""
    )

    body = run_node(script)

    assert_equal(body["enabled"], True, "save enabled")
    assert_equal(body["threshold_percent"], 88, "save threshold")
    assert_equal(body["scan_interval_seconds"], 45, "save interval")
    assert_equal(body["max_sleep_per_scan"], 4, "save max sleep")
    assert_equal(body["include_openai"], True, "save openai switch")
    assert_equal(body["include_anthropic"], False, "save anthropic switch")


def test_render_accounts_page_wires_whitelist_buttons_by_state() -> None:
    script = base_vm_script(
        """
renderAccountsPage({
  items: [
    { id: 1, name: 'managed', platform: 'openai', status: 'active', rate_limit_reset_at: null, is_whitelisted: false },
    { id: 2, name: 'skip', platform: 'openai', status: 'active', rate_limit_reset_at: null, is_whitelisted: true },
  ],
  meta: { total: 2, page: 1, page_size: 10, total_pages: 1 },
});
console.log(JSON.stringify({
  html: $('accountsBody').innerHTML,
  prevDisabled: $('accountsPrev').disabled,
  nextDisabled: $('accountsNext').disabled,
}));
"""
    )

    result = run_node(script)

    assert_equal("加入白名单" in result["html"], True, "add whitelist button")
    assert_equal("移出白名单" in result["html"], True, "remove whitelist button")
    assert_equal("addWhitelist(1)" in result["html"], True, "add action id")
    assert_equal("removeWhitelist(2)" in result["html"], True, "remove action id")
    assert_equal(result["prevDisabled"], True, "single-page prev disabled")
    assert_equal(result["nextDisabled"], True, "single-page next disabled")


def test_update_pager_disables_prev_next_at_boundaries() -> None:
    script = base_vm_script(
        """
updatePager('accounts', { total: 30, page: 1, page_size: 10, total_pages: 3 });
const first = { prev: $('accountsPrev').disabled, next: $('accountsNext').disabled, info: $('accountsPageInfo').textContent };
updatePager('accounts', { total: 30, page: 3, page_size: 10, total_pages: 3 });
const last = { prev: $('accountsPrev').disabled, next: $('accountsNext').disabled, info: $('accountsPageInfo').textContent };
console.log(JSON.stringify({ first, last }));
"""
    )

    result = run_node(script)

    assert_equal(result["first"], {"prev": True, "next": False, "info": "第 1 / 3 页"}, "first page pager")
    assert_equal(result["last"], {"prev": False, "next": True, "info": "第 3 / 3 页"}, "last page pager")


if __name__ == "__main__":
    tests = [
        test_api_joins_runtime_base_path_without_double_slash,
        test_api_uses_root_path_when_base_path_empty,
        test_api_raises_response_text_on_non_ok_response,
        test_save_sends_max_sleep_and_platform_switches,
        test_render_accounts_page_wires_whitelist_buttons_by_state,
        test_update_pager_disables_prev_next_at_boundaries,
    ]
    for test in tests:
        try:
            test()
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
            raise
        else:
            print(f"PASS {test.__name__}")
