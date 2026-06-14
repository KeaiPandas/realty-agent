// Realty Agent 移动端逻辑
// 数据源：复用现有 /api/leads/* 与 /api/bot/* 接口；接口不可达时自动回退演示数据
const API = location.origin;
let DEMO = false;
const store = { leads: [], customers: {}, cat: 'active' };

async function api(path, opts){
  const r = await fetch(API + path, opts);
  if(!r.ok) throw new Error(path + ' ' + r.status);
  return r.json();
}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function avClass(i){return ['','b','g'][i%3];}
function initial(name){return (name||'?').trim().charAt(0);}
function timeAgo(ts){
  if(!ts) return '未知';
  const t = typeof ts==='number' ? (ts>1e12?ts/1000:ts) : Date.parse(ts)/1000;
  if(!t) return String(ts);
  const d = Date.now()/1000 - t;
  if(d<60) return '刚刚';
  if(d<3600) return Math.floor(d/60)+'分钟前';
  if(d<86400) return Math.floor(d/3600)+'小时前';
  return Math.floor(d/86400)+'天前';
}

/* ---------- 看板 ---------- */
async function loadBoard(){
  try{
    const [stats, brief, acts, risk] = await Promise.all([
      api('/api/leads/stats'), api('/api/leads/briefing'),
      api('/api/leads/actions'), api('/api/leads/risk')
    ]);
    DEMO=false; renderKpi(stats.kpi); renderBrief(brief);
    renderTodos(acts.actions||[]); renderRisk((risk.leads||[]).slice(0,5));
    store.leads = risk.leads||[];
  }catch(e){ DEMO=true; demoBoard(); }
  document.getElementById('demoBadge').classList.toggle('show', DEMO);
}
function renderKpi(k){
  k=k||{};
  const cells=[
    ['accent', k.active_customers, '活跃客户'],
    ['', k.new_messages_today, '今日新消息'],
    ['danger', k.pending_reply, '待回复'],
    ['', k.silent_customers, '沉默客户'],
  ];
  document.getElementById('kpiGrid').innerHTML = cells.map(([c,n,l])=>
    `<div class="kpi ${c}"><div class="num">${n??0}</div><div class="lbl">${l}</div></div>`).join('');
}
function renderBrief(b){
  const txt = b && (b.summary||b.content) || '今日暂无简报,运行同步后由 AI 生成。';
  document.getElementById('briefWrap').innerHTML =
    `<div class="brief"><div class="bh"><span class="ico">&#10024;</span> AI 每日摘要 · ${esc(b&&b.date||'')}</div><p>${esc(txt)}</p></div>`;
}
function renderTodos(list){
  const w=document.getElementById('todoWrap');
  if(!list.length){w.innerHTML='<div class="empty">暂无紧急待办</div>';return;}
  w.innerHTML = list.slice(0,6).map(a=>{
    const done = a.status && a.status!=='pending';
    return `<div class="todo ${done?'done':''}" onclick="doAction(this,${a.id})">
      <div class="chk ico">&#10003;</div>
      <div class="body"><div class="t">${esc(a.description||a.action_type||'待办')}</div>
      <div class="meta"><span class="pill ${a.priority||'low'}">${({high:'高优先',medium:'中',low:'常规'})[a.priority]||'常规'}</span>${esc(a.ai_suggestion||a.nickname||'')}</div></div></div>`;
  }).join('');
}
async function doAction(el,id){
  const done = el.classList.toggle('done');
  toast(done?'已标记完成':'已恢复');
  if(DEMO||!id) return;
  try{ await api('/api/leads/actions/'+id+'/'+(done?'done':'skip'),{method:'POST'}); }catch(e){}
}
function renderRisk(list){
  const w=document.getElementById('riskWrap');
  if(!list.length){w.innerHTML='<div class="empty">暂无线索</div>';return;}
  w.innerHTML = list.map((l,i)=>leadCard(l,i,true)).join('');
}
function leadCard(l,i,withSummary){
  const kp=l.key_profile||{};
  const tags=[];
  if(l.stage==='intent')tags.push('高意向'); else if(l.stage==='showing')tags.push('带看中'); else if(l.stage==='closed')tags.push('已成交');
  if(kp.budget)tags.push('预算'+kp.budget+'万');
  if(kp.area)tags.push(kp.area);
  if(kp.purpose)tags.push(kp.purpose);
  if(l.silence_days>7)tags.push(l.silence_days+'天未联系');
  const tagHtml = (tags.length?tags:['未分组']).map(t=>`<span class="tag">${esc(t)}</span>`).join('');
  const sum = withSummary && (l.risk_reasons&&l.risk_reasons.join('·')) ;
  return `<div class="lead" onclick="openDetail('${esc(l.wxid)}')">
    <div class="row1"><div class="avatar ${avClass(i)}">${esc(initial(l.nickname))}</div>
    <div class="nm"><div class="n">${esc(l.nickname||l.wxid)} <span class="riskdot ${l.risk_level||'low'}"></span></div>
    <div class="s">${esc((kp.area||'未知区域'))} · ${l.message_count||0}条 · ${timeAgo(l.last_message_time)}</div></div></div>
    <div class="tags">${tagHtml}</div>
    ${sum?`<div class="sm">${esc(sum)}</div>`:''}</div>`;
}

