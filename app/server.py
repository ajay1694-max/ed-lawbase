#!/usr/bin/env python3
r"""ED LawBase - search for PMLA / FEMA / FEOA judgments, statutes and briefs.

LOCAL (an officer's own machine): double-click "Start LawBase.cmd", or `python app\server.py`.
  Opens a browser tab, binds 127.0.0.1 only, no login. Nothing leaves the machine.

HOSTED (e.g. Render): the platform sets $PORT, which switches HOSTED on automatically. Then:
  - every page and API call requires a session cookie from POST /api/login (see auth.py).
  - LAWBASE_ADMIN_PASSWORD (required on first boot with zero accounts) creates user "admin".
  - LAWBASE_SECRET (strongly recommended) signs session cookies; without it one is generated
    and saved to data\secret.key, which is lost on a redeploy with no persistent disk.
  - if data\lawbase.sqlite is missing, it is fetched via update.py (needs app\config.json "repo" set).
  See HOSTING.md for the full Render runbook.

Reads data\lawbase.sqlite (public tier) and, when present, internal\*.sqlite (internal pack).
"""
import glob, gzip, http.cookies, json, os, queue, re, socket, sqlite3, sys, threading, time, urllib.parse, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(APP)
sys.path.insert(0, APP)
import auth, export  # noqa: E402

PUBLIC_DB = os.path.join(ROOT, "data", "lawbase.sqlite")
INTERNAL_DBS = sorted(glob.glob(os.path.join(ROOT, "internal", "*.sqlite")))
STATIC = os.path.join(APP, "static")
HOSTED = bool(os.environ.get("PORT"))  # the one switch: local desktop use never sets this
COOKIE_NAME = "lawbase_session"
_METADATA_INDEX = None
_METADATA_TOKEN_INDEX = None
_GENERIC_METADATA_WORDS = frozenset({
    "anr", "another", "appln", "application", "bail", "court", "directorate",
    "enforcement", "high", "india", "ors", "state", "union", "versus", "vs",
})


_POOL = queue.LifoQueue()   # reused read-only connections: SQLite's page cache survives between requests
_HAS_CHUNK_CASE = None      # True when the compact rowid -> case_id map (pipeline/optimize_db.py) exists


