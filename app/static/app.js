const headers = () => ({ 'Content-Type': 'application/json' });
const $ = id => document.getElementById(id);
const PAGE_SIZE = 10;
const state = { accountsPage: 1, sleepingPage: 1, eventsPage: 1 };

function normalizeBasePath(value){
  const raw = String(value || '').trim();
  if(!raw || raw === '/') return '';
  const withSlash = raw.startsWith('/') ? raw : `/${raw}`;
  return withSlash.replace(/\/+$/, '');
}

const runtimeConfig = window.__OAUTH_SLEEPER_CONFIG__ || {};
const basePath = normalizeBasePath(runtimeConfig.basePath);

function joinBasePath(path){
  const cleanPath = path.startsWith('/') ? path : `/${path}`;
  return basePath ? `${basePath}${cleanPath}` : cleanPath;
}

function fmt(t){ return t ? new Date(t).toLocaleString() : '-'; }
function pct(v){ return `${Number(v || 0).toFixed(2)}%`; }
function esc(v){ return String(v ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
function msg(s, bad=false){ const el=$('message'); el.textContent=s; el.style.color=bad?'#b91c1c':'#065f46'; }
async function api(path, opts={}){
  const r = await fetch(joinBasePath(path), { ...opts, headers: { ...headers(), ...(opts.headers||{}) }});
  if(!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return await r.json();
}
function fillSettings(s){
  $('enabled').checked = s.enabled;
  $('threshold').value = s.threshold_percent;
  $('interval').value = s.scan_interval_seconds;
  $('maxSleep').value = s.max_sleep_per_scan;
  $('includeOpenai').checked = s.include_openai;
  $('includeAnthropic').checked = s.include_anthropic;
  $('enabledStat').textContent = s.enabled ? '已启用' : '已关闭';
  $('thresholdStat').textContent = pct(s.threshold_percent);
  $('intervalStat').textContent = `${s.scan_interval_seconds || 0}s`;
  $('lastScanStat').textContent = fmt(s.last_scan_at);
  $('triggeredStat').textContent = `${s.last_scan_triggered || 0} / ${s.last_scan_scanned || 0}`;
  $('sleepingCountStat').textContent = s.sleeping_count ?? 0;
}
function updatePager(prefix, meta){
  const totalPages = meta?.total_pages || 1;
  const page = Math.min(meta?.page || 1, totalPages);
  $(`${prefix}Total`).textContent = `共 ${meta?.total || 0} 条`;
  $(`${prefix}PageInfo`).textContent = `第 ${page} / ${totalPages} 页，每页最多 ${meta?.page_size || PAGE_SIZE} 条`;
  $(`${prefix}Prev`).disabled = page <= 1;
  $(`${prefix}Next`).disabled = page >= totalPages;
}
function renderSleepingPage(pageData){
  const items = pageData.items || [];
  $('sleepingBody').innerHTML = items.length ? items.map(e=>`<tr><td>${e.account_id}</td><td>${esc(e.account_name)}</td><td>${esc(e.platform)}</td><td>${esc(e.window_name)}</td><td>${pct(e.utilization_percent)}</td><td>${fmt(e.reset_at)}</td></tr>`).join('') : '<tr><td colspan="6">暂无</td></tr>';
  updatePager('sleeping', pageData.meta || {total:0,page:1,page_size:PAGE_SIZE,total_pages:1});
}
function renderAccountsPage(pageData){
  const items = pageData.items || [];
  $('accountsBody').innerHTML = items.length ? items.map(a=>{
    const button = a.is_whitelisted
      ? `<button class="secondary" onclick="removeWhitelist(${a.id})">移出白名单</button>`
      : `<button class="secondary" onclick="addWhitelist(${a.id})">加入白名单</button>`;
    return `<tr><td>${a.id}</td><td>${esc(a.name)}</td><td>${esc(a.platform)}</td><td>${esc(a.status)}</td><td>${fmt(a.rate_limit_reset_at)}</td><td>${a.is_whitelisted ? '是' : '否'}</td><td>${button}</td></tr>`;
  }).join('') : '<tr><td colspan="7">暂无</td></tr>';
  updatePager('accounts', pageData.meta || {total:0,page:1,page_size:PAGE_SIZE,total_pages:1});
}
function renderEventsPage(pageData){
  const items = pageData.items || [];
  $('eventsBody').innerHTML = items.length ? items.map(e=>`<tr><td>${fmt(e.created_at)}</td><td>${e.account_id}</td><td>${esc(e.account_name)}</td><td>${esc(e.platform)}</td><td>${esc(e.window_name)}</td><td>${pct(e.utilization_percent)}</td><td>${pct(e.threshold_percent)}</td><td>${fmt(e.reset_at)}</td></tr>`).join('') : '<tr><td colspan="8">暂无</td></tr>';
  updatePager('events', pageData.meta || {total:0,page:1,page_size:PAGE_SIZE,total_pages:1});
}
async function loadStatus(){ fillSettings(await api('api/status')); }
async function loadAccounts(){ renderAccountsPage(await api(`api/accounts?page=${state.accountsPage}&page_size=${PAGE_SIZE}`)); }
async function loadSleeping(){ renderSleepingPage(await api(`api/sleeping-accounts?page=${state.sleepingPage}&page_size=${PAGE_SIZE}`)); }
async function loadEvents(){ renderEventsPage(await api(`api/events?page=${state.eventsPage}&page_size=${PAGE_SIZE}`)); }
async function load(){ await loadStatus(); await Promise.all([loadAccounts(), loadSleeping(), loadEvents()]); }
async function save(){
  const body = {
    enabled: $('enabled').checked,
    threshold_percent: Number($('threshold').value),
    scan_interval_seconds: Number($('interval').value),
    max_sleep_per_scan: Number($('maxSleep').value),
    include_openai: $('includeOpenai').checked,
    include_anthropic: $('includeAnthropic').checked,
  };
  fillSettings(await api('api/settings', { method:'PUT', body: JSON.stringify(body) }));
  msg('配置已保存'); state.accountsPage = 1; state.sleepingPage = 1; state.eventsPage = 1; await load();
}
async function scan(){
  const r = await api('api/scan-once', { method:'POST' });
  msg(`扫描完成：扫描 ${r.scanned} 个，触发 ${r.triggered} 个`);
  state.accountsPage = 1; state.sleepingPage = 1; state.eventsPage = 1; await load();
}
async function addWhitelist(accountId){
  await api(`api/whitelist/${accountId}`, { method:'POST' });
  msg(`已加入白名单：账号 ID ${accountId}`);
  await Promise.all([loadStatus(), loadAccounts(), loadSleeping()]);
}
async function removeWhitelist(accountId){
  await api(`api/whitelist/${accountId}`, { method:'DELETE' });
  msg(`已移出白名单：账号 ID ${accountId}`);
  await Promise.all([loadStatus(), loadAccounts(), loadSleeping()]);
}
$('refreshBtn').onclick = () => load().catch(e=>msg(e.message,true));
$('saveBtn').onclick = () => save().catch(e=>msg(e.message,true));
$('scanBtn').onclick = () => scan().catch(e=>msg(e.message,true));
$('accountsPrev').onclick = () => { if(state.accountsPage > 1){ state.accountsPage--; loadAccounts().catch(e=>msg(e.message,true)); } };
$('accountsNext').onclick = () => { state.accountsPage++; loadAccounts().catch(e=>{ state.accountsPage--; msg(e.message,true); }); };
$('sleepingPrev').onclick = () => { if(state.sleepingPage > 1){ state.sleepingPage--; loadSleeping().catch(e=>msg(e.message,true)); } };
$('sleepingNext').onclick = () => { state.sleepingPage++; loadSleeping().catch(e=>{ state.sleepingPage--; msg(e.message,true); }); };
$('eventsPrev').onclick = () => { if(state.eventsPage > 1){ state.eventsPage--; loadEvents().catch(e=>msg(e.message,true)); } };
$('eventsNext').onclick = () => { state.eventsPage++; loadEvents().catch(e=>{ state.eventsPage--; msg(e.message,true); }); };
window.addWhitelist = accountId => addWhitelist(accountId).catch(e=>msg(e.message,true));
window.removeWhitelist = accountId => removeWhitelist(accountId).catch(e=>msg(e.message,true));
load().catch(e=>msg(e.message,true));