/* ---------- 客户列表 ---------- */
const CATS=[['active','活跃'],['pending','待回复'],['silent','沉默'],['messages','按消息']];
function renderChips(){
  document.getElementById('catChips').innerHTML = CATS.map(([k,l])=>
    `<span class="chip ${k===store.cat?'on':''}" onclick="selCat('${k}')">${l}</span>`).join('');
}
async function selCat(c){store.cat=c;renderChips();loadLeads();}
async function loadLeads(){
  const w=document.getElementById('leadsWrap');
  w.innerHTML='<div class="skel"></div><div class="skel"></div><div class="skel"></div>';
  try{
    const d=await api('/api/leads/customers?cat='+store.cat);
    const list=d.customers||[];
    if(!list.length){w.innerHTML='<div class="empty">该分类暂无客户</div>';return;}
    list.forEach(c=>store.customers[c.wxid]=c);
    w.innerHTML=list.map((c,i)=>custCard(c,i)).join('');
  }catch(e){ DEMO=true; document.getElementById('demoBadge').classList.add('show'); demoLeads(); }
}
function custCard(c,i){
  const tags=(c.tags||[]).slice(0,4).map(t=>`<span class="tag">${esc(t)}</span>`).join('');
  return `<div class="lead" onclick="openDetail('${esc(c.wxid)}')">
    <div class="row1"><div class="avatar ${avClass(i)}">${esc(initial(c.name))}</div>
    <div class="nm"><div class="n">${esc(c.name)} <span class="riskdot ${c.risk||'low'}"></span></div>
    <div class="s">${c.messages||0} 条消息 · ${esc(c.lastActive||'')}</div></div></div>
    <div class="tags">${tags}</div>
    ${c.summary?`<div class="sm">${esc(c.summary)}</div>`:''}</div>`;
}

/* ---------- 客户明细 ---------- */
function openDetail(wxid){
  const c = store.customers[wxid] || store.leads.find(l=>l.wxid===wxid) || {wxid,name:wxid};
  const name = c.name||c.nickname||wxid;
  const kp = c.key_profile||{};
  const rows=[
    ['意向区域', kp.area || (c.tags||[]).find(t=>!/万|意向|沉默|新线索|成交|带看/.test(t)) || '—'],
    ['购房预算', kp.budget?kp.budget+' 万':'—'],
    ['购房目的', kp.purpose||'—'],
    ['客户阶段', ({initial:'初步接触',intent:'高意向',showing:'带看中',closed:'已成交'})[c.stage]||c.stage||'—'],
    ['风险等级', ({high:'高 · 需尽快跟进',medium:'中',low:'低'})[c.risk||c.risk_level]||'低'],
    ['消息总数', (c.messages||c.message_count||0)+' 条'],
  ];
  const reasons = (c.risk_reasons||[]).join(';') || c.summary || '暂无足够沟通记录,建议主动跟进了解需求。';
  document.getElementById('sheetBody').innerHTML=`
    <div class="profhead"><div class="avatar">${esc(initial(name))}</div>
    <div><div class="n">${esc(name)}</div><div class="s">微信 ${esc(wxid)}</div></div></div>
    <div class="kv">${rows.map(([k,v])=>`<div class="k">${k}</div><div class="v">${esc(v)}</div>`).join('')}</div>
    <div class="block-title">AI 画像 / 跟进建议</div>
    <div class="aibox">${esc(reasons)}</div>
    <div class="block-title">操作</div>
    <div class="aibox" style="display:flex;gap:8px;padding:11px">
      <button class="btn primary" onclick="switchTo('bot');closeDetail()">去 Bot 回复</button>
      <button class="btn" onclick="toast('已加入今日跟进')">加入跟进</button>
    </div>`;
  document.getElementById('sheet').classList.add('open');
}
function closeDetail(){document.getElementById('sheet').classList.remove('open');}

