const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const newSessionId=()=>(crypto.randomUUID?crypto.randomUUID():String(Date.now()+Math.random())).slice(0,64);

/* ---- 安全存储：localStorage 不可用时降级为内存态 ---- */
const memoryStore={};
const store={
  get(key){try{return JSON.parse(localStorage.getItem(key))}catch{if(key in memoryStore)return memoryStore[key];return null}},
  set(key,val){try{localStorage.setItem(key,JSON.stringify(val))}catch{memoryStore[key]=val}}
};
const SESSIONS_KEY='ai.sessions.v1',REPORTS_KEY='ai.reports.v1',LAST_VIEW_KEY='ai.lastview',ACTIVE_JOB_KEY='ai.activejob';
const MAX_SESSIONS=5,MAX_REPORTS=10;

let sessionId=newSessionId();
let currentSession=null;                 // 当前会话记录（持久化对象）

let sessions=Array.isArray(store.get(SESSIONS_KEY))?store.get(SESSIONS_KEY):[];
let reports=Array.isArray(store.get(REPORTS_KEY))?store.get(REPORTS_KEY):[];


/* ---- Markdown 渲染（先转义再排版，模型输出视为不可信） ---- */
function inlineMd(t){return t
  .replace(/`([^`]+)`/g,'<code class="md-code-inline">$1</code>')
  .replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>')
  .replace(/(^|[^*])\*([^*\n]+)\*/g,'$1<em>$2</em>')
  .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,'<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')}
function mdTable(rows){
  const cells=r=>r.trim().replace(/^\||\|$/g,'').split('|').map(c=>c.trim());
  const head=cells(rows[0]);
  const body=rows.slice(2).map(cells);
  return '<table class="md-table"><thead><tr>'+head.map(h=>'<th>'+inlineMd(h)+'</th>').join('')+'</tr></thead><tbody>'+
    body.map(r=>'<tr>'+r.map(c=>'<td>'+inlineMd(c)+'</td>').join('')+'</tr>').join('')+'</tbody></table>'}
function renderMarkdown(src){
  const text=esc(src||'');
  const chunks=text.split(/```/);
  let out='';
  chunks.forEach((chunk,i)=>{
    if(i%2===1){out+='<pre class="md-code">'+chunk.replace(/^[a-zA-Z]*\n/,'')+'</pre>';return}
    out+=renderMdText(chunk);
  });
  return out}
