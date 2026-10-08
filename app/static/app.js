
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const snip = s => esc(s).replace(//g, "<mark>").replace(//g, "</mark>");
const api = async (path, params={}) => {
  const r = await fetch(path + "?" + new URLSearchParams(params));
  if(r.status===401){location.href='/login.html';throw Error('Please sign in');}
  const data=await r.json(); if(!r.ok || data.error) throw Error(data.error||'Request failed'); return data;
};
let META = null, basket = [];

function localStorageGet(k){ try { return localStorage.getItem(k); } catch(e){ return null; } }
function localStorageSet(k,v){ try { localStorage.setItem(k,v); } catch(e){} }
function saveBasket(){ localStorageSet("lb-basket:" + WHO.username, JSON.stringify(basket)); $("#bCount").textContent = basket.length; }

async function download(body){
  $("#bMsg").textContent = "preparingâ€¦";
  const r = await fetch("/api/export", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
  if (!r.ok){ $("#bMsg").textContent = "export failed: " + (await r.text()); return; }
  const name = (r.headers.get("Content-Disposition")||"").match(/filename="([^"]+)"/)?.[1] || "LawBase.docx";
  const url = URL.createObjectURL(await r.blob());
  const a = Object.assign(document.createElement("a"), {href:url, download:name}); a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000); $("#bMsg").textContent = "saved " + name;
}

function md(text){  // small markdown renderer for briefs and headnotes
  const lines = esc(text).split(/\n/); let out = [], i = 0;
  const inl = s => s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>').replace(/\*\*([^*]+)\*\*/g,"<strong>$1</strong>").replace(/\*([^*]+)\*/g,"<em>$1</em>").replace(/`([^`]+)`/g,"<code>$1</code>");
  while (i < lines.length){
    const l = lines[i];
    if (/^\|/.test(l)){ const rows=[]; while(i<lines.length && /^\|/.test(lines[i])) rows.push(lines[i++].replace(/^\||\|$/g,"").split("|").map(c=>c.trim()));
      out.push("<table>" + rows.filter(r=>!r.every(c=>/^:?-{3,}:?$/.test(c))).map((r,j)=>"<tr>"+r.map(c=>j?`<td>${inl(c)}</td>`:`<th>${inl(c)}</th>`).join("")+"</tr>").join("") + "</table>"); continue; }
    let m;
    if ((m = l.match(/^(#{1,3})\s+(.*)/))) out.push(`<h${m[1].length+1}>${inl(m[2])}</h${m[1].length+1}>`);
    else if (/^\s*[-*]\s+/.test(l)) out.push(`<li>${inl(l.replace(/^\s*[-*]\s+/,""))}</li>`);
    else if (l.trim() && l.trim() !== "---") out.push(`<p>${inl(l)}</p>`);
    i++;
  }
  return out.join("");
}

// ---------------------------------------------------------------- statutes
function statutesTab(){
  $("#left").innerHTML = `
    <div class="bar"><select id="sact"><option value="">All Acts</option>${META.acts.map(a=>`<option value="${a.act_id}">${esc(a.act_short)}</option>`).join("")}</select>
      <input type="search" id="sq" placeholder="e.g. burden of proof"><button class="go" id="sgo">Search</button></div>
    <p class="hint">Section labels come from the source and can be off by one; the full text is authoritative.</p>
    <div id="sres"></div>`;
  const run = async () => {
    const d = await api("/api/statutes", {q:$("#sq").value, act:$("#sact").value});
    $("#sres").innerHTML = d.results.map(r => `<div class="res" data-id="${r.rowid}"><div class="t">${esc(r.act_short)} â€” s.${esc(r.section_number)} ${esc(r.section_title||"")}</div><div class="snip">${snip(r.snip)}</div></div>`).join("") || "<p class='hint'>No match.</p>";
    document.querySelectorAll("#sres .res").forEach(el => el.onclick = async () => {
      const p = await api("/api/provision", {id: el.dataset.id});
      $("#right").innerHTML = `<h2>${esc(p.act_title)}</h2><div class="hint">${esc(p.chapter||"")} Â· labelled s.${esc(p.section_number)} Â· <a href="${esc(p.source_url)}" target="_blank" rel="noopener">India Code</a></div><div class="txt"><p>${esc(p.text)}</p></div>`;
    });
  };
  $("#sgo").onclick = run; $("#sq").onkeydown = e => { if (e.key === "Enter") run(); }; $("#sact").onchange = run;
}

// ---------------------------------------------------------------- briefs
async function briefsTab(){
  const d = await api("/api/briefs");
  const item = b => `<div class="res" data-slug="${b.slug}"><div class="t">${esc(b.title)}</div><div class="m">${esc(b.date||"")} Â· <span class="chip ${b.tier==="internal"?"cur":""}">${esc(b.tier)}</span> ${esc(b.issues||"")}</div></div>`;
  $("#left").innerHTML = `<h3>Research briefs</h3>${d.briefs.map(item).join("") || "<p class='hint'>None yet.</p>"}
    ${META.internal ? `<h3>Court-reply templates (internal)</h3>${d.templates.map(item).join("") || "<p class='hint'>None yet.</p>"}` : ""}`;
  document.querySelectorAll("#left .res").forEach(el => el.onclick = async () => {
    const b = await api("/api/brief", {slug: el.dataset.slug});
    $("#right").innerHTML = `<h2>${esc(b.title)}</h2><div class="bar"><button class="small" id="xBrief">Export (DOCX)</button></div>${md(b.body)}`;
    $("#xBrief").onclick = () => download({kind:"brief", slug: b.slug});
  });
}