/* ---------- Bot 审批 ---------- */
async function loadBot(){
  try{
    const [st, convs]=await Promise.all([api('/api/bot/status'),api('/api/bot/conversations')]);
    DEMO=false;
    document.getElementById('botModeLabel').textContent = st.running?('运行中 · '+((st.global_settings||{}).mode||'')):'已停止';
    document.getElementById('botKpi').innerHTML=
      `<div class="kpi accent"><div class="num">${st.pending_replies||0}</div><div class="lbl">待审批回复</div></div>
       <div class="kpi"><div class="num">${st.active_conversations||0}</div><div class="lbl">活跃会话</div></div>`;
    const pend=(convs||[]).filter(c=>c.pending_reply);
    renderBot(pend);
  }catch(e){ DEMO=true; document.getElementById('demoBadge').classList.add('show'); demoBot(); }
}
function renderBot(list){
  const w=document.getElementById('botWrap');
  if(!list.length){w.innerHTML='<div class="empty">暂无待审批回复 &#10003;</div>';return;}
  w.innerHTML=list.map((c,i)=>{
    const p=c.pending_reply;
    return `<div class="conv" data-wxid="${esc(c.wxid)}">
      <div class="ch"><div class="avatar ${avClass(i)}">${esc(initial(c.nickname))}</div>
      <div class="nm"><div class="n">${esc(c.nickname||c.wxid)}</div><div class="s">${timeAgo(p.timestamp)}</div></div>
      <span class="pill high">待审批</span></div>
      <div class="bubble in">${esc(p.content)}</div>
      <div class="ai-draft"><div class="lbl"><span class="ico">&#10024;</span> AI 生成回复</div>
      <div class="txt" contenteditable="true">${esc(p.reply)}</div>
      <div class="btns">
        <button class="btn ghost" onclick="botReject(this)">忽略</button>
        <button class="btn primary" onclick="botApprove(this)">通过并发送</button>
      </div></div></div>`;
  }).join('');
}
async function botApprove(b){
  const conv=b.closest('.conv'), wxid=conv.dataset.wxid;
  const edited=conv.querySelector('.txt').innerText.trim();
  conv.style.transition='.3s';conv.style.opacity='.4';
  try{
    if(!DEMO) await api('/api/bot/conversations/'+encodeURIComponent(wxid)+'/approve',
      {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({edited_reply:edited})});
    toast('已发送 · 模拟真人节奏分段发出');
  }catch(e){toast('发送失败:'+e.message);conv.style.opacity='1';return;}
  conv.style.opacity='0';conv.style.transform='scale(.96)';setTimeout(()=>{conv.remove();bumpBot(-1);},300);
}
async function botReject(b){
  const conv=b.closest('.conv'), wxid=conv.dataset.wxid;
  conv.style.transition='.3s';conv.style.opacity='0';
  try{ if(!DEMO) await api('/api/bot/conversations/'+encodeURIComponent(wxid)+'/reject',{method:'POST'}); }catch(e){}
  toast('已忽略,不发送');setTimeout(()=>{conv.remove();bumpBot(-1);},300);
}
function bumpBot(d){const k=document.querySelector('#botKpi .kpi.accent .num');if(k)k.textContent=Math.max(0,(parseInt(k.textContent)||0)+d);}

/* ---------- 导航 ---------- */
function switchView(el){
  if(el.dataset.v==='me')return;
  switchTo(el.dataset.v);
}
function switchTo(v){
  document.querySelectorAll('.nav a').forEach(a=>a.classList.toggle('on',a.dataset.v===v));
  document.querySelectorAll('.view').forEach(s=>s.classList.remove('active'));
  document.getElementById('view-'+v).classList.add('active');
  document.querySelector('.screen').scrollTop=0;
  if(v==='leads')loadLeads();
  if(v==='bot')loadBot();
}
function refreshAll(){toast('刷新中…');loadBoard();if(document.getElementById('view-leads').classList.contains('active'))loadLeads();if(document.getElementById('view-bot').classList.contains('active'))loadBot();}
let tT;function toast(m){const t=document.getElementById('toast');t.innerHTML=m;t.classList.add('show');clearTimeout(tT);tT=setTimeout(()=>t.classList.remove('show'),1900);}

