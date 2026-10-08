// Questions stay in this page's memory. No keys, prompts or answers in localStorage.
const aiClean = t => String(t || '').replace(/\[(SECTION|TITLE)\]\s*#*\s*/g, '');  // extraction markers, as the reader strips them
const AI_EXAMPLES = ['When must grounds of arrest be supplied in writing?', 'Can NCLT release a PMLA attachment under section 32A?', 'What are the twin conditions for PMLA bail?'];

function aiEmpty() {
  return `<div class="ai-empty"><h2>Research guidance</h2>
    <p>Ask a question on the left. LawBase searches the public judgments first, then prepares guidance that quotes them word for word.</p>
    <ol class="ai-steps"><li><b>Research points</b><span>Each point in plain language, with the judgment quotation that supports it.</span></li>
    <li><b>Source judgments</b><span>The cases relied on, with the exact passages and a link to the full text.</span></li>
    <li><b>Check before relying</b><span>Read the original and its later history before citing it.</span></li></ol></div>`;
}

// Which source and passage a verified quotation came from (the server has already matched it word for word).
function aiQuoteOrigin(p, byId) {
  const flat = s => s.replace(/\s+/g, ' ').trim();
  for (const ref of p.sources) {
    const s = byId[ref]; if (!s) continue;
    const hit = s.extracts.find(x => flat(x.text).includes(flat(p.quote)));
    if (hit) return {s, passage: Number(hit.passage)};
  }
  const s = byId[p.sources[0]]; return s ? {s, passage: null} : null;
}

function aiAnswer(d, question) {
  const byId = Object.fromEntries(d.sources.map(s => [s.id, s]));
  const used = new Set();
  const points = d.points.map((p, i) => {
    const o = aiQuoteOrigin(p, byId); if (o && o.passage !== null) used.add(o.s.id + ':' + o.passage);
    const tags = p.sources.map(r => `<a class="srcref" href="#src-${esc(r)}">${esc(r)}</a>`).join('');
    return `<article class="ai-point"><div class="ai-num">${i + 1}</div><div class="ai-body">
      <div class="ai-srcs">Sources ${tags}</div><p>${esc(p.text)}</p>
      <blockquote class="ai-quote"><div class="ai-qhead"><span>Quotation${o ? ' · ' + esc(shortCase(o.s.title)) : ''}</span>
      <span>Supports point ${i + 1}${o ? ' · ' + esc(o.s.id) + (o.passage !== null ? ', LawBase passage ' + (o.passage + 1) : '') : ''}</span></div>
      “${esc(aiClean(p.quote))}”</blockquote></div></article>`;
  }).join('');
  const sources = d.sources.map(s => `<article class="ai-source" id="src-${esc(s.id)}">
      <div class="ai-shead"><span class="ai-sid">${esc(s.id)}</span><div class="ai-stitle"><strong>${esc(s.title)}</strong>
      <span class="hint">${esc(s.court)} · ${esc(s.decision_date || 'Date unrecorded')} · ${esc(s.citation || 'Citation unrecorded')}</span></div>
      <a class="ai-newtab" href="/?case=${encodeURIComponent(s.case_id)}" target="_blank" rel="noopener">Open full judgment in another tab ↗</a></div>
      ${s.research_note ? `<p class="ai-note"><b>Research note</b> ${esc(s.research_note)}</p>` : ''}
      ${s.extracts.map(p => `<details class="ai-extract" ${used.has(s.id + ':' + Number(p.passage)) ? 'open' : ''}><summary>LawBase passage ${Number(p.passage) + 1}${used.has(s.id + ':' + Number(p.passage)) ? ' <span class="ai-relied">quoted above</span>' : ''}</summary>
        <p>${esc(aiClean(p.text))}</p><button class="small aiSource" data-case="${esc(s.case_id)}" data-passage="${Number(p.passage)}">Open full judgment here</button></details>`).join('')}
    </article>`).join('');
  return `<div class="ai-head"><div><h2>Research guidance</h2>${question ? `<p class="ai-asked"><span>Your question</span>${esc(question)}</p>` : ''}</div>
      ${d.points.length ? '<button class="small" id="aiCopy">Copy summary</button>' : ''}</div>
    ${d.message ? `<p class="notice">${esc(d.message)}</p>` : ''}
    ${d.points.length ? `<h3 class="ai-label">Research points</h3>${points}` : ''}
    <div class="ai-limits"><b>Check before relying</b>${esc(d.limitations)}</div>
    ${d.questions.length ? `<h3 class="ai-label">Clarify the legal issue</h3><div class="ai-followups">${d.questions.map(q => `<button class="ai-follow" data-q="${esc(q)}">${esc(q)}<span>Ask this →</span></button>`).join('')}</div>` : ''}
    ${d.sources.length ? `<h3 class="ai-label">Source judgments <span class="ai-count">${d.sources.length}</span></h3>${sources}` : ''}`;
}

function aiSummary(d, question) {
  const byId = Object.fromEntries(d.sources.map(s => [s.id, s]));
  const cite = r => { const s = byId[r]; return s ? `${r}: ${[s.title, s.citation, s.court, s.decision_date].filter(Boolean).join(' · ')}` : r; };
  return ['ED LawBase research guidance', question ? 'Question: ' + question : '', '',
    ...d.points.map((p, i) => `${i + 1}. ${p.text}\n   "${p.quote}"\n   Sources: ${p.sources.join(', ')}`), '',
    'Sources', ...[...new Set(d.points.flatMap(p => p.sources))].map(cite), '', d.limitations].filter((x, i, a) => x || a[i - 1]).join('\n');
}

tabs.assistant = async function () {
  $('#left').innerHTML = `<h2>Ask LawBase <span class="ai-badge">AI research</span></h2>
    <p class="ai-lead">Ask a general legal question to find relevant judgments and supporting passages.</p>
    <form id="aiForm"><label for="aiQuestion" class="ai-flabel">Legal question</label>
    <div class="ai-box"><textarea id="aiQuestion" maxlength="1500" minlength="8" required placeholder="Can non-cooperation alone justify an arrest under PMLA?"></textarea><span id="aiChars" class="ai-chars">0 / 1500</span></div>
    <label class="ai-check"><input id="aiPublic" type="checkbox" required> This contains only a general legal question, without confidential facts or private identifiers.</label>
    <p class="ai-privacy">AI answers send your question and public judgment extracts to OpenAI. Personal research notes and uploaded files are excluded.</p>
    <button class="go ai-ask" id="aiAsk">Find authorities</button><p id="aiState" class="ai-state" role="status"></p></form>
    <p id="aiAllowance" class="hint ai-allow"></p>
    <h3 class="ai-label">Try a question</h3><div id="aiExamples" class="ai-examples"></div>`;
  $('#right').innerHTML = aiEmpty();
  AI_EXAMPLES.forEach((question, i) => {
    const b = document.createElement('button'); b.type = 'button'; b.className = 'ai-example';
    b.innerHTML = `<span>${i + 1}</span>${esc(question)}`;
    b.onclick = () => { $('#aiQuestion').value = question; $('#aiQuestion').dispatchEvent(new Event('input')); $('#aiQuestion').focus(); };
    $('#aiExamples').append(b);
  });
  $('#aiQuestion').oninput = () => { $('#aiChars').textContent = `${$('#aiQuestion').value.length} / 1500`; };
  const allowance = $('#aiAllowance');
  try { const s = await api('/api/assistant/status'); if(allowance.isConnected) allowance.textContent = `${s.model} · team allowance $${s.monthly_budget_usd}/month · ${s.daily_queries_per_account} questions/account/day · ${s.configured ? 'AI connected' : 'API key awaiting connection'}`; }
  catch(e) { if(allowance.isConnected) allowance.textContent = e.message; }
  const form = $('#aiForm'); if(!form) return;
  form.onsubmit = async e => {
    e.preventDefault(); const button = $('#aiAsk'), state = $('#aiState'), right = $('#right'), question = $('#aiQuestion').value;
    button.disabled = true; state.className = 'ai-state busy'; state.textContent = 'Searching public judgments…';
    try {
      const d = await post('/api/assistant/ask', {question, public_question: $('#aiPublic').checked});
      if(!form.isConnected) return;
      state.className = 'ai-state done'; state.textContent = d.cached ? 'Saved answer reused; no new AI charge.' : 'Research ready';
      right.innerHTML = aiAnswer(d, question); right.scrollTop = 0;
      right.querySelectorAll('.aiSource').forEach(b=>b.onclick=()=>openCase(b.dataset.case,Number(b.dataset.passage)));
      right.querySelectorAll('.srcref').forEach(a=>a.onclick=ev=>{ev.preventDefault();const el=$('#src-'+a.textContent);if(el){el.scrollIntoView({behavior:'smooth',block:'start'});el.classList.add('flash');setTimeout(()=>el.classList.remove('flash'),1200);}});
      right.querySelectorAll('.ai-follow').forEach(b=>b.onclick=()=>{$('#aiQuestion').value=b.dataset.q;$('#aiQuestion').dispatchEvent(new Event('input'));$('#aiQuestion').focus();});
      if ($('#aiCopy')) $('#aiCopy').onclick = () => copyText(aiSummary(d, question));
    } catch(err) { if(state.isConnected) {state.textContent = err.message;state.className='ai-state error';} }
    finally {button.disabled=false;}
  };
};
