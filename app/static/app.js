const headers = () => ({ 'Content-Type': 'application/json' });
const $ = id => document.getElementById(id);
const basePath = (() => {
  const configured = (window.OAUTH_SLEEPER_BASE_PATH || '').trim().replace(/\/$/, '');
  if (configured) return configured;
  const path = window.location.pathname.replace(/\/$/, '');
  if (path.endsWith('/admin')) return path.slice(0, -'/admin'.length);
  return path;
})();
function rel(path){ return path.replace(/^\//, ''); }
function apiUrl(path){ return `${basePath}/${rel(path)}`; }
function fmt(t){ return t ? new Date(t).toLocaleString() : '-'; }
function pct(v){ return `${Number(v || 0).toFixed(2)}%`; }
function msg(s, bad=false){ const el=$('message'); el.textContent=s; el.style.color=bad?'#b91c1c':'#065f46'; }
async function api(path, opts={}){
  const r = await fetch(apiUrl(path), { ...opts, headers: { ...headers(), ...(opts.headers||{}) }});
  if(!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return await r.json();
}
function escapeHtml(value){
  return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}
function fillSettings(s){
  $('enabled').checked = s.enabled;
  $('threshold').value = s.threshold_percent;
  $('interval').value = s.scan_interval_seconds;
  $('includeOpenai').checked = s.include_openai;
  $('includeAnthropic').checked = s.include_anthropic;
  $('enabledStat').textContent = s.enabled ? '已启用' : '已关闭';
  $('thresholdStat').textContent = pct(s.threshold_percent);
  $('intervalStat').textContent = `${s.scan_interval_seconds || 0}s`;
  $('lastScanStat').textContent = fmt(s.last_scan_at);
  $('triggeredStat').textContent = `${s.last_scan_triggered || 0} / ${s.last_scan_scanned || 0}`;
}
function renderSleeping(items){
  $('sleepingBody').innerHTML = items.length ? items.map(e=>`<tr><td>${escapeHtml(e.account_id)}</td><td>${escapeHtml(e.account_name)}</td><td>${escapeHtml(e.platform)}</td><td>${escapeHtml(e.window_name)}</td><td>${pct(e.utilization_percent)}</td><td>${fmt(e.reset_at)}</td></tr>`).join('') : '<tr><td colspan="6">暂无</td></tr>';
}
function renderEvents(items){
  $('eventsBody').innerHTML = items.length ? items.map(e=>`<tr><td>${fmt(e.created_at)}</td><td>${escapeHtml(e.account_id)}</td><td>${escapeHtml(e.account_name)}</td><td>${escapeHtml(e.platform)}</td><td>${escapeHtml(e.window_name)}</td><td>${pct(e.utilization_percent)}</td><td>${pct(e.threshold_percent)}</td><td>${fmt(e.reset_at)}</td></tr>`).join('') : '<tr><td colspan="8">暂无</td></tr>';
}
async function load(){
  const st = await api('api/status');
  fillSettings(st); renderSleeping(st.sleeping_accounts || []);
  renderEvents(await api('api/events?limit=50'));
}
async function save(){
  const body = {
    enabled: $('enabled').checked,
    threshold_percent: Number($('threshold').value),
    scan_interval_seconds: Number($('interval').value),
    include_openai: $('includeOpenai').checked,
    include_anthropic: $('includeAnthropic').checked,
  };
  fillSettings(await api('api/settings', { method:'PUT', body: JSON.stringify(body) }));
  msg('配置已保存'); await load();
}
async function scan(){
  const r = await api('api/scan-once', { method:'POST' });
  msg(`扫描完成：扫描 ${r.scanned} 个，触发 ${r.triggered} 个`);
  await load();
}
$('refreshBtn').onclick = () => load().catch(e=>msg(e.message,true));
$('saveBtn').onclick = () => save().catch(e=>msg(e.message,true));
$('scanBtn').onclick = () => scan().catch(e=>msg(e.message,true));
load().catch(e=>msg(e.message,true));
