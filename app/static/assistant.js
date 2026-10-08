// Questions stay in this page's memory. No keys, prompts or answers in localStorage.
tabs.assistant = async function () {
  $('#left').innerHTML = `<h2>Ask LawBase</h2>
    <p>Ask a general legal question to find relevant judgments and supporting passages.</p>
    <form id="aiForm"><label for="aiQuestion">Legal question</label>
    <textarea id="aiQuestion" maxlength="1500" minlength="8" required placeholder="Can non-cooperation alone justify an arrest under PMLA?"></textarea>
    <label><input id="aiPublic" type="checkbox" required> This contains only a general legal question, without confidential facts or private identifiers.</label>
    <p class="hint">AI answers send your question and public judgment extracts to OpenAI. Personal research notes and uploaded files are excluded.</p>
    <button class="go" id="aiAsk">Find authorities</button><p id="aiState" role="status"></p></form>
    <p id="aiAllowance" class="hint"></p><h3>Try a question</h3>
    <div id="aiExamples"></div>`;
  $('#right').innerHTML = '<h2>Sources and guidance</h2><p>Relevant cases will appear here with links to their full text. Check the original and later history before relying on an answer.</p>';
  for (const question of ['When must grounds of arrest be supplied in writing?', 'Can NCLT release a PMLA attachment under section 32A?', 'What are the twin conditions for PMLA bail?']) {
    const b = document.createElement('button'); b.className = 'small'; b.textContent = question;
    b.onclick = () => { $('#aiQuestion').value = question; $('#aiQuestion').focus(); };
    $('#aiExamples').append(b, document.createElement('br'));
  }
  const allowance = $('#aiAllowance');
  try { const s = await api('/api/assistant/status'); if(allowance.isConnected) allowance.textContent = `${s.model} · team allowance $${s.monthly_budget_usd}/month · ${s.daily_queries_per_account} questions/account/day · ${s.configured ? 'AI connected' : 'API key awaiting connection'}`; }
  catch(e) { if(allowance.isConnected) allowance.textContent = e.message; }
  const form = $('#aiForm'); if(!form) return;
  form.onsubmit = async e => {
    e.preventDefault(); const button = $('#aiAsk'), state = $('#aiState'), right = $('#right');
    button.disabled = true; state.textContent = 'Searching public judgments…';
    try {
      const d = await post('/api/assistant/ask', {question: $('#aiQuestion').value, public_question: $('#aiPublic').checked});
      if(!form.isConnected) return;
      state.textContent = d.cached ? 'Saved answer reused; no new AI charge.' : 'Research ready';
      right.innerHTML = '<h2>Research guidance</h2>' + (d.message ? `<p class="notice">${esc(d.message)}</p>` : '') +
        d.points.map(p => `<article><p>${esc(p.text)}</p><blockquote>${esc(p.quote)}</blockquote><p class="hint">Sources: ${p.sources.map(esc).join(', ')}</p></article>`).join('') +
        `<p class="hint">${esc(d.limitations)}</p>` + (d.questions.length ? '<h3>Clarify the legal issue</h3>' + d.questions.map(q=>`<p>${esc(q)}</p>`).join('') : '') +
        '<h3>Source judgments</h3>' + d.sources.map(s => `<article class="res"><strong>${esc(s.id)} · ${esc(s.title)}</strong><p class="hint">${esc(s.court)} · ${esc(s.decision_date || 'Date unrecorded')} · ${esc(s.citation || 'Citation unrecorded')}</p>${s.extracts.map(p=>`<details><summary>LawBase passage ${Number(p.passage)+1}</summary><p>${esc(p.text)}</p><button class="small aiSource" data-case="${esc(s.case_id)}" data-passage="${Number(p.passage)}">Open full judgment here</button></details>`).join('')}<p><a href="/?case=${encodeURIComponent(s.case_id)}" target="_blank" rel="noopener">Open full judgment in another tab</a></p></article>`).join('');
      right.querySelectorAll('.aiSource').forEach(b=>b.onclick=()=>openCase(b.dataset.case,Number(b.dataset.passage)));
    } catch(err) { if(state.isConnected) {state.textContent = err.message;state.className='error';} }
    finally {button.disabled=false;}
  };
};