/* ---------- 演示数据兜底 ---------- */
function demoBoard(){
  renderKpi({active_customers:128,new_messages_today:37,pending_reply:9,silent_customers:23});
  renderBrief({date:'演示',summary:'今日共 37 条新消息,3 位高意向客户活跃。王女士明确看房意向(预算 380 万,意向滨江),建议今日约带看;陈先生已沉默 9 天,有流失风险,建议主动跟进。'});
  renderTodos([
    {id:0,description:'回复王女士的看房意向',priority:'high',ai_suggestion:'预算380万·滨江·刚刚',status:'pending'},
    {id:0,description:'跟进沉默 9 天的陈先生',priority:'medium',ai_suggestion:'改善型·流失预警',status:'pending'},
    {id:0,description:'发送江南里户型图给李先生',priority:'low',ai_suggestion:'已处理',status:'done'},
  ]);
  store.leads=DEMO_LEADS;
  renderRisk(DEMO_LEADS);
}
function demoLeads(){
  const w=document.getElementById('leadsWrap');
  DEMO_LEADS.forEach(l=>store.customers[l.wxid]={wxid:l.wxid,name:l.nickname,messages:l.message_count,lastActive:'演示',tags:[l.key_profile.area,'预算'+l.key_profile.budget+'万'],risk:l.risk_level,stage:l.stage,key_profile:l.key_profile,summary:l.risk_reasons.join('·')});
  w.innerHTML=DEMO_LEADS.map((l,i)=>custCard(store.customers[l.wxid],i)).join('');
}
function demoBot(){
  document.getElementById('botModeLabel').textContent='演示 · semi_auto';
  document.getElementById('botKpi').innerHTML='<div class="kpi accent"><div class="num">2</div><div class="lbl">待审批回复</div></div><div class="kpi"><div class="num">12</div><div class="lbl">活跃会话</div></div>';
  renderBot([
    {wxid:'demo_wang',nickname:'王女士',pending_reply:{content:'这个滨江的房子周末能约看吗?我周六有空',reply:'王姐好~周六完全没问题!我帮您约滨江花园这套,上午10点方便吗?顺便带您看同小区另一套高楼层的一起对比下',timestamp:Date.now()/1000}},
    {wxid:'demo_li',nickname:'李先生',pending_reply:{content:'江南里那套首付大概多少?',reply:'李哥,江南里这套总价258万,按首套30%算首付约77万,贷款181万、30年月供约1万。我整理份测算表发您参考~',timestamp:Date.now()/1000-480}},
  ]);
}
const DEMO_LEADS=[
  {wxid:'demo_wang',nickname:'王女士',stage:'intent',risk_level:'high',risk_reasons:['明确看房意向,关注学区与楼层,建议今日约带看锁定'],last_message_time:Date.now()/1000-120,silence_days:0,key_profile:{budget:380,area:'滨江',purpose:'改善自住'},message_count:62},
  {wxid:'demo_chen',nickname:'陈先生',stage:'initial',risk_level:'medium',risk_reasons:['9天未联系,有流失风险,可用新房源重新激活'],last_message_time:Date.now()/1000-9*86400,silence_days:9,key_profile:{budget:500,area:'城西',purpose:'改善'},message_count:28},
  {wxid:'demo_litao',nickname:'李先生',stage:'showing',risk_level:'low',risk_reasons:['带看中,关注首付与月供测算'],last_message_time:Date.now()/1000-7200,silence_days:0,key_profile:{budget:260,area:'江南里',purpose:'首套'},message_count:41},
  {wxid:'demo_zhao',nickname:'赵小姐',stage:'initial',risk_level:'low',risk_reasons:['新线索,投资需求,预算待明确'],last_message_time:Date.now()/1000-86400,silence_days:1,key_profile:{budget:'',area:'',purpose:'投资'},message_count:15},
];

renderChips();
loadBoard();