function renderMdText(t){
  const lines=t.split(/\r?\n/);
  let html='',list=null,para=[],table=[];
  const closeList=()=>{if(list){html+='</'+list+'>';list=null}};
  const flushPara=()=>{if(para.length){html+='<p>'+inlineMd(para.join('\n')).replace(/\n/g,'<br>')+'</p>';para=[]}};
  const flushTable=()=>{if(table.length){html+=mdTable(table);table=[]}};
  for(const raw of lines){
    const line=raw.trimEnd();
    if(/^\s*\|.*\|\s*$/.test(line)){flushPara();closeList();table.push(line.trim());continue}
    if(table.length&&!/^\s*\|.*\|\s*$/.test(line)){flushTable()}
    if(!line.trim()){flushPara();closeList();continue}
    let m;
    if((m=line.match(/^(#{1,6})\s+(.*)$/))){flushPara();closeList();const lv=Math.min(m[1].length+2,6);
      html+='<h'+lv+' class="md-h md-h'+m[1].length+'">'+inlineMd(m[2])+'</h'+lv+'>';continue}
    if(/^(-{3,}|\*{3,}|_{3,})$/.test(line.trim())){flushPara();closeList();html+='<hr class="md-hr">';continue}
    if((m=line.match(/^\s*[-*+]\s+(.*)$/))){flushPara();if(list!=='ul'){closeList();html+='<ul class="md-list">';list='ul'}html+='<li>'+inlineMd(m[1])+'</li>';continue}
    if((m=line.match(/^\s*(\d+)[.)]\s+(.*)$/))){flushPara();if(list!=='ol'){closeList();html+='<ol class="md-list">';list='ol'}html+='<li>'+inlineMd(m[2])+'</li>';continue}
    if((m=line.match(/^>\s?(.*)$/))){flushPara();closeList();html+='<blockquote class="md-quote">'+inlineMd(m[1])+'</blockquote>';continue}
    para.push(line);
  }
  flushTable();flushPara();closeList();
  return html}
function renderAnswerText(answer){
  const parts=String(answer||'').split(/\n\n---\n/);
  const body=renderMarkdown(parts[0]);
  const foot=parts.length>1?`<p class="result-meta">${esc(parts.slice(1).join(' '))}</p>`:'';
  return body+foot}

/* ---- 读屏播报（5.1）：专用隐藏状态区，只播摘要，不再把整个对话流当 live region ---- */
const liveRegion=document.querySelector('#live-status');
let lastAnnounce='';
function announce(text){
  if(!liveRegion||!text||text===lastAnnounce)return;
  lastAnnounce=text;
  liveRegion.textContent='';
  setTimeout(()=>{liveRegion.textContent=text},50);  // 清空后写入，确保重复文本也会被重新播报
}

/* ---- 视图路由：chat / official / library / result / report ---- */
const VIEW_TITLES={chat:'对话分析',official:'官方报告',library:'我的报告',result:'分析报告',report:'官方报告 · 阅读'};
const workspace=document.querySelector('.workspace');
const chatLog=document.querySelector('#chat-log');
const chatForm=document.querySelector('#chat-form');   // 缓存引用：innerHTML 清空后仍可重新挂载
function parseHash(){
  const h=location.hash.slice(1).split('?')[0];
  if(h==='analyze')return 'chat';
  if(h==='report')return 'report';
  const m=h.match(/^\/?(chat|official|library|result|report)$/);
  return m?m[1]:'chat'}
function showView(){
  const view=parseHash();
  if(view!=='result')store.set(LAST_VIEW_KEY,view);
  workspace.dataset.activePane=view;
  document.querySelector('.main-col').dataset.view=view;
  const title=document.querySelector('#view-title');
  if(title)title.textContent=VIEW_TITLES[view]||VIEW_TITLES.chat;
  document.querySelectorAll('.nav-item[data-nav]').forEach(btn=>{
    const active=(btn.dataset.nav==='official'&&(view==='official'||view==='report'))
      ||(btn.dataset.nav==='library'&&(view==='library'||view==='result'));
    if(active)btn.setAttribute('aria-current','page');else btn.removeAttribute('aria-current')});
  if(view==='official')renderOfficialView();
  if(view==='library')renderLibraryView();
  if(view==='chat'&&chatLog.querySelector('.msg'))dockComposer();
  closeSidebar()}
window.addEventListener('hashchange',showView);

/* ---- 空状态 ---- */
function renderEmptyState(){
  const pane=document.querySelector('#chat-pane');
  pane.classList.add('is-empty');
  // 防御：输入框若还在旧空状态子树里，先移回窗格，避免 innerHTML 重建时把它连带销毁
  if(chatForm&&chatLog.contains(chatForm))pane.appendChild(chatForm);
  chatLog.innerHTML=`<div class="empty-state">
  <img class="empty-mark" src="/static/logo-mark.png" alt="" width="52" height="52">
  <h2>把用户反馈，变成可核验的发现</h2>
  <div class="empty-suggest" aria-label="示例问题">
    <button type="button" class="chip" data-fill="续航衰减">「续航衰减」有哪些负向反馈？</button>
    <button type="button" class="chip" data-fill="充电体验">「充电体验」有哪些负向反馈？</button>
    <button type="button" class="chip" data-fill="售后服务">「售后服务」有哪些负向反馈？</button>
  </div>
  <div id="composer-slot" class="composer-slot"></div>
  </div>`;
  // DeepSeek 式默认页：输入框随问候语整体居中（表单节点移入空状态）
  const slot=document.querySelector('#composer-slot');
  if(slot&&chatForm)slot.appendChild(chatForm)}

function dockComposer(){
  // 只移除居中空状态，绝不清空已渲染的消息
  const pane=document.querySelector('#chat-pane');
  pane.classList.remove('is-empty');
  chatLog.querySelector('.empty-state')?.remove();
  if(chatForm&&chatForm.parentElement!==pane)pane.appendChild(chatForm)}

/* ---- 对话消息流与会话持久化 ---- */
function addMsg(html,cls){
  // 任何消息出现时都保证：空状态收起、输入框停靠底部（覆盖 /ask、命令提示、深度表单等全部首条消息路径）
  dockComposer();
  const div=document.createElement('div');div.className='msg '+cls;div.innerHTML=html;
  chatLog.appendChild(div);chatLog.scrollTop=chatLog.scrollHeight;return div}

function appendToSession(entry){
  if(!currentSession){
    currentSession={id:sessionId,title:'',updated_at:Date.now(),messages:[]};
    sessions.unshift(currentSession);
  }
  currentSession.messages.push(entry);
  if(!currentSession.title&&entry.role==='user')currentSession.title=String(entry.text||'').slice(0,24);
  currentSession.updated_at=Date.now();
  if(sessions.length>MAX_SESSIONS)sessions.length=MAX_SESSIONS;
  if(currentSession.messages.length>60)currentSession.messages.length=60;
  store.set(SESSIONS_KEY,sessions);
  renderSessionList();
}
function relTime(ts){
  const d=new Date(ts),now=new Date();
  const sameDay=d.toDateString()===now.toDateString();
  const hm=`${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
  return sameDay?hm:`${d.getMonth()+1}-${d.getDate()}`}
function renderSessionList(){
  const ul=document.querySelector('#session-list');
  if(!ul)return;
  ul.innerHTML=sessions.length?'':'<li class="nav-empty">暂无历史对话</li>';
  sessions.forEach(s=>{
    const li=document.createElement('li');
    const active=s.id===sessionId;
    li.innerHTML=`<button type="button" class="session-item${active?' active':''}" data-session="${esc(s.id)}" ${active?'aria-current="true"':''}>
      <span class="session-title">${esc(s.title||'未命名对话')}</span>
      <span class="session-time">${esc(relTime(s.updated_at))}</span></button>`;
    ul.appendChild(li)});
}
function renderSessionMessages(s){
  chatLog.innerHTML='';
  s.messages.forEach(m=>{
    if(m.role==='user')addMsg(`<span class="bubble">${esc(m.text)}</span>`,'user');
    else if(m.data)addMsg(renderAnswer(m.data),'bot');
    else addMsg(`<p class="status">${esc(m.text||'')}</p>`,'bot')});
  dockComposer();
}
function switchSession(id){
  const s=sessions.find(x=>x.id===id);
  if(!s)return;
  sessionId=id;currentSession=s;
  renderSessionMessages(s);
  renderSessionList();
  location.hash='#/chat';
  document.querySelector('#question').focus();
}

let currentQuestion='';
async function askOnce(question){currentQuestion=question;
  dockComposer();
  addMsg(`<span class="bubble">${esc(question)}</span>`,'user');
  appendToSession({role:'user',text:question});
  const holder=addMsg('<p class="status dots" role="status">正在处理</p>','bot');
  try{
    const r=await fetch('/api/question',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question,session_id:sessionId})});
    const raw=await r.text();
    let d=null;try{d=JSON.parse(raw)}catch{/* 代理/网关可能返回非 JSON（如 502 HTML） */}
    if(!r.ok||!d){const text=d&&d.message
      ?`${d.message}（错误码 ${d.error||r.status}）。你的问题已保留在上方，可修改后重试。`
      :`请求未完成：服务返回异常（HTTP ${r.status}）。你的问题已保留在上方，可直接重试。`;
      holder.innerHTML=`<p class="status error" role="alert">${esc(text)}</p>`;
      appendToSession({role:'bot',text});return}
    holder.innerHTML=renderAnswer(d);
    appendToSession({role:'bot',data:d});
    announce('回答已生成，包含统计数据与证据');
    chatLog.scrollTop=chatLog.scrollHeight;
  }catch(err){const text='请求未完成：连接中断或服务未及时响应（长问题耗时较久时可能被中途断开）。你的问题已保留在上方，可直接重试。';
    holder.innerHTML=`<p class="status error" role="alert">${esc(text)}</p>`;
    appendToSession({role:'bot',text})}}

const WARNING_LABELS={'temporary_snapshot_placeholder':'当前为演示用临时样本数据',
  'curated_evidence_subset_not_all_claims':'引用的观点为精选样本，不代表全部用户声音',
  'model_unconfigured_deterministic_only':'自动解读未启用，以上为系统直接计算的统计与证据',
  'model_unconfigured_conversational_fallback':'模型暂未配置，当前为简短引导回复',
  'no_negative_evidence_found':'当前条件下没有找到负向反馈'};
function friendlyWarnings(w){return (w||[]).filter(c=>WARNING_LABELS[c]).map(c=>esc(WARNING_LABELS[c]));}
function renderAnswer(d){
  const stats=d.stats||[], evidence=d.evidence||[], sections=d.citations?.sections||[];
  // 只展示算得出数值或带具体维度的条目，滤掉"— 统计结果"空壳
  const metricRows=stats.filter(x=>x&&typeof x==='object')
    .filter(x=>metricValue(x)||x.aspect||x.dimension||x.journey||x.product||x.period);
  const metricBlock=metricRows.length?`<section class="result-card"><h2>本次查到的数据</h2>
    ${metricRows.length===1?metricCard(metricRows[0]):`<div class="metric-grid">${metricRows.slice(0,6).map(metricCard).join('')}</div>`}
    <p class="result-meta">数据版本：${esc(d.data_version||'—')}</p></section>`:'';
  const evidenceBlock=evidence.length?`<section class="result-card"><h2>相关用户原话 <span class="tag">${evidence.length} 条</span></h2>${evidence.slice(0,8).map(evidenceCard).join('')}</section>`:'';
  // 豆包式行内引用：被引章节与检索命中合并为来源清单，回答文本中的 [锚点] 替换为可点击角标
  const refMap={};(d.citations?.refs||[]).forEach(r=>{if(r&&r.anchor)refMap[r.anchor]=r});
  const hits=d.report_hits||[];
  const sources=[];const seenSrc=new Set();
  const addSource=(id,title,hit)=>{
    if(!id||seenSrc.has(id))return;seenSrc.add(id);
    const ref=refMap[id]||{};
    sources.push({id,title:title||id,kind:ref.report_kind||'official',
      report_id:ref.report_id||'',snippet:(hit&&hit.snippet)||'',
      matched_terms:(hit&&hit.matched_terms)||[]})};
  sections.forEach(s=>{addSource(s.id,s.title,hits.find(h=>h.id===s.id))});
  hits.forEach(h=>addSource(h.id,h.title,h));
  const srcNum={};sources.forEach((s,i)=>{srcNum[s.id]=i+1});
  // 连续多个引用锚点折叠为一个角标，仅显示引用条数（豆包式精简）
  const answerHtml=renderAnswerText(d.answer).replace(
    /(?:\[([A-Za-z0-9_\-]+)\])+/g,
    m=>{
      const ids=[...m.matchAll(/\[([A-Za-z0-9_\-]+)\]/g)].map(x=>x[1]).filter(id=>srcNum[id]);
      if(!ids.length)return m;
      const title=ids.length>1
        ?`${ids.length} 条引用：${ids.map(id=>sources[srcNum[id]-1].title).join('；')}`
        :sources[srcNum[ids[0]]-1].title;
      return `<sup class="cite-inline" data-srcs="${esc(ids.join(','))}" title="${esc(title)}">${ids.length}</sup>`});
  const sourcesData=`<script type="application/json" class="cite-sources">${JSON.stringify(sources).replace(/</g,'\\u003c')}</script>`;
  const warnings=friendlyWarnings(d.warnings);
  const guided=(d.warnings||[]).includes('deep_analysis_guided');
  const reportAction=((stats.length||evidence.length)||guided)?`<p><button type="button" class="button primary" data-generate-report>深度分析这个问题 <span aria-hidden="true">→</span></button></p>`:'';
  return `<section class="result-card">${answerHtml}${warnings.length?`<p class="result-meta">${warnings.join('；')}</p>`:''}${reportAction}</section>${metricBlock}${evidenceBlock}${sourcesData}`}

function metricValue(x){
  const share=Number(x.negativeShare??x.negative_share);
  return Number.isFinite(share)?`${(share*100).toFixed(1)}%`:
    (x.negative_posts!=null&&x.posts!=null?`${x.negative_posts} / ${x.posts}`:
      (x.negative_claims!=null&&x.claims!=null?`${x.negative_claims} / ${x.claims}`:''))}
function metricCard(x){
  const label=x.aspect||x.dimension||x.journey||x.product||x.period||'统计结果';
  const value=metricValue(x);
  const detail=x.claims!=null?`观点 ${x.claims} 条`:'';
  return `<div class="metric-box"><strong>${esc(value||'—')}</strong><span>${esc(label)}${detail?` · ${esc(detail)}`:''}</span></div>`}

function evidenceCard(v){return `<article class="evidence"><strong>${esc(v.title||'来源观点')}</strong>
  <blockquote>${esc(v.quote||v.content)}</blockquote>
  <a href="${esc(v.url)}" target="_blank" rel="noopener noreferrer">打开原始来源 ↗</a>
  <p class="result-meta">${esc(v.date)} · ${esc(v.journey||'阶段未标注')} · 证据编号 ${esc(v.claim_id)}</p></article>`}

/* ---- @ 命令：直接以 @ 锁定报告引用源 ---- */
function reportOptions(){
  const opts=[{name:'官方报告',kind:'official',report_id:''}];
  reports.forEach(r=>opts.push({name:r.title,kind:'mine',report_id:r.report_id}));
  return opts;
}
function parseAskCommand(q){
  if(!q.startsWith('@'))return null;
  const after=q.slice(1);
  // 报告名可含空格：按已知报告名从长到短前缀匹配，避免多词名被截断
  const opts=reportOptions().slice().sort((a,b)=>b.name.length-a.name.length);
  for(const o of opts){
    if(after.startsWith(o.name)){
      const question=after.slice(o.name.length).trim();
      if(question)return {report:o,question};
      return {error:'missing_question',name:o.name};
    }
  }
  const name=after.split(/\s+/)[0]||'';
  return {error:'unknown_report',name};
}
async function askReport(question,ref){
  currentQuestion=question;  // 报告问答也更新当前问题，避免后续点「深度分析」自动填入过期旧问题
  addMsg(`<span class="bubble">${esc(`@${ref.name} ${question}`)}</span>`,'user');
  appendToSession({role:'user',text:`@${ref.name} ${question}`});
  const holder=addMsg('<p class="status dots" role="status">正在查阅报告</p>','bot');
  if(ref.kind==='mine'){
    const md=(findReport(ref.report_id)||{}).markdown||'';
    if(md.length>60000){
      const text='该报告超过 6 万字符的上下文预算，无法整份引用；可下载后分段查阅，或改用深度分析。';
      holder.innerHTML=`<p class="status error" role="alert">${esc(text)}</p>`;
      appendToSession({role:'bot',text});return}
  }
  try{
    const r=await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({question,report_ref:{kind:ref.kind,report_id:ref.report_id,
        content:ref.kind==='mine'?(findReport(ref.report_id)||{}).markdown||'':undefined}})});
    const raw=await r.text();
    let d=null;try{d=JSON.parse(raw)}catch{/* 非 JSON 响应按 HTTP 状态呈现 */}
    if(!r.ok||!d){const text=d&&d.message
      ?`${d.message}（错误码 ${d.error||r.status}）。`
      :`报告问答未完成：服务返回异常（HTTP ${r.status}）。你的问题已保留在上方，可直接重试。`;
      holder.innerHTML=`<p class="status error" role="alert">${esc(text)}</p>`;
      appendToSession({role:'bot',text});return}
    holder.innerHTML=renderAnswer(d);
    appendToSession({role:'bot',data:d});
    chatLog.scrollTop=chatLog.scrollHeight;
  }catch(err){const text='报告问答未完成：连接中断或服务未及时响应。你的问题已保留在上方，可直接重试。';
    holder.innerHTML=`<p class="status error" role="alert">${esc(text)}</p>`;
    appendToSession({role:'bot',text})}
}
function askCommandHint(note){
  const opts=reportOptions();
  addMsg(`<p class="status">${esc(note||'')}直接输入 <strong>@报告名 + 问题</strong>，可从下面选择报告：</p>
    <div class="cites">${opts.map(o=>`<button type="button" class="cite" data-ask-prefill="${esc(o.name)}">${esc(o.name)}</button>`).join('')}</div>`,'bot');
}

/* ---- 输入框补全（@ 报告）与引用选段上下文 ---- */
const suggestBox=document.querySelector('#composer-suggest');
const questionInput=document.querySelector('#question');
let suggestState=null;
function hideSuggest(){
  if(suggestBox)suggestBox.hidden=true;
  suggestState=null;
  questionInput?.setAttribute('aria-expanded','false');   // combobox 状态同步（5.5）
  questionInput?.removeAttribute('aria-activedescendant')}
function renderSuggest(items,type){
  if(!suggestBox)return;
  if(!items.length){hideSuggest();return}  // 无命中时不渲染空白浮层
  suggestState={type,items,index:0};
  suggestBox.innerHTML=items.map((o,idx)=>
    `<button type="button" role="option" id="suggest-opt-${idx}" aria-selected="${idx===0?'true':'false'}" class="suggest-item${idx===0?' active':''}" data-suggest-idx="${idx}"><strong>${esc(o.label)}</strong><span>${esc(o.desc)}</span></button>`).join('');
  suggestBox.hidden=false;
  questionInput.setAttribute('aria-expanded','true');
  questionInput.setAttribute('aria-activedescendant','suggest-opt-0');
}
function showReportSuggest(query){
  const items=reportOptions()
    .filter(o=>o.name.toLowerCase().includes((query||'').toLowerCase()))
    .map(o=>({label:o.name,desc:o.kind==='official'?'官方报告':'我的报告',opt:o}));
  renderSuggest(items,'report');
}
function applySuggest(item){
  if(!item)return;
  const v=questionInput.value;
  questionInput.value=v.replace(/@([^\s@]*)$/,`@${item.label} `);
  hideSuggest();
  questionInput.focus();
}
questionInput?.addEventListener('input',()=>{
  const v=questionInput.value;
  const at=v.match(/^@([^\s@]*)$/);
  if(at){showReportSuggest(at[1]);return}
  hideSuggest();
});

/* ---- 引用选段（Codex 式）：划词"问研究员"携带的上下文 ---- */
let composerQuote=null;
const composerQuoteEl=document.querySelector('#composer-quote');
function setComposerQuote(quote){
  composerQuote=quote;
  if(!composerQuoteEl)return;
  if(!quote){composerQuoteEl.hidden=true;composerQuoteEl.innerHTML='';return}
  const text=String(quote.text||'').trim();
  composerQuoteEl.innerHTML=`<p class="quote-text">“${esc(text.slice(0,160))}${text.length>160?'…':''}”</p>
    <p class="quote-src">${esc(quote.source||'报告选段')}${quote.section?` · ${esc(quote.section)}`:''}</p>
    <button type="button" class="quote-x" aria-label="移除引用选段" data-quote-remove aria-hidden="true">×</button>`;
  composerQuoteEl.hidden=false;
}
function composeQuestion(q){
  if(composerQuote&&composerQuote.text&&String(q).trim()){
    const qt=composerQuote.text.trim().slice(0,200);
    const sec=composerQuote.section?`（出自「${composerQuote.section}」）`:'';
    q=`报告选段“${qt}”${sec}：${q}`;
  }
  setComposerQuote(null);
  return q;
}
questionInput?.addEventListener('keydown',e=>{
  if(!suggestState||suggestBox.hidden)return;
  const items=suggestState.items;
  if(e.key==='ArrowDown'||e.key==='ArrowUp'){
    e.preventDefault();
    if(!items.length)return;
    suggestState.index=(suggestState.index+(e.key==='ArrowDown'?1:items.length-1))%items.length;
    suggestBox.querySelectorAll('.suggest-item').forEach((el,i)=>{
      el.classList.toggle('active',i===suggestState.index);
      el.setAttribute('aria-selected',i===suggestState.index?'true':'false')});
    questionInput.setAttribute('aria-activedescendant',`suggest-opt-${suggestState.index}`);
    return}
  if(e.key==='Enter'){
    e.preventDefault();
    applySuggest(items[suggestState.index]);
    return}
  if(e.key==='Escape'){hideSuggest()}
});

/* ---- 新建对话 ---- */
document.querySelector('#new-chat').addEventListener('click',()=>{
  sessionId=newSessionId();currentSession=null;
  renderEmptyState();renderSessionList();
  document.querySelector('#question').value='';
  location.hash='#/chat';
  document.querySelector('#question').focus();
});

document.querySelector('#chat-form').addEventListener('submit',e=>{e.preventDefault();
  const input=document.querySelector('#question'),q=input.value.trim();
  if(!q)return;input.value='';hideSuggest();
  if(/^@/.test(q)){
    const parsed=parseAskCommand(q);
    if(!parsed){askCommandHint('格式为 @报告名 问题。');input.value=q;return}
    if(parsed.error==='missing_question'){askCommandHint(`已选择「${parsed.name}」，请在下方补充你的问题。`);
      input.value=`@${parsed.name} `;showReportSuggest('');return}
    if(parsed.error){askCommandHint(`没有找到名为「${parsed.name}」的报告。`);input.value=q;return}
    askReport(composeQuestion(parsed.question),{kind:parsed.report.kind,report_id:parsed.report.report_id,name:parsed.report.name});
    return}
  askOnce(composeQuestion(q))});

/* ---- 报告库（我的报告） ---- */
function slugify(t){return String(t||'报告').replace(/[\\/:*?"<>|#\s]+/g,'-').slice(0,40)||'报告'}
function downloadReport(r){
  const blob=new Blob(['\ufeff'+(r.markdown||'')],{type:'text/markdown;charset=utf-8'});
  const a=document.createElement('a');
  a.href=URL.createObjectURL(blob);
  a.download=`AutoInsight报告-${slugify(r.title)}.md`;
  document.body.appendChild(a);a.click();a.remove();
  setTimeout(()=>URL.revokeObjectURL(a.href),2000)}
function buildReportRec(d,question){
  return {report_id:d.report_id||`local-${Date.now()}`,title:d.title||'未命名报告',
    markdown:d.report_md||'',key_findings:d.key_findings||[],data_version:d.data_version||'—',
    charts:Array.isArray(d.charts)?d.charts:[],
    evidence_index:Array.isArray(d.evidence_index)?d.evidence_index:[],
    question:question||'',saved_at:Date.now(),status:d.publication_status||'saved'}}
function upsertReport(rec){
  const i=reports.findIndex(r=>r.report_id===rec.report_id);
  if(i>=0)reports[i]=rec;else reports.unshift(rec);
  if(reports.length>MAX_REPORTS)reports.length=MAX_REPORTS;
  store.set(REPORTS_KEY,reports);
  updateLibraryBadge();
  return rec}
function saveReport(d,question){return upsertReport(buildReportRec(d,question))}
function findReport(id){return reports.find(r=>r.report_id===id)||null}
function updateLibraryBadge(){
  const b=document.querySelector('#library-badge');
  if(!b)return;
  b.hidden=!reports.length;
  b.textContent=String(reports.length)}

/* ---- 结果视图：报告结构化展示 ---- */
const RESULT_W_KEY='ai.resultw';
let currentResultReport=null;   // 当前分栏展示的"我的报告"（桥C 划词追问使用）
function openResultSplit(){
  if(window.innerWidth<1024){if(location.hash!=='#/result')location.hash='#/result';else showView();return}
  workspace.classList.add('has-result');
  document.querySelector('#result-divider').hidden=false;
  if(location.hash!=='#/chat')location.hash='#/chat';else showView()}
function closeResultSplit(){
  workspace.classList.remove('has-result');
  document.querySelector('#result-divider').hidden=true;
  if(parseHash()==='result')location.hash='#/chat';else showView()}
function decorateCitations(article,evidenceIndex){
  // 正文 (claim_id: hex) → [n] 角标（悬停看原帖信息、可点击）；文末附可展开编号清单。
  // report.md 原文不变，gate 证据闭包不受影响——纯呈现层转换。
  if(!article)return;
  const byId=new Map((Array.isArray(evidenceIndex)?evidenceIndex:[]).map(e=>[e.claim_id,e]));
  const re=/[（(]\s*claim_id[:：]\s*([0-9a-fA-F]{16,32})\s*[）)]/g;
  const used=[];
  const walker=document.createTreeWalker(article,NodeFilter.SHOW_TEXT);
  const nodes=[];let n;
  while(n=walker.nextNode())nodes.push(n);
  for(const node of nodes){
    if(!re.test(node.nodeValue))continue;
    re.lastIndex=0;
    const frag=document.createDocumentFragment();
    const text=node.nodeValue;let last=0,m;
    while(m=re.exec(text)){
      frag.appendChild(document.createTextNode(text.slice(last,m.index)));
      const id=m[1].toLowerCase();
      let idx=used.indexOf(id);
      if(idx<0){used.push(id);idx=used.length-1}
      const meta=byId.get(id);
      const sup=document.createElement('sup');
      sup.className='cite-ref';
      sup.textContent=`[${idx+1}]`;
      if(meta&&meta.url){
        const a=document.createElement('a');
        a.href=meta.url;a.target='_blank';a.rel='noopener';
        a.title=[meta.title,meta.date,meta.aspect,meta.sentiment,meta.ownership,meta.experience]
          .filter(Boolean).join(' · ');
        a.appendChild(sup);frag.appendChild(a)}
      else frag.appendChild(sup);
      last=m.index+m[0].length}
    frag.appendChild(document.createTextNode(text.slice(last)));
    node.parentNode.replaceChild(frag,node)}
  if(!used.length)return;
  const det=document.createElement('details');
  det.className='evidence-footnotes';
  det.innerHTML=`<summary>证据引用编号（${used.length} 条，展开查看原帖）</summary><ol>`+
    used.map((id,i)=>{const meta=byId.get(id);
      const desc=meta?[meta.title,meta.date].filter(Boolean).join(' · '):'';
      const link=meta&&meta.url?` · <a href="${esc(meta.url)}" target="_blank" rel="noopener">原帖</a>`:'';
      return `<li value="${i+1}"><code>${esc(id)}</code>${desc?' — '+esc(desc):''}${link}</li>`}).join('')+
    '</ol></details>';
  article.appendChild(det)}
function embedCharts(container,charts){
  // 图表锚进对应文字段落（与发布视图 _insert_charts 同构）：按标题/议题文本
  // 匹配正文元素，插到其后；找不到锚点才归入文末「图表」附录
  if(!container||!Array.isArray(charts)||!charts.length)return;
  const orphans=[];
  const scope=container.querySelectorAll('p,li,h2,h3,h4,td,th');
  for(const c of charts){
    const fig=document.createElement('figure');
    fig.className='report-chart';
    fig.innerHTML=(c.svg||'')+
      `<figcaption>${esc(c.title||'')} · 数据来源：已验证分析步骤（与正文数字同源）</figcaption>`;
    const anchor=String(c.anchor||c.title||'').slice(0,16);
    const hit=anchor?[...scope].find(el=>el.textContent.includes(anchor)):null;
    if(hit&&hit.parentElement)hit.parentElement.insertBefore(fig,hit.nextSibling);
    else orphans.push(fig)}
  if(orphans.length){
    const sec=document.createElement('section');
    sec.className='result-card';
    sec.innerHTML='<h2>图表</h2>';
    orphans.forEach(f=>sec.appendChild(f));
    container.appendChild(sec)}
}
function showReport(rec,{saved=true,inPlace=false}={}){
  const box=document.querySelector('#result-view');
  if(!box)return;
  const statusTag=!saved
    ?'<span class="tag warn">未保存</span>'
    :rec.status==='pending_review'
      ?'<span class="tag warn">待审核</span>':'<span class="tag ok">已保存</span>';
  const note=!saved
    ?'<div class="warning">报告尚未保存到「我的报告」；离开或刷新页面前请先保存。</div>'
    :rec.status==='pending_review'
      ?'<div class="warning">报告已进入审核发布流程；审核通过前不会替换公共报告。</div>':'';
  box.innerHTML=`
    <header class="result-head">
      <p class="result-kicker">分析报告${rec.question?` · 来自提问「${esc(rec.question.slice(0,30))}${rec.question.length>30?'…':''}」`:''}</p>
      <div class="result-title-row"><h1>${esc(rec.title)}</h1>${statusTag}</div>
      <p class="result-meta">数据版本：${esc(rec.data_version)} · 保存于 ${esc(relTime(rec.saved_at))}</p>
      <div class="result-actions">
        ${!saved?`<button type="button" class="button primary" data-save-report="${esc(rec.report_id)}">保存到我的报告</button>`:''}
        <button type="button" class="${saved?'button primary':'btn-ghost'}" data-download="${esc(rec.report_id)}">下载报告 <span aria-hidden="true">↓</span></button>
        ${inPlace?'<button type="button" class="btn-ghost" data-back-library>返回我的报告</button>':''}
      </div>
    </header>${note}
    ${rec.key_findings?.length?`<section class="result-card key-findings"><h2>关键结论</h2><ul class="md-list">${rec.key_findings.map(k=>`<li>${esc(k)}</li>`).join('')}</ul></section>`:''}
    <article class="report-body">${renderMarkdown(rec.markdown)}</article>`;
  embedCharts(box.querySelector('article.report-body'),rec.charts);
  decorateCitations(box.querySelector('article.report-body'),rec.evidence_index);
  // 与后端 sections_from_markdown 的编号规则对齐：标题按出现顺序 = agent-N
  box.querySelectorAll('.report-body :is(h3,h4,h5)').forEach((el,i)=>{el.id=`agent-${i+1}`});
  currentResultReport=rec;
  if(inPlace){
    // 「我的报告」页内阅读：整页结果视图，不跳回对话分栏
    if(parseHash()!=='result')location.hash='#/result';else showView()}
  else openResultSplit()}

/* ---- 官方报告卡片视图 ---- */
async function renderOfficialView(){
  const box=document.querySelector('#official-view');
  if(!box)return;
  box.innerHTML='<p class="status dots" role="status">正在获取官方报告信息</p>';
  let card;
  try{
    const r=await fetch('/api/reports/published/latest');
    if(r.ok){
      const d=await r.json();
      const m=d.report||{};
      card=`<article class="report-card">
        <p class="card-kicker">最新已发布</p>
        <h2>${esc(m.title||'AutoInsight 深度分析报告')}</h2>
        <p class="result-meta">数据版本：${esc(m.data_version||'—')}${m.review?.reviewer?` · 审核人：${esc(m.review.reviewer)}`:''}${m.review?.reviewed_at?` · 发布于 ${esc(String(m.review.reviewed_at).slice(0,10))}`:''}</p>
        <div class="card-actions"><button type="button" class="button primary" data-open-official>打开阅读 <span aria-hidden="true">→</span></button></div>
      </article>`;
    }else{
      card=`<article class="report-card">
        <p class="card-kicker">内置研究报告</p>
        <h2>AutoInsight 新能源用户研究报告</h2>
        <p class="result-meta">当前快照尚无经审核发布的深度分析报告；以下为随工作台交付的研究报告（auto-023 结构）。</p>
        <div class="card-actions"><button type="button" class="button primary" data-open-official>打开阅读 <span aria-hidden="true">→</span></button></div>
      </article>`;
    }
  }catch{
    card=`<article class="report-card"><h2>官方报告</h2><p class="result-meta">暂时无法获取报告信息，请稍后重试。</p></article>`;
  }
  box.innerHTML=`<h1 class="cards-heading">官方报告</h1><p class="cards-note">由研究团队审核发布；深度分析产生的报告需经审核后才会出现在这里。</p><div class="card-grid">${card}</div>`}

/* ---- 我的报告卡片视图 ---- */
function renderLibraryView(){
  const box=document.querySelector('#library-view');
  if(!box)return;
  if(!reports.length){
    box.innerHTML=`<h1 class="cards-heading">我的报告</h1>
      <div class="empty-library"><p>还没有保存的报告。</p>
      <p class="result-meta">在对话中发起深度分析，完成后在结果页点击「保存到我的报告」，报告就会保存在这里，并可下载为 Markdown 文件。</p></div>`;
    return}
  const cards=reports.map(r=>`<article class="report-card">
    <p class="card-kicker">${esc(relTime(r.saved_at))}</p>
    <h2>${esc(r.title)}</h2>
    ${r.key_findings?.length?`<ul class="card-findings">${r.key_findings.slice(0,2).map(k=>`<li>${esc(k)}</li>`).join('')}</ul>`:''}
    <p class="result-meta">数据版本：${esc(r.data_version)}</p>
    <div class="card-actions">
      <button type="button" class="button primary" data-view-report="${esc(r.report_id)}">查看</button>
      <button type="button" class="btn-ghost" data-download="${esc(r.report_id)}">下载 <span aria-hidden="true">↓</span></button>
      <button type="button" class="btn-ghost" data-del-report="${esc(r.report_id)}">删除</button>
    </div></article>`).join('');
  box.innerHTML=`<h1 class="cards-heading">我的报告</h1><p class="cards-note">保存在本浏览器中（最多 ${MAX_REPORTS} 份）；下载为 Markdown 文件。</p><div class="card-grid">${cards}</div>`}

/* ---- 深度分析：入口表单、进度与结果 ---- */
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let lastReportQuestion='';
function setStatus(text){const el=document.querySelector('#doc-status');if(el)el.textContent=text||''}
function openDeepForm(prefill){
  hideSuggest();
  // 只保留一张深度分析表单：打开前移除未提交的旧表单卡片
  chatLog.querySelectorAll('.msg .deep-form').forEach(el=>el.closest('.msg')?.remove());
  const topic=String(prefill||currentQuestion||'').slice(0,200);
  addMsg(`<div class="deep-form" role="group" aria-label="深度分析输入">
    <h2>发起深度分析</h2>
    <label class="deep-label" for="deep-topic">研究主题（必填）</label>
    <textarea id="deep-topic" maxlength="300" rows="2" placeholder="例如：新能源用户对充电体验的负面反馈集中在哪些环节？">${esc(topic)}</textarea>
    <p class="result-meta">分析主体：小米 SU7（当前数据快照锁定）。主题越具体，大纲越准；如需品牌共现对比，可在主题中说明。</p>
    <div class="deep-actions">
      <button type="button" class="button primary" data-deep-start>开始深度分析</button>
      <button type="button" class="btn-ghost" data-deep-cancel>取消</button>
    </div>
    <p class="result-meta">完成后可在结果页确认，点击「保存到我的报告」后才会入库。</p></div>`,'bot');
  document.querySelector('#deep-topic')?.focus();
}
function renderProgressCard(phase){
  const box=document.querySelector('#result-view');
  // 轮询每 1.5s 到达一次：卡片骨架只建一次，后续只更新阶段文本，避免全量重建 DOM
  const phaseEl=box?.querySelector('[data-progress-phase]');
  if(phaseEl){phaseEl.textContent=publicPhase(phase);return}
  box.innerHTML=`
    <header class="result-head"><p class="result-kicker">分析报告</p>
    <div class="result-title-row"><h1>正在生成研究报告</h1></div>
    <p class="result-meta">当前阶段：<span data-progress-phase>${esc(publicPhase(phase))}</span></p></header>
    <p class="status dots" role="status">深度分析进行中</p>
    <div class="scope-note">深度分析按「理解问题 → 分析草案 → 执行分析 → 报告核验」流程进行；完成后报告会自动保存在「我的报告」。</div>`}

/* ---- 等待用户输入的两类任务卡片（P0-1）：澄清补充 与 大纲审查 ---- */
let interactiveCardKey='';   // 当前已渲染交互卡片的标识；不变则不重绘，保护用户输入
let renderedCardKey='';      // 最近一次渲染卡片时使用的键；提交成功后用它抑制同内容重绘
let deepJobUrl='';           // 当前深度分析任务的轮询地址（也是 clarify/outline 子动作的基址）
let clarifyQuestions=[];     // 当前澄清卡的问题列表（提交时组装结构化答复）
// 子动作失败时的状态码 → 用户可读文案（后端无 message 时的兜底）
const DEEP_ACTION_ERRORS={400:'提交内容未通过校验，请检查后重试。',
  404:'任务状态已失效或已过期（服务可能重启过），请重新发起深度分析。',
  409:'任务状态刚刚发生变化，请刷新页面或稍后重试。',
  429:'操作过于频繁，请稍候几秒再试。',500:'服务暂时出现问题，请重试一次；若持续失败请重新发起分析。'};
async function postDeepAction(suffix,payload){
  const r=await fetch(`${deepJobUrl}/${suffix}`,{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const d=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(d.message||DEEP_ACTION_ERRORS[r.status]||d.error||`请求失败（${r.status}）`);
  return d}
function deepActionError(card,err){
  const box=card?.querySelector('.deep-action-error');
  if(box)box.innerHTML=`<div class="warning" role="alert">${esc(String(err.message||err).slice(0,200))}</div>`}

function renderClarifyCard(job){
  const questions=Array.isArray(job.clarify_questions)?job.clarify_questions:[];
  clarifyQuestions=questions;
  const fields=(questions.length?questions:[{field:'other',question:'请补充说明你的研究主题（关注对象、具体维度或对比意图）'}])
    .map((q,i)=>`<div class="clarify-q">
      <label class="deep-label" for="clarify-a${i}">${esc(q.question||'请补充说明研究主题')}</label>
      <textarea id="clarify-a${i}" data-clarify-idx="${i}" maxlength="500" rows="2"
        placeholder="选填；多项可只答你关心的部分"></textarea></div>`).join('');
  const box=document.querySelector('#result-view');
  box.innerHTML=`
    <header class="result-head"><p class="result-kicker">深度分析 · 确认研究问题</p>
      <div class="result-title-row"><h1 tabindex="-1">先确认几个问题</h1></div>
      <p class="result-meta">回答后分析会更聚焦；跳过则按当前理解继续。最多 ${Math.max(0,2-(job.clarifications?.length||0))} 轮。</p></header>
    <section class="result-card deep-stage-card" role="group" aria-label="澄清补充">
      ${fields}
      <div class="deep-action-error"></div>
      <div class="deep-actions">
        <button type="button" class="button primary" data-clarify-submit>提交并继续分析</button>
        <button type="button" class="btn-ghost" data-clarify-skip>跳过，直接开始</button>
      </div>
      <p class="result-meta">说明：分析主体与数据范围已由系统锁定，无需重复说明。</p>
    </section>`;
  announce('深度分析需要补充研究问题，请回答后继续');
  box.querySelector('h1')?.focus()}

let currentOutlinePlan='';
function renderOutlineCard(job){
  const outline=job.outline||{};
  const items=Array.isArray(outline.outline)?outline.outline:[];
  const left=Math.max(0,3-(job.regenerates||0));
  const hasIds=items.every(it=>it.id);
  const itemHtml=items.length?items.map(it=>`<li class="outline-item">
      ${hasIds?`<input type="checkbox" class="outline-keep" data-ws-id="${esc(it.id)}" checked aria-label="保留该条目">`:''}
      <span class="outline-order">${esc(it.order||'')}</span>
      <div class="outline-body"><p>${esc(it.question||'')}</p>
        <p class="result-meta">${it.aspect?`议题：${esc(it.aspect)}`:''}${it.aspect&&it.requires_evidence?' · ':''}${it.requires_evidence?'<span class="tag">含用户原话引用</span>':''}${it.visualization?.title?` · 图表：${esc(it.visualization.title)}`:''}</p>
      </div></li>`).join('')
    :`<li class="outline-item"><div class="outline-body"><p>（大纲内容为空，建议重新生成）</p></div></li>`;
  currentOutlinePlan=String(outline.plan_json||'');
  const box=document.querySelector('#result-view');
  box.innerHTML=`
    <header class="result-head"><p class="result-kicker">深度分析 · 大纲审查</p>
      <div class="result-title-row"><h1 tabindex="-1">这份分析大纲可以吗？</h1></div>
      <p class="result-meta">确认后系统按大纲执行分析并生成报告；不满意可要求重新起草（剩 ${left} 次）。${hasIds?'也可取消勾选不想分析的条目，按勾选修改后开始。':''}</p></header>
    <section class="result-card deep-stage-card" role="group" aria-label="大纲审查">
      <ol class="outline-list">${itemHtml}</ol>
      <details class="delivery-spec">
        <summary>可选：指定报告重点与受众</summary>
        <label class="deep-label" for="spec-focus">重点（如：集中在充电与售后）</label>
        <input id="spec-focus" maxlength="100">
        <label class="deep-label" for="spec-audience">受众（如：产品团队 / 管理层）</label>
        <input id="spec-audience" maxlength="100">
      </details>
      <div class="deep-action-error"></div>
      <div class="deep-actions">
        <button type="button" class="button primary" data-outline-confirm>确认，开始分析</button>
        <button type="button" class="btn-ghost" data-outline-edit${hasIds?'':' hidden'}>按勾选修改，开始分析</button>
        <button type="button" class="btn-ghost" data-outline-regen>重新起草</button>
      </div>
      <div class="regen-row" hidden>
        <label class="deep-label" for="regen-feedback">哪里不满意？（选填，帮助重新起草更准）</label>
        <textarea id="regen-feedback" maxlength="300" rows="2" placeholder="例如：只关注充电相关，不需要月度走势"></textarea>
        <div class="deep-actions">
          <button type="button" class="button primary" data-outline-regen-send>提交重新起草</button>
          <button type="button" class="btn-ghost" data-outline-regen-cancel>返回</button>
        </div>
      </div>
    </section>`;
  announce('分析大纲已生成，请确认或要求重新起草');
  box.querySelector('h1')?.focus()}
// 失败原因 → 用户可执行的下一步（P1-3：按错误类型给针对性指导，而非笼统兜底话术）
const FAILURE_HINTS=[
  [/model_unconfigured|not configured|配置/i,'深度分析依赖模型服务，当前未完成配置。请联系管理员检查服务端 AI_* 配置后重试。'],
  [/deep_analysis_busy|任务已满|busy/i,'当前分析并发已满（通常 1-2 分钟内会释放）。请稍等片刻再重试。'],
  [/pending_review_exists|等待澄清|等待.*审查/,'您已有一个等待处理的分析任务。请先在任务面板完成澄清或大纲确认，再发起新的分析。'],
  [/rate_limited|过于频繁|rate limit/i,'请求过于频繁触发了限流，请等待约 1 分钟后再重试。'],
  [/timeout|超时|RecursionError|recursion/i,'本次分析过程超出执行预算，通常是主题范围过大。建议把主题改得更聚焦（例如只关注一个议题、一种反馈类型）后重试。'],
  [/门禁|gate|未通过核验|未提交|gate_rejected/i,'报告未通过数据核验，通常与分析结果证据不足有关。建议更换提问角度或缩小分析范围后重试。'],
  [/budget|预算|attempt_limit|上限/,'分析重试预算已用尽。建议缩小主题范围后重新发起，而不是直接重试原主题。'],
  [/澄清|clarif/i,'问题澄清环节未正常完成。建议在发起时把研究主题写得更具体（对象+关注的反馈维度）。'],
];
function failureAdvice(detail){
  for(const [re,advice] of FAILURE_HINTS){if(re.test(detail))return advice}
  return '可修改问题后重试，或改用对话中的统计与证据查询。'}
function deepFailureView(job,err){
  store.set(ACTIVE_JOB_KEY,null);
  currentResultReport=null;
  interactiveCardKey='';
  setStatus('深度分析失败');
  const box=document.querySelector('#result-view');
  if(!box)return;
  // 具体原因：轮询失败带 job.error；启动失败带接口 err.message
  const detail=String((job&&job.error&&(job.error.error||job.error.message))||(err&&err.message)||'');
  const advice=failureAdvice(detail);
  const reasonHtml=detail?`<details class="failure-detail"><summary>技术原因</summary><pre>${esc(detail.slice(0,600))}</pre></details>`:'';
  box.innerHTML=`<header class="result-head"><p class="result-kicker">分析报告</p><div class="result-title-row"><h1>深度分析未完成</h1></div></header>
    <section class="result-card"><p>本次没有生成通过核验的报告，因此「我的报告」中没有新增条目。</p>
    <div class="warning">${esc(advice)}</div>${reasonHtml}
    <p><button type="button" class="btn-ghost" data-retry>重试深度分析</button></p></section>`;
}
const POLL_BASE_MS=1500,POLL_MAX_MS=8000,POLL_TOTAL_MS=15*60*1000;
let pollSeq=0;  // 每次新分析/恢复递增；旧轮询循环发现序号过期立即退出，杜绝双循环交替覆写视图（闪烁根因）
async function pollJob(statusUrl,question,seq){
  const box=document.querySelector('#result-view');
  deepJobUrl=statusUrl;
  let interval=POLL_BASE_MS,lastPhase='',startedAt=Date.now();
  for(;;){
    await sleep(interval);
    if(seq!==undefined&&seq!==pollSeq)return;  // 已有更新的分析在轮询，本循环退出（防闪烁）
    if(document.hidden)continue;  // 后台标签页暂停轮询，回到前台后下一个 tick 恢复（7.2）
    if(Date.now()-startedAt>POLL_TOTAL_MS){
      // 任务 TTL 远长于本上限：保留 ACTIVE_JOB，用户刷新页面可经 resumeLiveJob 继续跟踪
      setStatus('分析仍在后台进行');
      box.innerHTML=`<header class="result-head"><p class="result-kicker">分析报告</p>
        <div class="result-title-row"><h1>分析耗时较长</h1></div></header>
        <section class="result-card"><p>本次深度分析仍在后台执行，页面已暂停实时刷新。</p>
        <div class="warning">稍后刷新页面即可恢复进度；报告完成后会自动保存到「我的报告」。</div></section>`;
      return}
    let pr;
    try{pr=await fetch(statusUrl)}
    catch{interval=Math.min(interval*2,POLL_MAX_MS);continue}  // 网络抖动：退避重试，不终止
    if(!pr.ok){
      if(pr.status===404)throw new Error('任务不存在或已过期');
      interval=Math.min(interval*2,POLL_MAX_MS);continue}  // 5xx 等：退避重试
    let j;
    try{j=await pr.json()}
    catch{interval=Math.min(interval*2,POLL_MAX_MS);continue}
    interval=POLL_BASE_MS;
    if(j.phase!==lastPhase){lastPhase=j.phase;announce(`深度分析阶段：${publicPhase(j.phase)}`)}
    setStatus(publicPhase(j.phase));
    if(j.status==='done'){
      store.set(ACTIVE_JOB_KEY,null);
      interactiveCardKey='';
      setStatus('分析完成');
      announce('研究报告已生成，确认后请保存到我的报告');
      const rec=buildReportRec(j.result,question);
      appendToSession({role:'bot',text:`研究报告已生成：《${rec.title}》。请在结果页确认内容，点击「保存到我的报告」后才会出现在「我的报告」中。`});
      showReport(rec,{saved:false});
      return}
    if(j.status==='failed'){
      announce('深度分析未完成');
      deepFailureView(j);
      return}
    // 等待用户输入的两个节点（D10 澄清 / D9 大纲审查）：只在内容变化时渲染一次，
    // 避免轮询覆盖用户正在输入的表单（P0-1 修复：此前这两个状态被当成普通进度无限等待）
    if(j.status==='clarifying'){
      const key='clarify:'+JSON.stringify(j.clarify_questions||[]);
      if(key!==interactiveCardKey){
        interactiveCardKey=key;renderedCardKey=key;
        renderClarifyCard(j)}
      continue}
    if(j.status==='awaiting_review'){
      const outline=j.outline||{};
      const key='outline:'+(j.regenerates||0)+':'+String(outline.plan_json||'').length;
      if(key!==interactiveCardKey){
        interactiveCardKey=key;renderedCardKey=key;
        renderOutlineCard(j)}
      continue}
    interactiveCardKey='';
    renderProgressCard(j.phase);
  }
}
async function generateLiveReport(question,brief){
  const box=document.querySelector('#result-view');
  if(!box)return;
  lastReportQuestion=question;
  setStatus('正在分析');
  openResultSplit();
  currentResultReport=null;
  box.innerHTML=`<header class="result-head"><p class="result-kicker">分析报告</p><div class="result-title-row"><h1>正在启动深度分析</h1></div></header><p class="status dots" role="status">正在处理</p>`;
  try{
    const start=await fetch('/api/agent/report',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(brief?{question,brief}:{question})});
    const s=await start.json();
    if(!start.ok){throw new Error(s.message||'启动失败')}
    store.set(ACTIVE_JOB_KEY,{status_url:s.status_url,question});
    await pollJob(s.status_url,question,++pollSeq);
  }catch(err){deepFailureView(null,err)}
}
function resumeLiveJob(job){
  const box=document.querySelector('#result-view');
  if(!box)return;
  lastReportQuestion=job.question||'';
  setStatus('正在分析');
  openResultSplit();
  renderProgressCard('planning');
  pollJob(job.status_url,job.question,++pollSeq).catch(err=>deepFailureView(null,err));
}
function renderLibraryViewIfNeeded(){if(parseHash()==='library')renderLibraryView()}
function publicPhase(phase){return ({queued:'等待开始',planning:'梳理研究问题',analyzing:'分析数据与观点',writing:'整理研究报告',verifying:'核对数据与证据',done:'分析完成',failed:'分析未完成',
  '澄清中':'确认研究问题','待大纲审查':'等待大纲确认','数据探索中':'分析数据与观点','编写分析代码中':'分析数据与观点','沙箱执行中':'分析数据与观点','撰写报告中':'整理研究报告','收尾中':'核对数据与证据','已完成':'分析完成','失败':'分析未完成'})[phase]||'正在分析'}

/* ---- 引用定位：结果分栏是对话页内统一的报告承载面 ---- */
function showOfficialInPane(anchor){
  const box=document.querySelector('#result-view');
  if(!box)return;
  currentResultReport=null;
  box.innerHTML=`<header class="result-head"><p class="result-kicker">官方报告 · 对照阅读</p></header>
    <iframe class="pane-report-frame" src="/report/full" title="官方报告对照阅读"></iframe>`;
  openResultSplit();
  const frame=box.querySelector('iframe');
  frame.addEventListener('load',()=>{
    if(anchor){try{
      const el=frame.contentDocument.getElementById(anchor);
      if(el&&el.scrollIntoView)el.scrollIntoView({behavior:'smooth',block:'start'});
    }catch{}}
    attachSelectionPicker(frame,'官方报告');
  });
}
function scrollPaneReportTo(anchor){
  if(!anchor)return;
  const el=document.querySelector('#result-view .report-body')?.querySelector(`[id="${CSS.escape(anchor)}"]`);
  if(el&&el.scrollIntoView)el.scrollIntoView({behavior:'smooth',block:'start'});
}
/* ---- 行内引用角标 → 来源卡片（章节 + 命中片段 + 定位，支持多条） ---- */
let sourceCardEl=null;
function hideSourceCard(){sourceCardEl?.remove();sourceCardEl=null}
function showSourceCard(idsCsv,anchorBtn){
  hideSourceCard();
  const msg=anchorBtn.closest('.msg');
  let sources=[];
  try{sources=JSON.parse(msg?.querySelector('.cite-sources')?.textContent||'[]')}catch{}
  const picked=String(idsCsv||'').split(',').filter(Boolean)
    .map(id=>({id,s:sources.find(x=>x.id===id)})).filter(x=>x.s);
  if(!picked.length)return;
  const card=document.createElement('div');
  card.className='source-card';card.setAttribute('role','dialog');card.setAttribute('aria-label','引用来源');
  card.innerHTML=picked.map(({id,s})=>{
    const num=sources.indexOf(s)+1;
    return `<button type="button" class="sc-item" data-sc-id="${esc(id)}" aria-label="定位到：${esc(s.title)}">
      <span class="sc-num">${num}</span>
      <span class="sc-title">${esc(s.title)}</span>
      <span class="sc-go" aria-hidden="true">→</span>
    </button>`}).join('');
  card.querySelectorAll('[data-sc-id]').forEach(btn=>btn.addEventListener('click',()=>{
    const s=sources.find(x=>x.id===btn.dataset.scId);
    hideSourceCard();
    if(!s)return;
    if(s.kind==='mine'){const rec=findReport(s.report_id);if(rec){showReport(rec);scrollPaneReportTo(s.id);return}}
    showOfficialInPane(s.id);
  }));
  document.body.appendChild(card);
  sourceCardEl=card;
  // 视口内夹取：优先显示在角标上方，越界翻到下方
  const r=anchorBtn.getBoundingClientRect();
  const cw=Math.min(380,window.innerWidth-24);
  const ch=Math.min(card.offsetHeight||140,window.innerHeight-16);
  let top=r.top-ch-8,left=r.left;
  if(top<8)top=r.bottom+8;
  top=Math.min(Math.max(8,top),window.innerHeight-ch-8);
  left=Math.min(Math.max(8,left),window.innerWidth-cw-8);
  card.style.top=`${top}px`;card.style.left=`${left}px`;card.style.width=`${cw}px`;
}

/* ---- 桥A：官方报告页"问研究员" ---- */
function currentReportSectionTitle(win){
  try{
    const nodes=[...win.document.querySelectorAll('[id]')].filter(el=>{
      const r=el.getBoundingClientRect();
      return el.id&&r.height>0&&r.top<=120});
    const cur=nodes[nodes.length-1];
    if(cur){const h=cur.querySelector?.('h1,h2,h3');return (h||cur).textContent.trim().slice(0,80)}
  }catch{}
  return '';
}
function askResearcher(){
  let prefill='';
  try{
    const frame=document.querySelector('#report-frame');
    const sel=frame.contentWindow.getSelection?String(frame.contentWindow.getSelection()):'';
    prefill=sel.trim()?sel.trim().slice(0,300):currentReportSectionTitle(frame.contentWindow);
  }catch{}
  location.hash='#/chat';
  showOfficialInPane('');
  const input=document.querySelector('#question');
  input.value=prefill;input.focus();
}

/* ---- 全局点击分发（3.1）：data 属性 → 处理器映射表，按声明顺序首个命中生效 ---- */
const CLICK_ACTIONS=[
  ['.nav-item[data-nav]',el=>{location.hash='#/'+el.dataset.nav}],
  ['[data-qt-open]',()=>{quotesToastEl?.remove();quotesToastEl=null;openQuotesPanel()}],
  ['[data-q-ask]',el=>{const q=quotes.find(x=>x.id===el.closest('.quote-item')?.dataset.qid);if(q)askFromQuote(q)}],
  ['[data-q-edit]',el=>{quotesEditId=el.closest('.quote-item')?.dataset.qid;renderQuotesPanel()}],
  ['[data-q-save-edit]',el=>{const item=el.closest('.quote-item');
    const q=quotes.find(x=>x.id===item?.dataset.qid);
    if(q){q.question=(item.querySelector('.qi-edit')?.value||'').trim();
      store.set(QUOTES_KEY,quotes)}
    quotesEditId=null;renderQuotesPanel()}],
  ['[data-q-cancel-edit]',()=>{quotesEditId=null;renderQuotesPanel()}],
  ['[data-q-del]',el=>{quotes=quotes.filter(x=>x.id!==el.closest('.quote-item')?.dataset.qid);
    store.set(QUOTES_KEY,quotes);renderQuotesPanel()}],
  ['#quotes-close',()=>closeQuotesPanel()],
  ['[data-session]',el=>switchSession(el.dataset.session)],
  ['[data-view-report]',el=>{const r=findReport(el.dataset.viewReport);if(r)showReport(r,{saved:true,inPlace:true})}],
  ['[data-save-report]',()=>{
    if(!currentResultReport)return;
    upsertReport(currentResultReport);
    announce('已保存到我的报告');
    setStatus('已保存');
    showReport(currentResultReport,{saved:true,inPlace:parseHash()==='result'})}],
  ['[data-del-report]',el=>{
    const id=el.dataset.delReport;
    const r=findReport(id);if(!r)return;
    if(!confirm(`删除报告《${r.title}》？删除后不可恢复。`))return;
    reports=reports.filter(x=>x.report_id!==id);
    store.set(REPORTS_KEY,reports);
    updateLibraryBadge();
    if(currentResultReport?.report_id===id)currentResultReport=null;
    renderLibraryView();
    announce('报告已删除')}],
  ['[data-back-library]',()=>{location.hash='#/library'}],
  ['[data-download]',el=>{const r=findReport(el.dataset.download);if(r)downloadReport(r)}],
  ['[data-open-official]',()=>{location.hash='#/report'}],
  ['[data-close-result]',()=>closeResultSplit()],
  ['#ask-researcher',()=>askResearcher()],
  ['[data-deep-toggle]',()=>{
    // 自动填写优先取输入框里正在输入（未发送）的内容；为空才回退最近一次提问
    const pending=document.querySelector('#question')?.value.trim()||'';
    openDeepForm(pending)}],
  ['[data-generate-report]',()=>{
    // 与 data-deep-toggle 同一优先级：优先填输入框里正在输入（未发送）的内容，为空才回退最近一次提问
    const pending=document.querySelector('#question')?.value.trim()||'';
    openDeepForm(pending)}],
  ['[data-deep-start]',el=>{const card=el.closest('.deep-form');
    const topicEl=card?.querySelector('#deep-topic');
    const topic=(topicEl?.value||'').trim();
    if(!topic){topicEl?.focus();topicEl?.classList.add('input-error');return}
    card?.closest('.msg')?.remove();
    const brief={topic};
    addMsg(`<span class="bubble">${esc(`发起深度分析：${topic}`)}</span>`,'user');
    appendToSession({role:'user',text:`发起深度分析：${topic}`});
    generateLiveReport(topic,brief)}],
  ['[data-deep-cancel]',el=>{el.closest('.deep-form')?.closest('.msg')?.remove()}],
  ['[data-retry]',()=>{if(lastReportQuestion)generateLiveReport(lastReportQuestion)}],
  /* ---- 深度分析等待节点：澄清答复与大纲审查（P0-1） ---- */
  ['[data-clarify-submit]',el=>{
    const card=el.closest('.deep-stage-card');
    const inputs=[...card.querySelectorAll('textarea[data-clarify-idx]')];
    const parts=clarifyQuestions.map((q,i)=>({q,ans:(inputs[i]?.value||'').trim()}))
      .filter(x=>x.ans).map(x=>`【${x.q.question||x.q.field||'补充'}】${x.ans}`);
    if(!parts.length){inputs[0]?.focus();inputs[0]?.classList.add('input-error');return}
    el.disabled=true;
    postDeepAction('clarify',{answer:parts.join('\n'),field:String(clarifyQuestions[0]?.field||'other')})
      .then(()=>{interactiveCardKey=renderedCardKey;card.innerHTML='<p class="status dots" role="status">已收到，正在继续分析…</p>'})
      .catch(err=>{el.disabled=false;deepActionError(card,err)})}],
  ['[data-clarify-skip]',el=>{
    const card=el.closest('.deep-stage-card');
    el.disabled=true;
    postDeepAction('clarify',{answer:'用户选择跳过澄清，请按已有信息直接起草分析计划。',field:'skip'})
      .then(()=>{interactiveCardKey=renderedCardKey;card.innerHTML='<p class="status dots" role="status">正在开始分析…</p>'})
      .catch(err=>{el.disabled=false;deepActionError(card,err)})}],
  ['[data-outline-confirm]',el=>{
    const card=el.closest('.deep-stage-card');
    const payload={action:'confirm'};
    const focus=card.querySelector('#spec-focus')?.value.trim()||'';
    const audience=card.querySelector('#spec-audience')?.value.trim()||'';
    if(focus)payload.focus=focus;
    if(audience)payload.audience=audience;
    el.disabled=true;
    postDeepAction('outline',payload)
      .then(()=>{interactiveCardKey=renderedCardKey;card.innerHTML='<p class="status dots" role="status">大纲已确认，正在执行分析…</p>'})
      .catch(err=>{el.disabled=false;deepActionError(card,err)})}],
  ['[data-outline-edit]',el=>{
    const card=el.closest('.deep-stage-card');
    const keeps=[...card.querySelectorAll('.outline-keep:checked')].map(c=>c.dataset.wsId);
    let plan=null;try{plan=JSON.parse(currentOutlinePlan||'{}')}catch{/* plan_json 损坏时退回重新起草 */}
    if(!plan||!Array.isArray(plan.workstreams)||!plan.workstreams.length||!keeps.length){
      el.disabled=true;deepActionError(card,new Error('请至少保留一个分析条目；若要全部调整请用「重新起草」。'));return}
    if(keeps.length===plan.workstreams.length){card.querySelector('[data-outline-confirm]')?.click();return}
    const edited={...plan,workstreams:plan.workstreams
      .filter(w=>keeps.includes(String(w.id)))
      .map((w,i)=>({...w,id:`w${i+1}`}))};
    el.disabled=true;
    postDeepAction('outline',{action:'edit',plan_json:JSON.stringify(edited)})
      .then(()=>{interactiveCardKey=renderedCardKey;card.innerHTML='<p class="status dots" role="status">已按勾选更新大纲，正在执行分析…</p>'})
      .catch(err=>{el.disabled=false;deepActionError(card,err)})}],
  ['[data-outline-regen]',el=>{el.closest('.deep-stage-card')?.querySelector('.regen-row')?.removeAttribute('hidden');
    el.setAttribute('hidden','')}],
  ['[data-outline-regen-cancel]',el=>{const card=el.closest('.deep-stage-card');
    card?.querySelector('.regen-row')?.setAttribute('hidden','');
    card?.querySelector('[data-outline-regen]')?.removeAttribute('hidden')}],
  ['[data-outline-regen-send]',el=>{
    const card=el.closest('.deep-stage-card');
    const feedback=card.querySelector('#regen-feedback')?.value.trim()||'';
    el.disabled=true;
    postDeepAction('outline',feedback?{action:'regenerate',feedback}:{action:'regenerate'})
      .then(()=>{interactiveCardKey=renderedCardKey;card.innerHTML='<p class="status dots" role="status">正在重新起草分析大纲…</p>'})
      .catch(err=>{el.disabled=false;deepActionError(card,err)})}],
  ['[data-prompt]',el=>{const input=document.querySelector('#question');input.value=el.dataset.prompt;input.focus();
    if(parseHash()!=='chat')location.hash='#/chat'}],
  ['.cite-inline[data-srcs]',el=>showSourceCard(el.dataset.srcs,el)],
  ['[data-ask-prefill]',el=>{const input=document.querySelector('#question');
    input.value=`@${el.dataset.askPrefill} `;
    hideSuggest();showReportSuggest('');input.focus()}],
  ['[data-quote-remove]',()=>setComposerQuote(null)],
  ['[data-suggest-idx]',el=>{if(suggestState)applySuggest(suggestState.items[Number(el.dataset.suggestIdx)])}],
  ['[data-fill]',el=>{const input=document.querySelector('#question');input.value=`「${el.dataset.fill}」有哪些负向反馈？`;input.focus()}],
  ['[data-run]',el=>{const q=el.dataset.run;addMsg(`<span class="bubble">${esc(q)}</span>`,'user');askOnce(q)}],
];
document.body.addEventListener('click',e=>{
  // 浮层收起判定先于动作分发（原 if 链行为保持不变）
  if(!e.target.closest('.quote-form'))hideCitePick();
  if(!e.target.closest('.cite-inline')&&!e.target.closest('.source-card'))hideSourceCard();
  if(e.target.id==='quotes-panel'){closeQuotesPanel();return}
  for(const [selector,run] of CLICK_ACTIONS){
    const el=e.target.closest(selector);
    if(el){run(el,e);return}
  }
});

/* ---- 桥C：报告划词记录问题（多位置统一，累积保存） ---- */
const QUOTES_KEY='ai.quotes.v1';const MAX_QUOTES=50;
let quotes=store.get(QUOTES_KEY)||[];
let citeFormEl=null;
function hideCitePick(){citeFormEl?.remove();citeFormEl=null}
let quotesToastEl=null;
function showQuotesToast(){
  quotesToastEl?.remove();
  const t=document.createElement('div');
  t.className='quotes-toast';
  t.innerHTML=`<span>已保存到划词笔记</span><button type="button" class="btn-ghost" data-qt-open>查看</button>`;
  document.body.appendChild(t);
  quotesToastEl=t;
  setTimeout(()=>{t.classList.add('out');setTimeout(()=>{t.remove();if(quotesToastEl===t)quotesToastEl=null},300)},4000)}
function saveQuote(q){
  quotes.unshift({id:`q-${Date.now().toString(36)}-${Math.random().toString(36).slice(2,6)}`,
    created_at:Date.now(),text:'',question:'',source:'',section:'',kind:'official',report_id:'',...q});
  if(quotes.length>MAX_QUOTES)quotes.length=MAX_QUOTES;
  store.set(QUOTES_KEY,quotes);
  showQuotesToast()}
function showCitePick(text,ref,rect,context){
  hideCitePick();
  const r=rect||(window.getSelection?.().rangeCount?window.getSelection().getRangeAt(0).getBoundingClientRect():null);
  const selText=String(text||'').trim();
  const form=document.createElement('div');
  form.className='quote-form';form.setAttribute('role','group');form.setAttribute('aria-label','记录划词问题');
  form.innerHTML=`<input class="qf-input" maxlength="300" placeholder="想问什么？（可留空）" aria-label="记录划词问题">
    <div class="qf-actions">
      <button type="button" class="btn-ghost" data-qf-save>保存</button>
      <button type="button" class="btn-ghost" data-qf-ask>立即提问</button>
    </div>
    <button type="button" class="qf-x" aria-label="关闭" data-qf-close aria-hidden="true">×</button>`;
  document.body.appendChild(form);
  citeFormEl=form;
  // 视口内夹取：优先放在选区下方，空间不足翻到上方
  const fw=Math.min(300,window.innerWidth-24);
  const fh=form.offsetHeight||150;
  let top=r?r.bottom+8:120,left=r?r.left:120;
  if(r&&top+fh>window.innerHeight-8)top=r.top-fh-8;
  top=Math.min(Math.max(8,top),Math.max(8,window.innerHeight-fh-8));
  left=Math.min(Math.max(8,left),window.innerWidth-fw-8);
  form.style.top=`${top}px`;form.style.left=`${left}px`;form.style.width=`${fw}px`;
  const input=form.querySelector('.qf-input');
  input?.focus();
  form.addEventListener('click',e=>{
    if(e.target.closest('[data-qf-close]')){hideCitePick();return}
    const payload=()=>({text:selText,question:input.value.trim(),source:ref.name,
      section:context?.section||'',kind:ref.kind,report_id:ref.report_id||''});
    if(e.target.closest('[data-qf-save]')){saveQuote(payload());hideCitePick();return}
    if(e.target.closest('[data-qf-ask]')){
      const question=input.value.trim();
      saveQuote(payload());
      hideCitePick();
      location.hash='#/chat';
      openResultSplit();
      setComposerQuote({text:selText,source:ref.name,section:context?.section||''});
      const qi=document.querySelector('#question');
      qi.value=(`@${ref.name} ${question}`).trim()+' ';
      qi.focus();return}
  });
}
// 选区上方最近的编号标题，作为选段来源上下文（官方报告与我的报告均按 [id] 标题组织）
function selectionContext(win,range,vpTop){
  try{
    const nodes=[...win.document.querySelectorAll('[id]')].filter(el=>{
      const r=el.getBoundingClientRect();
      return el.id&&r.height>0&&r.top<=vpTop+2});
    const cur=nodes[nodes.length-1];
    if(cur){const h=cur.querySelector?.('h1,h2,h3,h4');return (h||cur).textContent.trim().slice(0,60)}
  }catch{}
  return '';
}
// 在同源 iframe 或主文档上绑定：划词出记录框、点击/滚动收起
function attachSelectionPicker(frame,ref){
  let doc;
  try{doc=frame.contentDocument;if(!doc)return}catch{return}
  doc.addEventListener('pointerup',()=>{
    setTimeout(()=>{
      const selObj=frame.contentWindow.getSelection?.();
      const sel=selObj?String(selObj):'';
      if(!sel.trim()){hideCitePick();return}
      const rect=selObj.rangeCount?selObj.getRangeAt(0).getBoundingClientRect():null;
      const fr=frame.getBoundingClientRect();
      const vp=rect?{top:rect.top+fr.top,left:rect.left+fr.left,bottom:rect.bottom+fr.top}:null;
      const section=vp?selectionContext(frame.contentWindow,selObj.getRangeAt(0),vp.top):'';
      showCitePick(sel,ref,vp,{section});
    },10);
  });
  doc.addEventListener('click',hideCitePick);
  doc.addEventListener('scroll',hideCitePick,{passive:true});
}
const resultViewEl=document.querySelector('#result-view');
resultViewEl?.addEventListener('pointerup',()=>{
  setTimeout(()=>{
    const selObj=window.getSelection();
    const sel=selObj?String(selObj):'';
    if(!sel.trim()||!currentResultReport){hideCitePick();return}
    const rect=selObj.rangeCount?selObj.getRangeAt(0).getBoundingClientRect():null;
    const section=rect?selectionContext(window,selObj.getRangeAt(0),rect.top):'';
    showCitePick(sel,{name:currentResultReport.title,kind:'mine',
      report_id:currentResultReport.report_id},rect,{section});
  },10);
});
resultViewEl?.addEventListener('scroll',hideCitePick,{passive:true});
chatLog?.addEventListener('scroll',()=>{hideSourceCard();hideCitePick()},{passive:true});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){hideSourceCard();hideCitePick();closeQuotesPanel()}});
// 官方报告阅读页（#/report）同样支持划词记录问题
const docFrame=document.querySelector('#report-frame');
docFrame?.addEventListener('load',()=>attachSelectionPicker(docFrame,{name:'官方报告',kind:'official',report_id:''}));

/* ---- 划词笔记：统一轻量管理界面（查看 / 编辑 / 删除 / 发起对话） ---- */
let quotesEditId=null;
let quotesLastFocus=null;
function openQuotesPanel(){
  renderQuotesPanel();
  const p=document.querySelector('#quotes-panel');if(!p)return;
  quotesLastFocus=document.activeElement;
  p.hidden=false;
  p.querySelector('#quotes-close')?.focus()}  // 焦点移入 dialog（5.4）
function closeQuotesPanel(){
  const p=document.querySelector('#quotes-panel');if(p)p.hidden=true;
  quotesEditId=null;
  if(quotesLastFocus&&document.contains(quotesLastFocus)){quotesLastFocus.focus();quotesLastFocus=null}}  // 焦点还原
// dialog 焦点圈闭：Tab 在面板内循环，不逃逸到背景页面（5.4）
document.querySelector('#quotes-panel')?.addEventListener('keydown',e=>{
  if(e.key!=='Tab')return;
  const panel=e.currentTarget;
  const focusables=[...panel.querySelectorAll('button,textarea,input,[href]')]
    .filter(el=>!el.disabled&&!el.closest('[hidden]'));
  if(!focusables.length)return;
  const first=focusables[0],last=focusables[focusables.length-1];
  if(e.shiftKey&&(document.activeElement===first||!panel.contains(document.activeElement))){e.preventDefault();last.focus()}
  else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}
});
function renderQuotesPanel(){
  const list=document.querySelector('#quotes-list');
  if(!list)return;
  if(!quotes.length){
    list.innerHTML='<p class="quotes-empty">还没有划词记录。在官方报告阅读页、对话分栏或「我的报告」中划选文字，即可记录问题。</p>';
    return}
  list.innerHTML=quotes.map(q=>`
    <article class="quote-item" data-qid="${esc(q.id)}">
      <div class="qi-head"><span class="tag">${esc(q.source||'报告')}</span>
        ${q.section?`<span class="qi-src">${esc(q.section)}</span>`:''}
        <span class="qi-time">${esc(relTime(q.created_at))}</span></div>
      <blockquote class="qi-text">“${esc(String(q.text||'').slice(0,160))}${String(q.text||'').length>160?'…':''}”</blockquote>
      ${quotesEditId===q.id
        ?`<textarea class="qi-edit" maxlength="300" aria-label="编辑问题">${esc(q.question||'')}</textarea>
          <div class="qi-actions"><button type="button" class="button primary" data-q-save-edit>保存修改</button>
          <button type="button" class="btn-ghost" data-q-cancel-edit>取消</button></div>`
        :`<p class="qi-q">${q.question?esc(q.question):'<span class="qi-unset">未填写问题</span>'}</p>
          <div class="qi-actions"><button type="button" class="button primary" data-q-ask>问研究员</button>
          <button type="button" class="btn-ghost" data-q-edit>编辑</button>
          <button type="button" class="btn-ghost" data-q-del>删除</button></div>`}
    </article>`).join('');
}
function askFromQuote(q){
  closeQuotesPanel();
  location.hash='#/chat';
  openResultSplit();
  setComposerQuote({text:q.text,source:q.source,section:q.section});
  const input=document.querySelector('#question');
  input.value=(`@${q.source} ${q.question||''}`).trim()+' ';
  input.focus();
}

/* ---- 侧栏抽屉（窄屏） ---- */
const sidebar=document.querySelector('#sidebar'),mask=document.querySelector('#sidebar-mask'),menuBtn=document.querySelector('#menu-btn'),chatMenuBtn=document.querySelector('#chat-menu');
function openSidebar(){sidebar.classList.add('open');mask.hidden=false;menuBtn.setAttribute('aria-expanded','true');chatMenuBtn?.setAttribute('aria-expanded','true')}
function closeSidebar(){if(window.innerWidth>=1024)return;sidebar.classList.remove('open');mask.hidden=true;menuBtn.setAttribute('aria-expanded','false');chatMenuBtn?.setAttribute('aria-expanded','false')}
menuBtn.addEventListener('click',()=>sidebar.classList.contains('open')?closeSidebar():openSidebar());
chatMenuBtn?.addEventListener('click',()=>sidebar.classList.contains('open')?closeSidebar():openSidebar());
mask.addEventListener('click',closeSidebar);
window.addEventListener('resize',()=>{if(window.innerWidth>=1024){sidebar.classList.remove('open');mask.hidden=true;menuBtn.setAttribute('aria-expanded','false');chatMenuBtn?.setAttribute('aria-expanded','false')}});

/* ---- 结果分栏拖拽调宽 ---- */
const divider=document.querySelector('#result-divider');
function clampResultW(w){
  const maxW=Math.round(workspace.clientWidth*0.72);
  return Math.min(Math.max(Math.round(w),320),maxW)}
function applyResultW(w){
  w=clampResultW(w);
  document.documentElement.style.setProperty('--result-w',w+'px');
  divider.setAttribute('aria-valuemax',String(clampResultW(workspace.clientWidth)));
  divider.setAttribute('aria-valuenow',String(w));
  return w}
divider.addEventListener('mousedown',e=>{
  e.preventDefault();
  const pane=document.querySelector('#result-pane');
  function move(ev){
    applyResultW(workspace.getBoundingClientRect().right-ev.clientX)}
  function up(){
    document.removeEventListener('mousemove',move);
    document.removeEventListener('mouseup',up);
    store.set(RESULT_W_KEY,Math.round(pane.getBoundingClientRect().width))}
  document.addEventListener('mousemove',move);
  document.addEventListener('mouseup',up)});
// 键盘调宽（5.6）：← 加宽报告栏，→ 收窄；分隔条聚焦时可见
divider.addEventListener('keydown',e=>{
  if(e.key!=='ArrowLeft'&&e.key!=='ArrowRight')return;
  e.preventDefault();
  const pane=document.querySelector('#result-pane');
  const cur=pane.getBoundingClientRect().width;
  const w=applyResultW(cur+(e.key==='ArrowLeft'?16:-16));
  store.set(RESULT_W_KEY,w)});

/* ---- 侧栏收起 / 展开（桌面端，状态持久化） ---- */
const SIDEBAR_KEY='ai.sidebar';
const shell=document.querySelector('.shell');
const collapseBtn=document.querySelector('#sidebar-collapse');
const expandBtn=document.querySelector('#sidebar-expand');
function setSidebarCollapsed(collapsed){
  shell.classList.toggle('sidebar-collapsed',collapsed);
  collapseBtn?.setAttribute('aria-expanded',String(!collapsed));
  expandBtn?.setAttribute('aria-expanded',String(collapsed));
  // 收起时让侧栏不可聚焦，避免 Tab 进入不可见区域
  if(sidebar)sidebar.inert=Boolean(collapsed)&&window.innerWidth>=1024;
  store.set(SIDEBAR_KEY,collapsed?'collapsed':'expanded')}
collapseBtn?.addEventListener('click',()=>setSidebarCollapsed(true));
expandBtn?.addEventListener('click',()=>setSidebarCollapsed(false));
window.addEventListener('resize',()=>{
  if(sidebar&&window.innerWidth<1024)sidebar.inert=false;
  else if(sidebar)sidebar.inert=shell.classList.contains('sidebar-collapsed')});
setSidebarCollapsed(store.get(SIDEBAR_KEY)==='collapsed');

/* ---- 初始化：落地视图、宽度、最近会话与进行中任务 ---- */
const savedW=Number(store.get(RESULT_W_KEY));
if(savedW>=320)document.documentElement.style.setProperty('--result-w',savedW+'px');
(function restoreView(){
  if(location.hash.slice(1))return;
  const saved=store.get(LAST_VIEW_KEY);
  location.hash=saved&&saved!=='result'?`#/${saved}`:'#/official';  // 首访落地官方报告
})();
if(sessions.length){
  const first=sessions[0];
  sessionId=first.id;currentSession=first;   // 保留为当前会话，后续消息继续追加
  if(first.messages.length)renderSessionMessages(first);
  else renderEmptyState();                   // 空会话也展示空状态与示例芯片
}else renderEmptyState();
renderSessionList();
updateLibraryBadge();
renderLibraryViewIfNeeded();
showView();
const activeJob=store.get(ACTIVE_JOB_KEY);
if(activeJob&&activeJob.status_url)resumeLiveJob(activeJob);
