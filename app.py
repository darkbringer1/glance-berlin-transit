#!/usr/bin/env python3
"""Berlin U-Bahn and S-Bahn status as a Glance extension widget. Python stdlib only."""
import datetime as dt
import html
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

API = os.environ.get("BVG_API", "https://v6.bvg.transport.rest").rstrip("/")
PORT = int(os.environ.get("PORT", "8080"))
CACHE_SECONDS = int(os.environ.get("CACHE_SECONDS", "300"))
RETRY_SECONDS = int(os.environ.get("RETRY_SECONDS", "120"))
TZ = ZoneInfo("Europe/Berlin")
# Hubs that together cover every U-Bahn and S-Bahn line.
HUBS = os.environ.get("BVG_HUBS", "900100003,900100001,900078101,900023201,900056102,"
                                  "900120003,900058101,900079221,900007102").split(",")
LINES = {"U1": "#7DAD4C", "U2": "#DA421E", "U3": "#16683D", "U4": "#F0D722", "U5": "#7E5330",
         "U6": "#8C6DAB", "U7": "#528DBA", "U8": "#224F86", "U9": "#F3791D",
         "S1": "#DE4DA4", "S2": "#005F27", "S25": "#005F27", "S26": "#005F27", "S3": "#0A4C99",
         "S41": "#AD5937", "S42": "#CB6418", "S45": "#CD9C53", "S46": "#CD9C53", "S47": "#CD9C53",
         "S5": "#EB7405", "S7": "#816DA6", "S75": "#816DA6", "S8": "#66AA22", "S85": "#66AA22",
         "S9": "#992746"}
DARK_TEXT = {"U4"}
RANK = {"bad": 0, "warn": 1, "info": 2}

TEXT = {
    "en": {"title": "Berlin U-Bahn · S-Bahn", "ok": "No disruptions in sampled departures", "bad": "{n} lines disrupted",
           "warn": "{n} lines delayed", "until": "until {t}", "stale": "data from {t}", "nodata": "No BVG data right now.",
           "delay": "~{n} min delay", "cancelled": "{n} cancelled", "unknown": "Lines without departure data: {n}", "partial": "{n}/{total} stations reached"},
    "de": {"title": "Berlin U-Bahn · S-Bahn", "ok": "Keine Störungen in erfassten Abfahrten", "bad": "{n} Linien gestört",
           "warn": "{n} Linien verspätet", "until": "bis {t}", "stale": "Stand {t}", "nodata": "Derzeit keine BVG-Daten.",
           "delay": "~{n} Min. Verspätung", "cancelled": "{n} Ausfälle", "unknown": "Linien ohne Abfahrtsdaten: {n}", "partial": "{n}/{total} Stationen erreicht"},
    "tr": {"title": "Berlin U-Bahn · S-Bahn", "ok": "Taranan seferlerde aksama yok", "bad": "{n} hatta arıza",
           "warn": "{n} hatta aksama", "until": "{t} saatine kadar", "stale": "{t} verisi", "nodata": "BVG verisi şu an yok.",
           "delay": "~{n} dk gecikme", "cancelled": "{n} iptal", "unknown": "{n} hatta sefer verisi yok", "partial": "{n}/{total} durağa erişildi"},
}

_lock = threading.Lock()
_cache = {"data": None, "at": 0.0, "failed_at": 0.0}


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "glance-berlin-transit/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def remark_active(remark, now):
    try:
        start = dt.datetime.fromisoformat(remark["validFrom"]) if remark.get("validFrom") else None
        end = dt.datetime.fromisoformat(remark["validUntil"]) if remark.get("validUntil") else None
    except ValueError:
        return True
    return (start is None or start <= now) and (end is None or now <= end)


def severity(text):
    low = text.lower()
    if any(k in low for k in ("störung", "ausfall", "fällt", "unterbrochen", "kein zugverkehr", "sperrung", "notarzt", "polizei")):
        return "bad"
    if any(k in low for k in ("bau", "ersatzverkehr", "sev", "umleitung", "verspätung")):
        return "warn"
    return "info"


