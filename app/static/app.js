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

function cell(label, value, className=''){
  const cls = className ? ` class="${className}"` : '';
  return `<td data-label="${esc(label)}"${cls}>${value}</td>`;
}

function chip(text, tone='neutral'){
  return `<span class="chip chip--${tone}">${esc(text)}</span>`;
}

function accountCell(name){
  const safe = esc(name || '-');
  return `<span class="accountName" title="${safe}">${safe}</span>`;
}

function meter(value){
  const num = Math.max(0, Math.min(100, Number(value || 0)));
  return `<span class="meter"><span class="meter__track"><span class="meter__bar" style="--pct:${num}%"></span></span><span>${pct(num)}</span></span>`;
}

function msg(text, tone='success'){
  const el = $('message');
  el.textContent = text || '';
  el.className = text ? `message is-visible is-${tone}` : 'message';
}

function setBusy(buttonId, busy, label){
  const button = $(buttonId);
  if(!button) return;
  if(!button.dataset.defaultLabel) button.dataset.defaultLabel = button.textContent;
  button.disabled = busy;
  button.textContent = busy ? label : button.dataset.defaultLabel;
}

async function withBusy(buttonId, label, task){
  setBusy(buttonId, true, label);
  try {
    return await task();
  } finally {
    setBusy(buttonId, false, label);
  }
}

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

  const enabledStat = $('enabledStat');
  enabledStat.textContent = s.enabled ? '自动休眠已启用' : '自动休眠已关闭';
  enabledStat.className = `statePill ${s.enabled ? 'statePill--enabled' : 'statePill--disabled'}`;

  $('writeGuardTitle').textContent = s.enabled ? '扫描器会在命中阈值时写入休眠字段.' : '扫描器当前不会自动写入休眠字段.';
  $('writeGuardText').textContent = s.enabled
    ? `当前阈值 ${pct(s.threshold_percent)}，每 ${s.scan_interval_seconds || 0} 秒检查一次，单轮最多休眠 ${s.max_sleep_per_scan ?? 0} 个账号。`
    : '配置已加载，但主动休眠处于关闭状态。手动扫描仍会按当前策略执行一次检查。';

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
  $(`${prefix}PageInfo`).textContent = `第 ${page} / ${totalPages} 页`;
  $(`${prefix}Prev`).disabled = page <= 1;
  $(`${prefix}Next`).disabled = page >= totalPages;
}

function renderSleepingPage(pageData){
  const items = pageData.items || [];
  $('sleepingBody').innerHTML = items.length ? items.map(e=>`<tr>
    ${cell('ID', esc(e.account_id), 'mono')}
    ${cell('账号', accountCell(e.account_name))}
    ${cell('平台', chip(e.platform || '-', 'neutral'))}
    ${cell('窗口', esc(e.window_name || '-'))}
    ${cell('使用率', meter(e.utilization_percent))}
    ${cell('休眠到', esc(fmt(e.reset_at)))}
  </tr>`).join('') : '<tr class="emptyRow"><td colspan="6">暂无插件记录的休眠账号。</td></tr>';
  updatePager('sleeping', pageData.meta || {total:0,page:1,page_size:PAGE_SIZE,total_pages:1});
}

function renderAccountsPage(pageData){
  const items = pageData.items || [];
  $('accountsBody').innerHTML = items.length ? items.map(a=>{
    const whitelistTone = a.is_whitelisted ? 'warning' : 'success';
    const whitelistText = a.is_whitelisted ? '已跳过' : '受控';
    const button = a.is_whitelisted
      ? `<button class="button whitelistRemoveBtn" type="button" onclick="removeWhitelist(${a.id})">移出白名单</button>`
      : `<button class="button whitelistAddBtn" type="button" onclick="addWhitelist(${a.id})">加入白名单</button>`;
    return `<tr>
      ${cell('ID', esc(a.id), 'mono')}
      ${cell('账号', accountCell(a.name))}
      ${cell('平台', chip(a.platform || '-', 'neutral'))}
      ${cell('状态', chip(a.status || '-', a.status === 'active' ? 'success' : 'warning'))}
      ${cell('当前休眠到', esc(fmt(a.rate_limit_reset_at)))}
      ${cell('白名单', chip(whitelistText, whitelistTone))}
      ${cell('操作', `<span class="rowActions">${button}</span>`)}
    </tr>`;
  }).join('') : '<tr class="emptyRow"><td colspan="7">暂无可休眠 OAuth 账号，当前筛选条件下没有 active OAuth 账号。</td></tr>';
  updatePager('accounts', pageData.meta || {total:0,page:1,page_size:PAGE_SIZE,total_pages:1});
}