def connect():
    try:
        return _POOL.get_nowait()
    except queue.Empty:
        pass
    c = sqlite3.connect(f"file:{PUBLIC_DB}?mode=ro", uri=True, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA cache_size = -16384")      # 16 MB of page cache per connection
    c.execute("PRAGMA mmap_size = 268435456")    # read through the OS page cache instead of copying
    c.execute("PRAGMA temp_store = MEMORY")
    if INTERNAL_DBS:
        c.execute("ATTACH DATABASE ? AS internal", (f"file:{INTERNAL_DBS[0]}?mode=ro",))
    return c


def release(c):
    """Return a connection to the pool (at most 4 kept); close the rest."""
    try:
        c.rollback()
    except sqlite3.Error:
        c.close()
        return
    if _POOL.qsize() < 4:
        _POOL.put(c)
    else:
        c.close()


def chunk_map(c):
    """Table that maps an FTS rowid to its case: the compact map if present, else the chunks table itself."""
    global _HAS_CHUNK_CASE
    if _HAS_CHUNK_CASE is None:
        _HAS_CHUNK_CASE = c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunk_case'").fetchone() is not None
    return "chunk_case" if _HAS_CHUNK_CASE else "chunks"


def schemas():
    return ["main"] + (["internal"] if INTERNAL_DBS else [])


def fts_query(q):
    """Plain words -> each word required. Quotes, *, AND/OR/NOT/NEAR pass through as FTS5 syntax."""
    if re.search(r'["*]|\b(AND|OR|NOT|NEAR)\b', q):
        return q
    return " ".join('"' + t + '"' for t in re.findall(r"[^\s\"]+", q))


def _search_normalize(value):
    """Comparable form for case titles, case numbers and citations."""
    return " ".join(re.findall(r"[a-z0-9]+", (value or "").lower()))


def _metadata_query(query):
    """Return the normalized query only when metadata promotion is useful.

    Generic one-word searches such as ``bail`` and ``enforcement`` are requests
    for judgment text, not case titles.  A citation/case number (digits present)
    or a multi-word name with at least one distinctive word is a locator query.
    """
    needle = _search_normalize(query)
    words = tuple(needle.split())
    if not words:
        return None
    if any(ch.isdigit() for ch in needle):
        return needle, words
    if len(words) >= 2 and any(word not in _GENERIC_METADATA_WORDS for word in words):
        return needle, words
    return None


def _metadata_index(c):
    """Cache normalized public-case metadata once per process."""
    global _METADATA_INDEX, _METADATA_TOKEN_INDEX
    if _METADATA_INDEX is None:
        rows = c.execute("""SELECT c.case_id, c.title, c.citation, c.case_number,
                            coalesce(e.citation_extra, '') AS citation_extra
                            FROM cases c LEFT JOIN enrich_cases e USING (case_id)""")
        index, token_index = {}, {}
        for row in rows:
            title = _search_normalize(row["title"])
            citation = _search_normalize(" ".join((row["citation"] or "", row["citation_extra"] or "")))
            case_number = _search_normalize(row["case_number"])
            combined_words = frozenset(" ".join((title, citation, case_number)).split())
            entry = (row["case_id"], title, citation, case_number,
                     combined_words, frozenset(title.split()))
            index[row["case_id"]] = entry
            for word in combined_words:
                token_index.setdefault(word, set()).add(row["case_id"])
        _METADATA_TOKEN_INDEX = {word: frozenset(ids) for word, ids in token_index.items()}
        _METADATA_INDEX = index  # assign the sentinel last so concurrent first requests see both caches
    return _METADATA_INDEX


def _metadata_candidates(c, words):
    """Use the cached token index to avoid scanning every case per query."""
    index = _metadata_index(c)
    pools = [_METADATA_TOKEN_INDEX.get(word, frozenset()) for word in words]
    if not pools or any(not pool for pool in pools):
        return index, ()
    candidates = set(min(pools, key=len))
    for pool in pools:
        candidates.intersection_update(pool)
        if not candidates:
            break
    return index, sorted(candidates)


def _metadata_priority_cached(entry, needle, words):
    """Return the direct-match priority for one pre-normalized metadata entry."""
    _, title, citation, case_number, combined_words, title_words = entry
    if not all(word in combined_words for word in words):
        return None
    if any(ch.isdigit() for ch in needle):
        return (
            int(citation == needle), int(case_number == needle),
            int(needle in citation), int(needle in case_number),
            int(title == needle), int(title.startswith(needle)), int(needle in title),
            int(all(word in title_words for word in words)),
        )
    return (
        int(title == needle), int(title.startswith(needle)), int(needle in title),
        int(case_number == needle), int(needle in case_number),
        int(citation == needle), int(needle in citation),
        int(all(word in title_words for word in words)),
    )


def _metadata_priority(row, query):
    """Rank direct metadata matches ahead of judgments that merely cite the query.

    Full-text relevance remains the stable fallback order.  A tuple is returned so
    Python's stable sort can promote exact/prefix/phrase matches without disturbing
    the existing FTS order among otherwise equal cases.
    """
    parsed = _metadata_query(query)
    if parsed is None:
        return None
    needle, words = parsed
    title = _search_normalize(row["title"])
    citation = _search_normalize(row["citation"])
    case_number = _search_normalize(row["case_number"])
    entry = (row["case_id"] if "case_id" in row.keys() else "", title, citation, case_number,
             frozenset(" ".join((title, citation, case_number)).split()), frozenset(title.split()))
    return _metadata_priority_cached(entry, needle, words)


def attribution(c):
    r = c.execute("SELECT value FROM meta WHERE key='attribution'").fetchone()
    return r[0] if r else ""


def curated(c, cid):
    out = []
    for s in schemas():
        r = c.execute(f"SELECT * FROM {s}.enrich_cases WHERE case_id=?", (cid,)).fetchone()
        if r:
            out.append(dict(r))
    return out


def issue_labels(c, cid):
    return [dict(r) for r in c.execute("""SELECT ci.issue, i.label, ci.source, ci.hits FROM case_issues ci
        LEFT JOIN issues i USING (issue) WHERE ci.case_id=? ORDER BY ci.source='curated' DESC, ci.hits DESC""", (cid,))]


# ------------------------------------------------------------------ API
def api_meta(c, p):
    meta = {r[0]: r[1] for r in c.execute("SELECT key, value FROM meta")}
    courts = [dict(r) for r in c.execute("SELECT court_slug, any_value(court) AS court, count(*) AS n FROM cases GROUP BY court_slug ORDER BY n DESC")] \
        if False else [dict(r) for r in c.execute("SELECT court_slug, max(court) AS court, count(*) AS n FROM cases GROUP BY court_slug ORDER BY n DESC")]
    issues = [dict(r) for r in c.execute("""SELECT i.issue, i.label, i.act, count(ci.case_id) AS n FROM issues i
        LEFT JOIN case_issues ci USING (issue) GROUP BY i.issue ORDER BY i.issue""")]
    acts = [dict(r) for r in c.execute("SELECT act_id, act_short, count(*) AS n FROM statutes GROUP BY act_id ORDER BY act_short")]
    return {"meta": meta, "courts": courts, "issues": issues, "acts": acts, "internal": bool(INTERNAL_DBS)}


def api_search(c, p):
    q = (p.get("q") or "").strip()
    limit = min(int(p.get("limit") or 50), 300)
    filt, args = [], []
    if p.get("court"):
        filt.append("c.court_slug = ?"); args.append(p["court"])
    if p.get("year_from"):
        filt.append("c.year >= ?"); args.append(int(p["year_from"]))
    if p.get("year_to"):
        filt.append("c.year <= ?"); args.append(int(p["year_to"]))
    if p.get("act"):
        filt.append("(',' || c.acts || ',') LIKE ?"); args.append(f"%,{p['act']},%")
    if p.get("issue"):
        filt.append("c.case_id IN (SELECT case_id FROM case_issues WHERE issue = ?)"); args.append(p["issue"])
    extra = "".join(" AND " + f for f in filt)
    cmap = chunk_map(c)
    best, order, best_rids = {}, [], {}
    if q:
        # Default: every word/phrase must appear somewhere in the JUDGMENT (not necessarily one passage).
        # within=chunk, or explicit FTS operators, keeps the stricter same-passage matching.
        terms = re.findall(r'"[^"]+"|[^\s"]+', q)
        phrase = lambda t: t if t.startswith('"') else '"' + t + '"'
        raw = bool(re.search(r'\*|\b(AND|OR|NOT|NEAR)\b', q))
        case_level = p.get("within", "case") == "case" and len(terms) > 1 and not raw
        restrict, common = "", None
        if case_level:
            for t in terms:
                ids = {r[0] for r in c.execute(f"""SELECT DISTINCT k.case_id FROM chunks_fts
                        JOIN {cmap} k ON k.rowid = chunks_fts.rowid JOIN cases c ON c.case_id = k.case_id
                        WHERE chunks_fts MATCH ?{extra}""", [phrase(t)] + args)}
                common = ids if common is None else common & ids
                if not common:
                    break
            c.execute("CREATE TEMP TABLE IF NOT EXISTS hitset (case_id TEXT PRIMARY KEY)")
            c.execute("DELETE FROM temp.hitset")
            c.executemany("INSERT INTO temp.hitset VALUES (?)", [(x,) for x in (common or ())])
            restrict = " AND k.case_id IN (SELECT case_id FROM temp.hitset)"
            match = " OR ".join(phrase(t) for t in terms)
        else:
            match = fts_query(q)
        # Phase 1 ranks passages from the FTS index and the compact map only - no passage text is read.
        sql = f"""SELECT chunks_fts.rowid AS rid, k.case_id, bm25(chunks_fts) AS score
                  FROM chunks_fts JOIN {cmap} k ON k.rowid = chunks_fts.rowid JOIN cases c ON c.case_id = k.case_id
                  WHERE chunks_fts MATCH ?{extra}{restrict} ORDER BY score LIMIT 3000"""
        try:
            rows = c.execute(sql, [match] + args).fetchall()
        except sqlite3.OperationalError:
            match = '"' + q.replace('"', "") + '"'
            rows = c.execute(sql, [match] + args).fetchall()
        snip_rids = {}
        for r in rows:
            b = best.get(r["case_id"])
            if b is None:
                best[r["case_id"]] = b = {"hits": 0, "snips": []}
                order.append(r["case_id"])
            b["hits"] += 1
            snip_rids.setdefault(r["case_id"], [])
            if len(snip_rids[r["case_id"]]) < 2:
                snip_rids[r["case_id"]].append(r["rid"])
        best_rids = snip_rids  # snippets are built later, only for the cases actually returned
        for x in sorted(common or ()):  # matching cases whose passages fell outside the snippet window
            if x not in best:
                best[x] = {"hits": 0, "snips": []}
                order.append(x)

        # A person's/case's name or a citation is often used to locate the case
        # itself.  FTS alone can rank a later judgment quoting that case above the
        # source judgment, so merge direct metadata matches and promote them.
        parsed_metadata = None if raw else _metadata_query(q)
        if parsed_metadata is not None:
            needle, words = parsed_metadata
            priorities = {}
            known = set(order)
            eligible = None
            if filt:
                eligible = {r[0] for r in c.execute(f"SELECT c.case_id FROM cases c WHERE 1=1{extra}", args)}
            index, candidates = _metadata_candidates(c, words)
            for cid in candidates:
                if eligible is not None and cid not in eligible:
                    continue
                meta = index[cid]
                priority = _metadata_priority_cached(meta, needle, words)
                if priority is None:
                    continue
                priorities[cid] = priority
                if cid not in known:
                    best[cid] = {"hits": 0, "snips": []}
                    order.append(cid)
                    known.add(cid)
            zero = (0,) * 8
            order.sort(key=lambda cid: priorities.get(cid, zero), reverse=True)
    elif filt:
        for r in c.execute(f"SELECT c.case_id FROM cases c WHERE 1=1{extra} ORDER BY c.decision_date DESC LIMIT 2000", args):
            best[r[0]] = {"hits": 0, "snips": []}
            order.append(r[0])
    page = order[:limit]
    if q and best_rids:
        # Phase 2: snippets for at most two passages of each returned case (<= 2 x limit rows of text).
        want = [rid for cid in page for rid in best_rids.get(cid, ())]
        snips = {}
        for rid in want:
            r = c.execute("""SELECT snippet(chunks_fts, 0, char(1), char(2), ' … ', 30) FROM chunks_fts
                             WHERE chunks_fts MATCH ? AND rowid = ?""", (match, rid)).fetchone()
            if r:
                snips[rid] = r[0]
        for cid in page:
            best[cid]["snips"] = [snips[rid] for rid in best_rids.get(cid, ()) if rid in snips]
    out = []
    for cid in page:
        m = dict(c.execute("SELECT * FROM cases WHERE case_id=?", (cid,)).fetchone())
        out.append({**m, **best[cid], "issues": issue_labels(c, cid)[:6], "curated": curated(c, cid)})
    return {"results": out, "total": len(order)}


def api_case(c, p):
    cid = p["id"]
    m = c.execute("SELECT * FROM cases WHERE case_id=?", (cid,)).fetchone()
    if not m:
        return {"error": "not found"}
    chunks = [dict(r) for r in c.execute("SELECT chunk_index, section_type, text FROM chunks WHERE case_id=? ORDER BY chunk_index", (cid,))]
    return {"case": dict(m), "issues": issue_labels(c, cid), "curated": curated(c, cid), "chunks": chunks}


def api_statutes(c, p):
    q, act = (p.get("q") or "").strip(), p.get("act")
    if q:
        sql = """SELECT s.rowid, s.act_short, s.section_number, s.section_title,
                 snippet(statutes_fts, 0, char(1), char(2), ' … ', 30) AS snip
                 FROM statutes_fts JOIN statutes s ON s.rowid = statutes_fts.rowid WHERE statutes_fts MATCH ?"""
        args = [fts_query(q)]
        if act:
            sql += " AND s.act_id = ?"; args.append(act)
        try:
            rows = c.execute(sql + " ORDER BY bm25(statutes_fts) LIMIT 100", args).fetchall()
        except sqlite3.OperationalError:
            args[0] = '"' + q.replace('"', "") + '"'
            rows = c.execute(sql + " ORDER BY bm25(statutes_fts) LIMIT 100", args).fetchall()
    elif act:
        rows = c.execute("SELECT rowid, act_short, section_number, section_title, substr(text, 1, 220) AS snip FROM statutes WHERE act_id=? ORDER BY rowid", (act,)).fetchall()
    else:
        rows = []
    return {"results": [dict(r) for r in rows]}


def api_provision(c, p):
    r = c.execute("SELECT * FROM statutes WHERE rowid=?", (int(p["id"]),)).fetchone()
    return dict(r) if r else {"error": "not found"}


def api_briefs(c, p):
    out = []
    for s in schemas():
        out += [dict(r) for r in c.execute(f"SELECT slug, title, tier, issues, date, author FROM {s}.briefs ORDER BY date DESC, slug")]
    templates = []
    if INTERNAL_DBS:
        templates = [dict(r) for r in c.execute("SELECT slug, title, tier, issues FROM internal.templates ORDER BY title")]
    return {"briefs": out, "templates": templates}


def api_brief(c, p):
    for s in schemas():
        for table in ("briefs", "templates"):
            if table == "templates" and s == "main":
                continue
            r = c.execute(f"SELECT * FROM {s}.{table} WHERE slug=?", (p["slug"],)).fetchone()
            if r:
                return dict(r)
    return {"error": "not found"}


def do_export(c, body):
    kind = body.get("kind")
    attr = attribution(c)
    if kind == "table":
        rows = []
        for cid in body.get("ids", []):
            m = c.execute("SELECT * FROM cases WHERE case_id=?", (cid,)).fetchone()
            if not m:
                continue
            cur = curated(c, cid)
            note = " | ".join(x.get("summary") or "" for x in cur if x.get("summary"))
            rows.append({**dict(m), "issues": [i["label"] or i["issue"] for i in issue_labels(c, cid)[:4]], "note": note})
        return export.citation_table(rows, attr), "LawBase-citation-table"
    if kind == "case":
        d = api_case(c, {"id": body["id"]})
        data = export.judgment(d["case"], [i["label"] or i["issue"] for i in d["issues"]], d["curated"],
                               [ch["text"] for ch in d["chunks"]], attr)
        return data, re.sub(r"[^\w]+", "-", d["case"]["title"])[:80]
    if kind == "brief":
        b = api_brief(c, {"slug": body["slug"]})
        return export.brief(b, b["body"], attr), b["slug"]
    raise ValueError("unknown export kind")


# admin-only management API (HOSTED only; see api_users_* below)
def api_users_list(c, p, session):
    return {"users": auth.list_users(ROOT)}


ROUTES = {"/api/meta": api_meta, "/api/search": api_search, "/api/case": api_case, "/api/statutes": api_statutes,
          "/api/provision": api_provision, "/api/briefs": api_briefs, "/api/brief": api_brief}
ADMIN_ROUTES = {"/api/users": api_users_list}
PUBLIC_PATHS = {"/login.html", "/api/login",  # reachable with no session, only when HOSTED
                "/manifest.webmanifest", "/sw.js", "/offline.html", "/icon-192.png", "/icon-512.png",
                "/icon-maskable-512.png", "/apple-touch-icon.png", "/favicon.png", "/favicon.ico"}  # installable-app files
TYPES = {".html": "text/html; charset=utf-8", ".js": "application/javascript", ".css": "text/css",
         ".webmanifest": "application/manifest+json", ".png": "image/png", ".json": "application/json"}

# Response cache for read-only API calls. The data only changes when lawbase.sqlite is replaced or patched,
# so entries are keyed to the file's modification time and dropped wholesale when it changes.
_CACHE, _CACHE_LOCK, _CACHE_BUDGET = {}, threading.Lock(), 48 * 1024 * 1024
_CACHE_STATE = {"stamp": None, "bytes": 0}
GZIP_TYPES = ("application/json", "text/", "application/javascript")


def _db_stamp():
    try:
        return os.stat(PUBLIC_DB).st_mtime_ns
    except OSError:
        return None


def cache_get(key):
    with _CACHE_LOCK:
        stamp = _db_stamp()
        if stamp != _CACHE_STATE["stamp"]:
            _CACHE.clear(); _CACHE_STATE.update(stamp=stamp, bytes=0)
            return None
        hit = _CACHE.pop(key, None)
        if hit is not None:
            _CACHE[key] = hit  # move to the end: most recently used
        return hit


def cache_put(key, raw, packed):
    size = len(raw) + len(packed)
    if size > _CACHE_BUDGET // 8:
        return
    with _CACHE_LOCK:
        _CACHE[key] = (raw, packed)
        _CACHE_STATE["bytes"] += size
        while _CACHE_STATE["bytes"] > _CACHE_BUDGET and _CACHE:
            old = _CACHE.pop(next(iter(_CACHE)))
            _CACHE_STATE["bytes"] -= len(old[0]) + len(old[1])


class Handler(BaseHTTPRequestHandler):
    server_version = "ED-LawBase"
    sys_version = ""

    def version_string(self):
        return self.server_version

    def log_message(self, *a):
        pass

    def _accepts_gzip(self):
        return "gzip" in (self.headers.get("Accept-Encoding") or "")

    def _send(self, code, data, ctype, extra=None, packed=None):
        """Send a response; text and JSON over 1 KB go gzip-compressed when the client accepts it."""
        extra = dict(extra or {})
        if self._accepts_gzip() and ctype.startswith(GZIP_TYPES) and len(data) > 1024:
            data = packed if packed is not None else gzip.compress(data, compresslevel=5)
            extra["Content-Encoding"] = "gzip"
            extra["Vary"] = "Accept-Encoding"
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _session(self):
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        jar = http.cookies.SimpleCookie(); jar.load(raw)
        tok = jar.get(COOKIE_NAME)
        return auth.verify_session(ROOT, tok.value) if tok else None

    def _require_session(self, path):
        """Returns a session dict, or None after already sending a 401/redirect."""
        if not HOSTED or path in PUBLIC_PATHS:
            return {"username": None, "is_admin": False}
        session = self._session()
        if session:
            return session
        if path.startswith("/api/"):
            self._send(401, json.dumps({"error": "login required"}).encode(), "application/json")
        else:
            self._send(302, b"", "text/plain", {"Location": "/login.html"})
        return None

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        session = self._require_session(u.path)
        if session is None:
            return
        if u.path == "/api/whoami":
            return self._send(200, json.dumps({"hosted": HOSTED, **session}).encode(), "application/json")
        if u.path in ADMIN_ROUTES:
            if not session["is_admin"]:
                return self._send(403, json.dumps({"error": "admin only"}).encode(), "application/json")
            p = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            try:
                res = ADMIN_ROUTES[u.path](None, p, session)
                return self._send(200, json.dumps(res, default=str).encode(), "application/json")
            except Exception as e:
                return self._send(500, json.dumps({"error": str(e)}).encode(), "application/json")
        if u.path in ROUTES:
            p = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            key = (u.path, tuple(sorted(p.items())))
            hit = cache_get(key)
            if hit is not None:
                return self._send(200, hit[0], "application/json", {"X-Cache": "hit"}, packed=hit[1])
            try:
                c = connect()
                try:
                    res = ROUTES[u.path](c, p)
                finally:
                    release(c)
                raw = json.dumps(res, ensure_ascii=False, default=str).encode("utf-8")
                packed = gzip.compress(raw, compresslevel=5)
                if "error" not in res:
                    cache_put(key, raw, packed)
                self._send(200, raw, "application/json", packed=packed)
            except Exception as e:  # surface the error to the UI rather than a blank page
                self._send(500, json.dumps({"error": str(e)}).encode(), "application/json")
            return
        if u.path == "/admin" or u.path == "/admin.html":
            if not session["is_admin"]:
                return self._send(403, b"admin only", "text/plain")
            u = u._replace(path="/admin.html")
        name = "index.html" if u.path in ("/", "") else os.path.basename(u.path)
        path = os.path.join(STATIC, name)
        if os.path.isfile(path):
            ext = os.path.splitext(name)[1]
            # the service worker and pages must always be re-checked so app updates reach installed phones;
            # icons rarely change
            cache = {"html": "no-cache", ".png": "public, max-age=604800"}.get("html" if ext in (".html", ".js", ".webmanifest") else ext)
            self._send(200, open(path, "rb").read(), TYPES.get(ext, "application/octet-stream"),
                       {"Cache-Control": cache} if cache else None)
        else:
            self._send(404, b"not found", "text/plain")

    def do_HEAD(self):
        """Serve the same status and headers as GET without a response body."""
        return self.do_GET()

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/login":
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            user = auth.verify_login(ROOT, body.get("username", ""), body.get("password", ""))
            if not user:
                return self._send(401, json.dumps({"error": "wrong username or password"}).encode(), "application/json")
            token = auth.make_session(ROOT, user)
            # Secure: hosted mode is only ever reached over HTTPS (Caddy / Render terminate TLS) - Codex X3
            cookie = f"{COOKIE_NAME}={token}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=1209600"
            return self._send(200, json.dumps({"ok": True, "is_admin": user["is_admin"]}).encode(), "application/json",
                              {"Set-Cookie": cookie})
        session = self._require_session(u.path)
        if session is None:
            return
        if u.path == "/api/logout":
            return self._send(200, b"{}", "application/json", {"Set-Cookie": f"{COOKIE_NAME}=; Path=/; Max-Age=0"})
        if u.path in ("/api/users/create", "/api/users/delete", "/api/users/password"):
            if not session["is_admin"]:
                return self._send(403, json.dumps({"error": "admin only"}).encode(), "application/json")
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            try:
                if u.path == "/api/users/create":
                    auth.create_user(ROOT, body["username"], body["password"], body.get("is_admin", False))
                elif u.path == "/api/users/password":
                    auth.set_password(ROOT, body["username"], body["password"])
                elif u.path == "/api/users/delete":
                    if body.get("username", "").strip().lower() == session["username"]:
                        raise ValueError("cannot delete the account you are logged in as")
                    auth.delete_user(ROOT, body["username"])
                return self._send(200, b"{}", "application/json")
            except (ValueError, KeyError) as e:
                return self._send(400, json.dumps({"error": str(e)}).encode(), "application/json")
        if u.path != "/api/export":
            return self._send(404, b"not found", "text/plain")
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        try:
            c = connect()
            try:
                (data, ext), name = do_export(c, body)
            finally:
                release(c)
            ctype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document" if ext == "docx" else "text/markdown"
            self._send(200, data, ctype, {"Content-Disposition": f'attachment; filename="{name}.{ext}"'})
        except Exception as e:
            self._send(500, json.dumps({"error": str(e)}).encode(), "application/json")


def free_port(start=8765):
    for port in range(start, start + 50):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise SystemExit("no free port")


def ensure_data():
    if os.path.exists(PUBLIC_DB):
        return
    if not HOSTED:
        sys.exit(f"Data file missing: {PUBLIC_DB}\nDownload the latest lawbase.sqlite into the data folder.")
    print("data\\lawbase.sqlite missing - fetching from the latest GitHub Release ...", flush=True)
    import update
    update.main()
    if not os.path.exists(PUBLIC_DB):
        sys.exit("Still no data\\lawbase.sqlite after update.py ran. Check app\\config.json's \"repo\" and that "
                 "the repo has a release with a lawbase-data-*.zip asset.")


def ensure_admin():
    if auth.count_users(ROOT) > 0:
        return
    pw = os.environ.get("LAWBASE_ADMIN_PASSWORD")
    if not pw:
        sys.exit("No accounts exist yet and LAWBASE_ADMIN_PASSWORD is not set.\n"
                 "Set it (Render: Environment tab) and redeploy - this creates user \"admin\" on first boot.")
    auth.create_user(ROOT, "admin", pw, is_admin=True)
    print("Created initial admin account \"admin\" from LAWBASE_ADMIN_PASSWORD.", flush=True)
    if not os.environ.get("LAWBASE_SECRET"):
        print("WARNING: LAWBASE_SECRET is not set. A key was generated and saved to data\\secret.key - "
              "on a host with no persistent disk, every account and login session is lost on redeploy. "
              "Set LAWBASE_SECRET explicitly (any long random string) to avoid that. See HOSTING.md.", flush=True)


def main():
    ensure_data()
    if HOSTED:
        ensure_admin()
        port = int(os.environ["PORT"])
        host = "0.0.0.0"
        print(f"ED LawBase (hosted) listening on {host}:{port}", flush=True)
    else:
        port = free_port()
        host = "127.0.0.1"
        url = f"http://{host}:{port}/"
        print(f"ED LawBase running at {url}  (internal pack: {'yes' if INTERNAL_DBS else 'no'})\nClose this window to stop.", flush=True)
        if "--no-browser" not in sys.argv:
            webbrowser.open(url)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