def build():
    """Departures with remarks at every hub, reduced to a state per line and a list of issues."""
    now = dt.datetime.now(TZ)
    seen, delays, cancels, ok_hubs, observed = {}, {}, {}, 0, set()
    query = urllib.parse.urlencode({"duration": 30, "results": 80, "remarks": "true", "bus": "false",
                                    "tram": "false", "regional": "false", "express": "false", "ferry": "false"})
    for hub in HUBS:
        try:
            deps = fetch_json(f"{API}/stops/{hub.strip()}/departures?{query}")
        except Exception:
            continue
        ok_hubs += 1
        for dep in deps.get("departures", []) if isinstance(deps, dict) else deps:
            line = (dep.get("line") or {}).get("name", "")
            if line not in LINES:
                continue
            observed.add(line)
            if dep.get("cancelled"):
                cancels[line] = cancels.get(line, 0) + 1
            elif dep.get("delay") is not None:
                delays.setdefault(line, []).append(dep["delay"] / 60)
            for r in dep.get("remarks") or []:
                if r.get("type") != "warning" or not remark_active(r, now):
                    continue
                text = " ".join((r.get("text") or "").split())
                summary = (r.get("summary") or "").strip(" .")
                until = ""
                if r.get("validUntil"):
                    until = dt.datetime.fromisoformat(r["validUntil"]).astimezone(TZ).strftime("%-d.%-m. %H:%M")
                seen[(line, r.get("id") or (summary, text))] = {
                    "line": line, "summary": summary, "text": text, "until": until,
                    "sev": severity(summary + " " + text)}
    if ok_hubs == 0:
        raise RuntimeError("BVG API not reachable")
    lines = {}
    for line in LINES:
        mine = [r for (l, _), r in seen.items() if l == line]
        d = sorted(delays.get(line, []))
        median = d[len(d) // 2] if d else 0
        sev = min((RANK[r["sev"]] for r in mine), default=3)
        if cancels.get(line, 0) >= 2 or sev == 0:
            state = "bad"
        elif median >= 3 or sev == 1:
            state = "warn"
        elif line not in observed:
            state = "none"
        else:
            state = "ok"
        lines[line] = {"state": state, "delay": round(median) if median >= 2 else 0, "cancelled": cancels.get(line, 0)}
    return {"lines": lines, "issues": list(seen.values()), "hubs_ok": ok_hubs, "hubs_total": len(HUBS)}


def data():
    with _lock:
        t = time.time()
        fresh = _cache["data"] is not None and t - _cache["at"] < CACHE_SECONDS
        if not fresh and t - _cache["failed_at"] >= RETRY_SECONDS:
            try:
                _cache.update(data=build(), at=t)
            except Exception:
                _cache["failed_at"] = t
        stale = _cache["failed_at"] > _cache["at"]
        return _cache["data"], stale, _cache["at"]


def render(d, stale, at, lang, wanted):
    t = TEXT.get(lang, TEXT["en"])
    e = html.escape
    if d is None:
        return f'<p class="color-subdue">{e(t["nodata"])}</p>'
    names = [n for n in LINES if not wanted or n in wanted]
    bad = sum(d["lines"][n]["state"] == "bad" for n in names)
    warn = sum(d["lines"][n]["state"] == "warn" for n in names)
    head = ", ".join(x for x in (t["bad"].format(n=bad) if bad else "", t["warn"].format(n=warn) if warn else "") if x) or t["ok"]
    unknown = sum(d["lines"][n]["state"] == "none" for n in names)
    if unknown:
        head += " · " + t["unknown"].format(n=unknown)
    if d.get("hubs_ok", 0) < d.get("hubs_total", 0):
        head += " · " + t["partial"].format(n=d["hubs_ok"], total=d["hubs_total"])
    if stale:
        head += " · " + t["stale"].format(t=dt.datetime.fromtimestamp(at, TZ).strftime("%H:%M"))
    color = "color-negative" if bad else "color-primary" if warn else "color-positive"
    out = [f'<p class="size-h6 {color}">{e(head)}</p>', '<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:8px">']
    for n in names:
        s = d["lines"][n]
        note = [t["delay"].format(n=s["delay"])] if s["delay"] else []
        if s["cancelled"]:
            note.append(t["cancelled"].format(n=s["cancelled"]))
        title = n + (": " + ", ".join(note) if note else "")
        look = {"bad": "outline:2px solid var(--color-negative);outline-offset:1px;",
                "warn": "outline:2px solid var(--color-primary);outline-offset:1px;",
                "none": "opacity:.35;"}.get(s["state"], "")
        out.append(f'<span title="{e(title)}" style="background:{LINES[n]};color:{"#111" if n in DARK_TEXT else "#fff"};'
                   f'font-weight:700;font-size:1.2rem;padding:2px 6px;border-radius:3px;{look}">{e(n)}</span>')
    out.append("</div>")
    groups = {}
    for r in d["issues"]:
        if r["line"] in names:
            groups.setdefault((r["summary"], r["text"]), dict(r, lines=[]))["lines"].append(r["line"])
    issues = sorted(groups.values(), key=lambda r: (RANK[r["sev"]], names.index(r["lines"][0])))[:12]
    if issues:
        out.append('<ul class="list list-gap-8 collapsible-container" data-collapse-after="3" style="margin-top:10px">')
        for r in issues:
            cls = "color-negative" if r["sev"] == "bad" else "color-primary" if r["sev"] == "warn" else "color-subdue"
            until = f' <span class="size-h6 color-subdue">· {e(t["until"].format(t=r["until"]))}</span>' if r["until"] else ""
            out.append(f'<li><p><span class="{cls}">{e(", ".join(sorted(set(r["lines"]), key=names.index)))}</span> '
                       f'<span class="color-highlight">{e(r["summary"])}</span>{until}</p>'
                       f'<p class="size-h6 color-subdue">{e(r["text"])}</p></li>')
        out.append("</ul>")
    out.append('<p class="size-h6 color-subdue" style="margin-top:8px">'
               '<a href="https://www.bvg.de/de/verbindungen/stoerungsmeldungen" target="_blank" rel="noreferrer">BVG</a> · '
               '<a href="https://sbahn.berlin/fahren/bauen-stoerung/" target="_blank" rel="noreferrer">S-Bahn</a></p>')
    return "".join(out)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/health":
            body, status, extra = b"ok", 200, {}
        elif url.path == "/":
            q = urllib.parse.parse_qs(url.query)
            lang = q.get("lang", ["en"])[0]
            wanted = {x.strip().upper() for v in q.get("lines", []) for x in v.split(",") if x.strip()}
            d, stale, at = data()
            body = render(d, stale, at, lang, wanted).encode()
            status = 200
            extra = {"Widget-Title": TEXT.get(lang, TEXT["en"])["title"], "Widget-Content-Type": "html"}
        else:
            body, status, extra = b"not found", 404, {}
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer((os.environ.get("HOST", "0.0.0.0"), PORT), Handler).serve_forever()
