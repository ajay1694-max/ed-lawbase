// Account-scoped research tools. No third-party scripts or remote services.
let WHO = {}, searchState = {}, activeTab = 'judgments', currentCase = null;
const post = async (path, body) => {
  const r = await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(r.status===401){location.href='/login.html';throw Error('Please sign in');}
  const d = await r.json(); if(!r.ok || d.error) throw Error(d.error||'Request failed'); return d;
};
const safeURL = url => /^https?:\/\//i.test(url||'') ? esc(url) : '';
const notice = (el, message, bad=false) => { el.textContent=message; el.classList.toggle('error',bad); };
const action = (selector, fn) => { $(selector).onclick=async e=>{const b=e.currentTarget;b.disabled=true;try{await fn(e);}catch(err){alert(err.message);}finally{b.disabled=false;}}; };
function addBasket(id,title){if(!basket.includes(id)){if(basket.length>=20){alert('Export up to 20 judgments at once.');return;}basket.push(id);}if(title)basketTitles[id]=title;saveBasket();}
// Cause title from "<case no.> of <petitioner> Vs <respondent>"; null when the title has no "versus".
function parties(title){const m=String(title||'').match(/^(?:(.*?)\s+of\s+)?(.+?)\s+(?:vs\.?|versus|v\.)\s+(.+)$/i);return m?{no:(m[1]||'').replace(/^\//,'').trim(),pet:m[2].trim(),res:m[3].replace(/[,\s]+$/,'').trim()}:null;}
// The judges field is often stray extracted text ("him, by an", "Court No. 17"); show it only when it reads like names.
function cleanJudges(j){j=String(j||'').trim();if(!j||j.length>220)return '';const parts=j.split(/[;,]/).map(s=>s.trim()).filter(Boolean);
  const bad=/\b(by|is|an|as|which|therefore|petitioner|accused|court|room|district|act|risk|wife|directors?|investigating|release|scc)\b/i;
  return parts.length&&parts.every(p=>/^[A-Z][A-Za-z .()'’-]{1,70}$/.test(p)&&!bad.test(p))&&/\.|justice/i.test(j)?j:'';}
const fact=(k,v)=>v?`<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`:'';
function caseLink(id, passage){const u=new URL(location.href);u.searchParams.set('case',id);if(passage!==undefined)u.searchParams.set('passage',passage);else u.searchParams.delete('passage');return u.href;}
async function copyText(text){try{await navigator.clipboard.writeText(text);notice($('#bMsg'),'Copied');}catch(e){prompt('Copy this text:',text);}}
let readerRequest=0;
function setTab(name){readerRequest++;activeTab=name;document.body.classList.remove('reader-wide');document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('on',b.dataset.tab===name));return tabs[name]();}
function rememberURL(){const u=new URL(location.href);u.search='';for(const [k,v] of Object.entries(searchState))if(v)u.searchParams.set(k,v);history.replaceState({},'',u);}

function judgmentsTab(){
  $('#left').innerHTML=`<h3>Find judgments</h3><div class="bar"><input aria-label="Judgment search" type="search" id="q" placeholder="Case name, citation, or judgment text"><button class="go" id="go">Search</button><button class="small" id="resetSearch">Clear</button></div>
  <div class="bar"><select id="court" aria-label="Court"><option value="">All courts</option>${META.courts.map(c=>`<option value="${esc(c.court_slug)}">${esc(c.court)} (${c.n})</option>`).join('')}</select>
  <select id="act" aria-label="Act"><option value="">Any Act</option>${['PMLA','FEMA','FEOA','FERA'].map(a=>`<option>${a}</option>`).join('')}</select>
  <select id="issue" aria-label="Issue"><option value="">Any issue</option>${META.issues.map(i=>`<option value="${esc(i.issue)}">${esc(i.label)} (${i.n})</option>`).join('')}</select>
  <input id="year_from" type="number" aria-label="From year" placeholder="From year" style="width:110px"><input id="year_to" type="number" aria-label="To year" placeholder="To year" style="width:110px"></div>
  <div class="bar"><label><input type="checkbox" id="same"> Same passage only</label><select id="sort" aria-label="Sort order"><option value="relevance">Relevance</option><option value="newest">Newest first</option><option value="oldest">Oldest first</option></select><select id="limit" aria-label="Results per page"><option value="25">25 per page</option><option value="50">50 per page</option></select><button class="small" id="saveSearch">Save search</button></div>
  <div id="activeFilters" class="activefilters" aria-label="Active filters"></div>
  <p class="hint">All words must appear in the judgment. Use quotation marks for phrases, or OR for alternatives.</p><div id="results" aria-live="polite"></div>`;
  for(const k of ['q','court','act','issue','year_from','year_to','sort','limit'])if(searchState[k])$('#'+k).value=searchState[k];
  $('#same').checked=searchState.within==='chunk';
  const values=()=>Object.fromEntries(['q','court','act','issue','year_from','year_to','sort','limit'].map(k=>[k,$('#'+k).value]).concat([['within',$('#same').checked?'chunk':'case']]));
  const drawActive=()=>{const v=values(),items=[];
    if(v.court)items.push(['court',(META.courts.find(c=>c.court_slug===v.court)||{}).court||v.court]);if(v.act)items.push(['act',v.act]);
    if(v.issue)items.push(['issue',(META.issues.find(i=>i.issue===v.issue)||{}).label||v.issue]);if(v.year_from)items.push(['year_from','From '+v.year_from]);
    if(v.year_to)items.push(['year_to','To '+v.year_to]);if(v.within==='chunk')items.push(['same','Same passage only']);if(v.sort!=='relevance')items.push(['sort',v.sort==='newest'?'Newest first':'Oldest first']);
    $('#activeFilters').innerHTML=items.map(([k,l])=>`<button class="ftag" data-k="${k}" title="Remove this filter">${esc(l)}<span aria-hidden="true">×</span></button>`).join('')+(items.length>1?'<button class="ftag clear" data-k="*">Clear all filters</button>':'');
    $('#activeFilters').querySelectorAll('.ftag').forEach(b=>b.onclick=()=>{for(const f of b.dataset.k==='*'?['court','act','issue','year_from','year_to','same','sort']:[b.dataset.k]){if(f==='same')$('#same').checked=false;else if(f==='sort')$('#sort').value='relevance';else $('#'+f).value='';}
      drawActive();const w=values();if(w.q||w.court||w.issue||w.act)run();else{$('#results').innerHTML='';searchState={};rememberURL();}});};
  for(const k of ['court','act','issue','year_from','year_to','sort','same'])$('#'+k).addEventListener('change',drawActive);
  drawActive();
  const run=async(offset=0)=>{
    searchState={...values(),offset};rememberURL();drawActive();const target=$('#results'),go=$('#go');go.disabled=true;target.textContent='Searching…';const started=performance.now();
    try{
      const d=await api('/api/search',searchState);if(!target.isConnected)return;
      target.innerHTML=`<p class="hint">${d.total.toLocaleString()} matching judgments · ${d.results.length?d.offset+1:0}–${d.offset+d.results.length} · ${((performance.now()-started)/1000).toFixed(1)}s</p>`+d.results.map(r=>`<article class="res"><button class="small open" data-id="${esc(r.case_id)}"><strong>${esc(r.title)}</strong></button><div class="m">${esc(r.court)} · ${esc(r.decision_date)} · ${esc(r.citation)} ${r.hits?'· '+r.hits+' matching passages':''}</div>${r.curated.map(h=>`<div class="snip">${esc(h.summary)}</div>`).join('')}${r.snips.map(s=>`<div class="snip">…${snip(s)}…</div>`).join('')}<div>${r.issues.map(i=>`<span class="chip">${esc(i.label||i.issue)}</span>`).join('')}</div><button class="small add" data-id="${esc(r.case_id)}" data-title="${esc(r.title)}">＋ export list</button></article>`).join('')+`<div class="bar" style="margin-top:12px"><button class="small" id="prev" ${d.offset===0?'disabled':''}>Previous</button><button class="small" id="next" ${!d.has_more?'disabled':''}>Next</button></div>`;
      target.parentElement.scrollTop=0;
      target.querySelectorAll('.open').forEach(b=>b.onclick=()=>openCase(b.dataset.id));target.querySelectorAll('.add').forEach(b=>b.onclick=()=>addBasket(b.dataset.id,b.dataset.title));
      $('#prev').onclick=()=>run(Math.max(0,d.offset-d.limit));$('#next').onclick=()=>run(d.offset+d.limit);
    }catch(e){if(target.isConnected)notice(target,e.message,true);}finally{go.disabled=false;}
  };
  $('#go').onclick=()=>run();$('#q').onkeydown=e=>{if(e.key==='Enter')run();};$('#resetSearch').onclick=()=>{searchState={};rememberURL();judgmentsTab();};
  action('#saveSearch',async()=>{const title=prompt('Name for this saved search:', $('#q').value||'Filtered judgments');if(title){await post('/api/searches/save',{title,params:values()});notice($('#bMsg'),'Saved to My research');}});
  if(searchState.q||searchState.court||searchState.issue||searchState.act)run(Number(searchState.offset)||0);
};

async function openCase(id, passage){
  const request=++readerRequest;
  const target=$('#right');target.textContent='Loading…';
  try{
    const d=await api('/api/case',{id});if(request!==readerRequest)return;currentCase=d;const c=d.case;
    history.replaceState({},'',caseLink(id,passage));
    const pt=parties(c.title),caseNo=(pt&&pt.no)||c.case_number;
    target.innerHTML=`<div class="causetitle"><div class="ct-court">${esc(c.court)}</div>${caseNo?`<div class="ct-no">${esc(caseNo)}</div>`:''}
    <h2>${pt?`<span class="ct-party">${esc(pt.pet)}</span><span class="ct-v">versus</span><span class="ct-party">${esc(pt.res)}</span>`:esc(c.title)}</h2>
    <dl class="ct-facts">${fact('Decided',c.decision_date)}${fact('Citation',c.citation)}${c.case_number&&c.case_number!==caseNo?fact('Case no.',c.case_number):''}${fact('Judge(s) as recorded',cleanJudges(c.judges))}${fact('Acts',c.acts||'Unrecorded')}${fact('Result',c.disposition)}</dl></div>
    <div class="bar">${safeURL(c.source_url)?`<a href="${safeURL(c.source_url)}" target="_blank" rel="noopener">Open ${esc(d.source_kind)}</a>`:'<span class="hint">Original PDF not linked</span>'}<button class="small" id="requestSource">Request a source / correction</button></div>
    <div class="tools"><div class="bar"><button class="small" id="xCase">Download DOCX</button><button class="small" id="xAdd">＋ export list</button><button class="small" id="copyCitation">Copy citation</button><button class="small" id="copyLink">Copy link</button><button class="small" id="wide">Expand reader</button><button class="small" id="fontDown" aria-label="Smaller text">A−</button><button class="small" id="fontUp" aria-label="Larger text">A＋</button></div>
    <div class="bar"><input type="search" id="findText" aria-label="Find in judgment" placeholder="Find in this judgment"><button class="small" id="findPrev">Previous match</button><button class="small" id="findNext">Next match</button><span class="hint" id="findCount"></span></div></div>
    <details id="notes"><summary>Save to a folder / add a note</summary><p class="hint">Saved under ${esc(WHO.username)}. Anyone using this same login shares its research workspace.</p><label class="field">Folder<input id="folder" maxlength="100" value="Saved judgments"></label><label class="field">Note<textarea id="note" maxlength="10000"></textarea></label><label class="field">Saved extract<textarea id="quote" maxlength="10000"></textarea></label><label class="field">Source page / paragraph or LawBase passage<input id="locator" maxlength="100"></label><button class="small" id="takeSelection">Use selected text</button> <button class="go" id="saveNote">Save research</button><span id="noteStatus" role="status"></span></details>
    ${d.curated.map(h=>`<div class="headnote"><strong>Research headnote</strong> · ${esc(h.tier)} · ${esc(h.status)}<p>${esc(h.summary)}</p>${md(h.body||'')}</div>`).join('')}
    <p class="hint">Passage numbers below locate extracted text in LawBase; they are not the court’s paragraph numbers. Check the original before citation.</p>
    <div class="txt" id="judgmentText">${d.chunks.map(ch=>`<section class="passage" id="passage-${Number(ch.chunk_index)}"><button class="small passageCopy" data-index="${Number(ch.chunk_index)}">Copy passage ${Number(ch.chunk_index)+1} with citation</button><p data-index="${Number(ch.chunk_index)}">${esc(ch.text.replace(/\[(SECTION|TITLE)\]\s*#*\s*/g,''))}</p></section>`).join('')}</div>`;
    $('#xCase').onclick=()=>download({kind:'case',id});$('#xAdd').onclick=()=>addBasket(id,c.title);
    const cite=[c.title,c.citation,c.court,c.decision_date].filter(Boolean).join(' · ');
    $('#copyCitation').onclick=()=>copyText(cite);$('#copyLink').onclick=()=>copyText(caseLink(id));
    $('#requestSource').onclick=()=>{setTab('contribute');$('#submitTitle').value=c.title;$('#submitCitation').value=c.citation||c.case_number||id;};
    $('#wide').onclick=()=>{document.body.classList.toggle('reader-wide');$('#wide').textContent=document.body.classList.contains('reader-wide')?'Split reader':'Expand reader';};
    let font=15;const resize=n=>{$('#judgmentText').style.fontSize=(font=Math.min(24,Math.max(12,font+n)))+'px';};$('#fontDown').onclick=()=>resize(-1);$('#fontUp').onclick=()=>resize(1);
    document.querySelectorAll('.passageCopy').forEach(b=>b.onclick=()=>{const ch=d.chunks.find(x=>x.chunk_index===Number(b.dataset.index));copyText(ch.text+'\n\n'+cite+'\nLawBase extracted passage '+(ch.chunk_index+1)+' (verify original paragraph/page)\n'+caseLink(id,ch.chunk_index));});
    let marks=[],at=-1;
    const move=delta=>{if(!marks.length)return;at=(at+delta+marks.length)%marks.length;marks.forEach(m=>m.style.outline='');marks[at].style.outline='2px solid #b77900';marks[at].scrollIntoView({block:'center'});$('#findCount').textContent=(at+1)+' / '+marks.length;};
    $('#findText').oninput=()=>{const needle=$('#findText').value.toLowerCase();document.querySelectorAll('#judgmentText p').forEach(p=>{const text=d.chunks.find(ch=>ch.chunk_index===Number(p.dataset.index)).text.replace(/\[(SECTION|TITLE)\]\s*#*\s*/g,'');if(!needle){p.textContent=text;return;}let out='',pos=0,idx;while((idx=text.toLowerCase().indexOf(needle,pos))>=0){out+=esc(text.slice(pos,idx))+'<mark>'+esc(text.slice(idx,idx+needle.length))+'</mark>';pos=idx+needle.length;}p.innerHTML=out+esc(text.slice(pos));});marks=[...document.querySelectorAll('#judgmentText mark')];at=-1;$('#findCount').textContent=marks.length+' matches';if(marks.length)move(1);};
    $('#findNext').onclick=()=>move(1);$('#findPrev').onclick=()=>move(-1);$('#findText').onkeydown=e=>{if(e.key==='Enter')move(e.shiftKey?-1:1);};
    $('#takeSelection').onmousedown=e=>e.preventDefault();$('#takeSelection').onclick=()=>{const s=getSelection();if(s && $('#judgmentText').contains(s.anchorNode)){$('#quote').value=s.toString();const p=s.anchorNode.parentElement.closest('[data-index]');if(p)$('#locator').value='LawBase extracted passage '+(Number(p.dataset.index)+1);}else notice($('#noteStatus'),'Select text in the judgment first',true);};
    action('#saveNote',async()=>{await post('/api/library/save',{case_id:id,folder:$('#folder').value,note:$('#note').value,quote:$('#quote').value,locator:$('#locator').value});notice($('#noteStatus'),' Saved');});
    api('/api/library').then(lib=>{if(currentCase!==d)return;const item=lib.items.find(x=>x.case_id===id);if(item)for(const k of ['folder','note','quote','locator'])$('#'+k).value=item[k]||'';}).catch(()=>{});
    if(passage!==undefined){const anchor=$('#passage-'+Number(passage));if(anchor){anchor.style.borderColor='var(--navy)';anchor.scrollIntoView({block:'center'});}}
  }catch(e){notice(target,e.message,true);}
};

async function libraryTab(){
  $('#left').innerHTML='<h3>My research</h3><p>Loading…</p>';
  try{const d=await api('/api/library');$('#left').innerHTML=`<h3>My research</h3><p class="hint">Workspace for ${esc(WHO.username)}. Shared logins share notes and folders.</p><label>Folder <select id="folderFilter"><option value="">All folders</option>${[...new Set(d.items.map(i=>i.folder))].map(f=>`<option>${esc(f)}</option>`).join('')}</select></label><div id="savedItems"></div><h3>Saved searches</h3><div id="savedSearches"></div>`;
  const draw=()=>{$('#savedItems').innerHTML=d.items.filter(i=>!$('#folderFilter').value||i.folder===$('#folderFilter').value).map(i=>`<article class="res"><span class="chip">${esc(i.folder)}</span><p><button class="small savedOpen" data-id="${esc(i.case_id)}">${esc(i.case.title)}</button></p><p>${esc(i.note)}</p>${i.quote?`<blockquote>${esc(i.quote)}</blockquote><p class="hint">${esc(i.locator)}</p>`:''}<button class="small removeSaved" data-id="${esc(i.case_id)}">Remove bookmark and note</button></article>`).join('')||'<p class="hint">Open a judgment to save it to a folder.</p>';document.querySelectorAll('.savedOpen').forEach(b=>b.onclick=()=>openCase(b.dataset.id));document.querySelectorAll('.removeSaved').forEach(b=>b.onclick=async()=>{if(confirm('Remove this saved note and bookmark?')){await post('/api/library/save',{case_id:b.dataset.id,remove:true});libraryTab();}});};$('#folderFilter').onchange=draw;draw();
  $('#savedSearches').innerHTML=d.searches.map(s=>`<div class="res"><button class="small savedRun" data-id="${esc(s.id)}">${esc(s.title)}</button> <button class="small deleteSearch" data-id="${esc(s.id)}">Remove</button></div>`).join('')||'<p class="hint">Use Save search on the Judgments tab.</p>';
  document.querySelectorAll('.savedRun').forEach(b=>b.onclick=()=>{searchState=JSON.parse(d.searches.find(s=>s.id===b.dataset.id).params);setTab('judgments');});document.querySelectorAll('.deleteSearch').forEach(b=>b.onclick=async()=>{await post('/api/searches/save',{id:b.dataset.id,remove:true});libraryTab();});
  }catch(e){notice($('#left'),e.message,true);}
}

function contributeTab(){
  $('#left').innerHTML=`<h3>Enrich the judgment library</h3><p>Upload a public judgment or request one by citation. Submissions enter a review queue; verified additions then become searchable for the team.</p>
  <form id="submissionForm"><label class="field">Your name<input id="contributor" maxlength="120" required value="${esc(localStorageGet('lb-contributor:'+WHO.username)||WHO.username)}"></label>
  <label class="field">Case title<input id="submitTitle" maxlength="300" required></label><label class="field">Citation / case number<input id="submitCitation" maxlength="300" placeholder="For example: 2026 INSC …"></label><label class="field">Official source link (optional)<input id="sourceURL" type="url" maxlength="1500" placeholder="https://…"></label><label class="field">Judgment PDF (optional, up to 8 MB)<input id="pdf" type="file" accept="application/pdf,.pdf"></label><label class="field">What should be added or corrected?<textarea id="submitNote" maxlength="4000"></textarea></label><label><input id="publicJudgment" type="checkbox" required> This is a public judgment or a request for one, without confidential case material.</label><p><button class="go" type="submit" id="sendSubmission">Submit for review</button></p><p id="submissionStatus" role="status"></p></form>`;
  $('#right').innerHTML='<h3>My submissions</h3><div id="mySubmissions">Loading…</div>';loadQueue(false);
  $('#submissionForm').onsubmit=async e=>{e.preventDefault();const b=$('#sendSubmission'),msg=$('#submissionStatus');b.disabled=true;try{let pdf_base64='',filename='';const file=$('#pdf').files[0];if(file){if(file.size>8*1024*1024)throw Error('PDF must be 8 MB or smaller. Use a citation or official link for a larger document.');filename=file.name;const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));pdf_base64=btoa(binary);}const contributor=$('#contributor').value;const d=await post('/api/submissions/create',{contributor,title:$('#submitTitle').value,citation:$('#submitCitation').value,source_url:$('#sourceURL').value,note:$('#submitNote').value,public_judgment:$('#publicJudgment').checked,pdf_base64,filename});localStorageSet('lb-contributor:'+WHO.username,contributor);notice(msg,d.duplicate?'This submission is already in your queue.':'Submitted for review. Reference '+d.id.slice(0,8));$('#pdf').value='';await loadQueue(false);}catch(err){notice(msg,err.message,true);}finally{b.disabled=false;}};
}

async function loadQueue(admin){
  const target=admin?$('#left'):$('#mySubmissions');
  try{const d=await api('/api/submissions');if(!target?.isConnected)return;
    const items=admin?d.items:d.items.filter(i=>i.owner===WHO.username);
    target.innerHTML=(admin?'<h3>Review queue</h3><p class="hint">'+d.pending+' open submissions. Verify sources and import through the reviewed content pipeline before marking an item integrated.</p><label>Show <select id="queueFilter"><option value="open">Open requests</option><option value="all">All requests</option></select></label>':'')+'<div id="queueItems"></div>';
    const draw=()=>{const visible=items.filter(i=>!admin||$('#queueFilter').value==='all'||['submitted','reviewing','needs_info'].includes(i.status));$('#queueItems').innerHTML=visible.map(i=>`<article class="res"><span class="chip">${esc(i.status.replaceAll('_',' '))}</span><strong> ${esc(i.title)}</strong><p class="hint">${esc(i.contributor)} · ${esc(i.created.slice(0,10))} · ref ${esc(i.id.slice(0,8))}</p><p>${esc(i.citation)}</p><p>${esc(i.note)}</p>${safeURL(i.source_url)?`<p><a href="${safeURL(i.source_url)}" target="_blank" rel="noopener">Submitted source</a></p>`:''}${i.has_file?`<p><a href="/api/submission-file?id=${encodeURIComponent(i.id)}">Download submitted PDF</a></p>`:''}${i.review_note?`<div class="notice">${esc(i.review_note)}</div>`:''}${i.linked_case?`<button class="small queueCase" data-id="${esc(i.linked_case)}">Open linked judgment</button>`:''}${admin?` <button class="small reviewItem" data-id="${esc(i.id)}">Review</button>`:''}</article>`).join('')||'<p class="hint">No submissions here yet.</p>';document.querySelectorAll('.queueCase').forEach(b=>b.onclick=()=>openCase(b.dataset.id));document.querySelectorAll('.reviewItem').forEach(b=>b.onclick=()=>reviewItem(items.find(i=>i.id===b.dataset.id)));};if(admin)$('#queueFilter').onchange=draw;draw();
  }catch(e){notice(target,e.message,true);}
}
function reviewItem(i){
  $('#right').innerHTML=`<h2>${esc(i.title)}</h2><p>${esc(i.citation)}</p><p class="hint">Submitted by ${esc(i.contributor)} (${esc(i.owner)}) · ${esc(i.id)}</p>${i.has_file?`<a href="/api/submission-file?id=${encodeURIComponent(i.id)}">Download PDF for verification</a><p class="hint">SHA-256: ${esc(i.sha256)}</p>`:''}<label class="field">Status<select id="reviewStatus">${['submitted','reviewing','needs_info','duplicate','integrated','declined'].map(s=>`<option value="${s}">${s.replaceAll('_',' ')}</option>`).join('')}</select></label><label class="field">Review note (visible to submitter)<textarea id="reviewNote" maxlength="4000">${esc(i.review_note)}</textarea></label><label class="field">Linked LawBase case ID (required for duplicate / integrated)<input id="linkedCase" maxlength="150" value="${esc(i.linked_case)}"></label><button class="go" id="saveReview">Save review</button><p id="reviewResult" role="status"></p>`;
  $('#reviewStatus').value=i.status;action('#saveReview',async()=>{await post('/api/submissions/review',{id:i.id,status:$('#reviewStatus').value,review_note:$('#reviewNote').value,linked_case:$('#linkedCase').value,expected_updated:i.updated});notice($('#reviewResult'),'Saved');await loadQueue(true);$('#saveReview').hidden=true;});
}

const oldBriefsTab=briefsTab;
briefsTab=async function(){await oldBriefsTab();const tools=document.createElement('div');tools.className='bar';tools.innerHTML='<input type="search" id="briefQuery" aria-label="Search briefs" placeholder="Search brief titles and full text"><button class="go" id="briefSearch">Search</button>';$('#left').prepend(tools);action('#briefSearch',async()=>{const d=await api('/api/briefs',{q:$('#briefQuery').value});const slugs=new Set([...d.briefs,...d.templates].map(b=>b.slug));document.querySelectorAll('#left .res').forEach(el=>el.hidden=!slugs.has(el.dataset.slug));});$('#briefQuery').onkeydown=e=>{if(e.key==='Enter')$('#briefSearch').click();};};

const tabs={judgments:judgmentsTab,statutes:statutesTab,briefs:briefsTab,library:libraryTab,contribute:contributeTab,review:()=>loadQueue(true)};
(async()=>{
  try{WHO=await api('/api/whoami');META=await api('/api/meta');try{basket=JSON.parse(localStorageGet('lb-basket:'+WHO.username)||'[]');if(!Array.isArray(basket))basket=[];}catch(e){basket=[];}try{basketTitles=JSON.parse(localStorageGet('lb-basket-titles:'+WHO.username)||'{}')||{};}catch(e){basketTitles={};}saveBasket();
    $('#reviewNav').hidden=!WHO.is_admin;if(WHO.hosted){$('#hostedLinks').style.display='inline';if(WHO.is_admin)$('#adminLink').style.display='inline';$('#signOut').onclick=async e=>{e.preventDefault();await post('/api/logout',{});location.href='/login.html';};}
    const m=META.meta;$('#snap').textContent=`${Number(m.cases).toLocaleString()} judgments · ${Number(m.provisions).toLocaleString()} provisions · ${m.briefs} briefs · latest decision ${m.latest_decision||'unrecorded'}`;$('#intBadge').hidden=!META.internal;$('#attr').textContent='Check the original and later history before relying on extracted text. '+(m.attribution||'');
    document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>setTab(b.dataset.tab));$('#bClear').onclick=()=>{basket=[];saveBasket();};$('#bExport').onclick=()=>basket.length?download({kind:'table',ids:basket}):notice($('#bMsg'),'Add cases first');$('#bBundle').onclick=()=>basket.length?download({kind:'bundle',ids:basket}):notice($('#bMsg'),'Add cases first');
    action('#bCompare',async()=>{if(!basket.length||basket.length>3)throw Error('Keep one to three judgments in the export list to compare.');const d=await api('/api/compare',{ids:basket.join(',')});$('#right').innerHTML='<h2>Compare judgments</h2><p class="hint">Metadata and existing research headnotes. No inferred legal treatment.</p><table><thead><tr><th>Field</th>'+d.cases.map(x=>`<th>${esc(x.case.title)}</th>`).join('')+'</tr></thead><tbody>'+['court','decision_date','citation','judges','disposition','acts'].map(k=>'<tr><th>'+k.replaceAll('_',' ')+'</th>'+d.cases.map(x=>`<td>${esc(x.case[k]||'Unrecorded')}</td>`).join('')+'</tr>').join('')+'<tr><th>Research note</th>'+d.cases.map(x=>`<td>${x.curated.map(h=>esc(h.summary)).join('<hr>')||'None yet'}</td>`).join('')+'</tr></tbody></table>';});
    const params=new URLSearchParams(location.search);searchState=Object.fromEntries([...params].filter(([k])=>!['case','passage'].includes(k)));judgmentsTab();if(params.has('case'))await openCase(params.get('case'),params.has('passage')?Number(params.get('passage')):undefined);
  }catch(e){notice($('#left'),e.message,true);}
})();