function renderEventsPage(pageData){
  const items = pageData.items || [];
  $('eventsBody').innerHTML = items.length ? items.map(e=>`<tr>
    ${cell('时间', esc(fmt(e.created_at)))}
    ${cell('ID', esc(e.account_id), 'mono')}
    ${cell('账号', accountCell(e.account_name))}
    ${cell('平台', chip(e.platform || '-', 'neutral'))}
    ${cell('窗口', esc(e.window_name || '-'))}
    ${cell('使用率', meter(e.utilization_percent))}
    ${cell('阈值', esc(pct(e.threshold_percent)))}
    ${cell('休眠到', esc(fmt(e.reset_at)))}
  </tr>`).join('') : '<tr class="emptyRow"><td colspan="8">暂无扫描事件。</td></tr>';
  updatePager('events', pageData.meta || {total:0,page:1,page_size:PAGE_SIZE,total_pages:1});
}

async function loadStatus(){ fillSettings(await api('api/status')); }
async function loadAccounts(){ renderAccountsPage(await api(`api/accounts?page=${state.accountsPage}&page_size=${PAGE_SIZE}`)); }
async function loadSleeping(){ renderSleepingPage(await api(`api/sleeping-accounts?page=${state.sleepingPage}&page_size=${PAGE_SIZE}`)); }
async function loadEvents(){ renderEventsPage(await api(`api/events?page=${state.eventsPage}&page_size=${PAGE_SIZE}`)); }
async function load(){ await loadStatus(); await Promise.all([loadAccounts(), loadSleeping(), loadEvents()]); }

async function refresh(){
  await withBusy('refreshBtn', '刷新中', async () => {
    await load();
    msg('状态已刷新', 'success');
  });
}

async function save(){
  await withBusy('saveBtn', '保存中', async () => {
    const body = {
      enabled: $('enabled').checked,
      threshold_percent: Number($('threshold').value),
      scan_interval_seconds: Number($('interval').value),
      max_sleep_per_scan: Number($('maxSleep').value),
      include_openai: $('includeOpenai').checked,
      include_anthropic: $('includeAnthropic').checked,
    };
    fillSettings(await api('api/settings', { method:'PUT', body: JSON.stringify(body) }));
    msg('配置已保存，列表已重新加载。', 'success');
    state.accountsPage = 1; state.sleepingPage = 1; state.eventsPage = 1;
    await load();
  });
}

async function scan(){
  await withBusy('scanBtn', '扫描中', async () => {
    msg('正在执行一次手动扫描，可能写入 Sub2API 数据库。', 'loading');
    const r = await api('api/scan-once', { method:'POST' });
    msg(`扫描完成：扫描 ${r.scanned} 个账号，触发 ${r.triggered} 个休眠。`, 'success');
    state.accountsPage = 1; state.sleepingPage = 1; state.eventsPage = 1;
    await load();
  });
}

const addWhitelistAction = async accountId => {
  await api(`api/whitelist/${accountId}`, { method:'POST' });
  msg(`已加入白名单：账号 ID ${accountId} 后续会被主动休眠扫描跳过。`, 'success');
  await Promise.all([loadStatus(), loadAccounts(), loadSleeping()]);
};

const removeWhitelistAction = async accountId => {
  await api(`api/whitelist/${accountId}`, { method:'DELETE' });
  msg(`已移出白名单：账号 ID ${accountId} 会重新纳入主动休眠扫描。`, 'success');
  await Promise.all([loadStatus(), loadAccounts(), loadSleeping()]);
};

$('refreshBtn').onclick = () => refresh().catch(e=>msg(e.message,'error'));
$('saveBtn').onclick = () => save().catch(e=>msg(e.message,'error'));
$('scanBtn').onclick = () => scan().catch(e=>msg(e.message,'error'));
$('accountsPrev').onclick = () => { if(state.accountsPage > 1){ state.accountsPage--; loadAccounts().catch(e=>msg(e.message,'error')); } };
$('accountsNext').onclick = () => { state.accountsPage++; loadAccounts().catch(e=>{ state.accountsPage--; msg(e.message,'error'); }); };
$('sleepingPrev').onclick = () => { if(state.sleepingPage > 1){ state.sleepingPage--; loadSleeping().catch(e=>msg(e.message,'error')); } };
$('sleepingNext').onclick = () => { state.sleepingPage++; loadSleeping().catch(e=>{ state.sleepingPage--; msg(e.message,'error'); }); };
$('eventsPrev').onclick = () => { if(state.eventsPage > 1){ state.eventsPage--; loadEvents().catch(e=>msg(e.message,'error')); } };
$('eventsNext').onclick = () => { state.eventsPage++; loadEvents().catch(e=>{ state.eventsPage--; msg(e.message,'error'); }); };
window.addWhitelist = accountId => addWhitelistAction(accountId).catch(e=>msg(e.message,'error'));
window.removeWhitelist = accountId => removeWhitelistAction(accountId).catch(e=>msg(e.message,'error'));
load().catch(e=>msg(e.message,'error'));
