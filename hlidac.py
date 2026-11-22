#!/usr/bin/env python3
"""
Hlídač spuštění registrace do Programu Centra preventivní medicíny (AGEL) – pracoviště Třinec.

Každý běh:
  1. načte stránku https://cpm.npo.agel.cz/moznosti-prihlaseni a vytáhne text záložky „Pracoviště Třinec“,
  2. posbírá všechny odkazy na dotazníky (dotazniky.agel.cz) a zkontroluje jejich stav
     (nenalezen / plně obsazen / byl dostupný do … / bude dostupný … / OTEVŘENO),
  3. porovná vše s minulým během (soubor state.json) a při změně pošle push notifikaci přes ntfy.

Jen standardní knihovna Pythonu, žádné závislosti.
"""
import datetime
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

MAIN_URL = "https://cpm.npo.agel.cz/moznosti-prihlaseni"
EXTRA_PAGES = ["https://cpm.npo.agel.cz/zapojit-se"]
# Dotazníky, které se hlídají vždy (i když na ně web zrovna neodkazuje).
KNOWN_FORMS = [
    "https://dotazniky.agel.cz/dotaznik/npo/cpm",          # původní dotazník programu (dnes „byl dostupný do 31.08.2026“)
    "https://dotazniky.agel.cz/dotaznik/NPO/cpm-trinec",   # odhad adresy pro Třinec (dnes „Dotazník nenalezen“)
]
# Dotazníky, které nás nezajímají (jiné pracoviště).
IGNORED_FORM_PARTS = ["cpm-ostrava"]

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
TZ = ZoneInfo("Europe/Prague")
HEARTBEAT_HOUR = 8            # denní potvrzení „hlídač běží“ po 8:00
ERROR_ALERT_AFTER = 4         # po kolika neúspěšných bězích za sebou poslat varování (~1 h)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

PRIO_URGENT, PRIO_HIGH, PRIO_DEFAULT, PRIO_LOW = 5, 4, 3, 2


# ---------------------------------------------------------------- stahování a text

def fetch(url, tries=3):
    """Vrátí (http_status, html). Při síťové chybě vyhodí výjimku po `tries` pokusech."""
    last = None
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept-Language": "cs,en;q=0.8",
            "Cache-Control": "no-cache",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace") if e.fp else ""
            if e.code < 500:
                return e.code, body
            last = e
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"{url}: {last}")


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in ("p", "br", "div", "li", "h1", "h2", "h3", "tr", "button"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def text_of(html):
    p = _Text()
    p.feed(html)
    return re.sub(r"\s+", " ", "".join(p.parts)).strip()


def dotaznik_links(html, base):
    out = []
    for href in re.findall(r'href\s*=\s*["\']([^"\']+)["\']', html, re.I):
        url = urllib.parse.urljoin(base, href.strip())
        if "dotazniky.agel.cz" in url.lower():
            out.append(url.split("#")[0])
    return out


def trinec_panel(html):
    """HTML obsah záložky Pracoviště Třinec, nebo None, když ji nenajdeme."""
    m = re.search(r'<div[^>]+id\s*=\s*["\'](tab-pane-[^"\']*trinec[^"\']*)["\']', html, re.I)
    if not m:
        return None
    rest = html[m.end():]
    nxt = re.search(r'<div[^>]+id\s*=\s*["\']tab-pane-', rest, re.I)
    end = nxt.start() if nxt else min(len(rest), 6000)
    return rest[:end]


# ---------------------------------------------------------------- vyhodnocení

DATE_RE = re.compile(
    r"\b\d{1,2}\.\s?\d{1,2}\.(\s?20\d\d)?"                       # 8. 12. 2026 / 8.12.
    r"|\b\d{1,2}\.\s?(ledna|února|března|dubna|května|června|července|srpna|září|října|listopadu|prosince)"
    r"|\b\d{1,2}[:.]\d{2}\s?(h|hod)"                                # 10:00 hod
    r"|\bv\s\d{1,2}[:.]\d{2}\b",                                    # v 10:00
    re.I)
START_RE = re.compile(r"spouštíme|spuštěn|zahájen|zaregistr|registrace\s+(je|jsou)\s+otevřen|přihlašování\s+(je|bylo)\s+(otevřen|spuštěn)", re.I)


def classify_form(status, html):
    """Vrátí (stav, krátký text). Stav: OPEN / SCHEDULED / FULL / CLOSED / NOT_FOUND / ERROR / UNKNOWN."""
    if status >= 500:
        return "ERROR", f"HTTP {status}"
    t = text_of(html)
    low = t.lower()

    def snippet(word):
        i = low.find(word)
        start = low.rfind("dotazník", 0, i)
        start = start if start >= 0 and i - start < 120 else max(0, i - 40)
        s = t[start:i + 90]
        return s.split("©")[0].strip()

    if "nenalezen" in low:
        return "NOT_FOUND", "Dotazník nenalezen."
    if "plně obsazen" in low:
        return "FULL", snippet("plně obsazen")
    m = re.search(r"bude\s+dostupn|dostupný\s+od|zpřístupněn\s+od|spuštěn\s+od|otevřen\s+od", low)
    if m:
        return "SCHEDULED", snippet(m.group(0))
    m = re.search(r"byla?\s+dostupn", low)
    if m:
        return "CLOSED", snippet(m.group(0))
    if status == 200 and "dotazník" in low and len(t) > 150:
        title = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
        return "OPEN", text_of(title.group(1)) if title else t[:120]
    return "UNKNOWN", t[:160]


LABEL = {
    "OPEN": "🔴 OTEVŘENO",
    "SCHEDULED": "🟠 oznámeno datum",
    "FULL": "plně obsazen",
    "CLOSED": "uzavřen",
    "NOT_FOUND": "nenalezen",
    "ERROR": "chyba serveru",
    "UNKNOWN": "neznámý stav",
}


# ---------------------------------------------------------------- notifikace

FAILED_SENDS = []


def notify(title, message, priority=PRIO_DEFAULT, tags=None, click=None, email=False):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    print(f"\n[NOTIFIKACE p{priority}] {title}\n{message}\n")
    if not topic:
        FAILED_SENDS.append("chybí NTFY_TOPIC")
        return
    payload = {"topic": topic, "title": title, "message": message, "priority": priority}
    if tags:
        payload["tags"] = tags
    if click:
        payload["click"] = click
        payload["actions"] = [{"action": "view", "label": "Otevřít", "url": click}]
    if email and os.environ.get("NTFY_EMAIL", "").strip():
        payload["email"] = os.environ["NTFY_EMAIL"].strip()
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    data = json.dumps(payload).encode()
    err = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(server, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                if r.status == 200:
                    return
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(3)
    FAILED_SENDS.append(f"{title}: {err}")


# ---------------------------------------------------------------- stav

def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def norm(url):
    return url.rstrip("/").lower()


# ---------------------------------------------------------------- hlavní běh

def main():
    now = datetime.datetime.now(TZ)
    today = now.strftime("%Y-%m-%d")
    stamp = now.strftime("%d. %m. %Y %H:%M")
    prev = load_state()
    first_run = prev is None
    state = json.loads(json.dumps(prev)) if prev else {"forms": {}}
    state.setdefault("forms", {})
    state.setdefault("errors", 0)
    open_forms = []
    summary = []

    if os.environ.get("TEST_NOTIFY", "").lower() == "true":
        notify("🔔 Test – hlídač CPM Třinec", f"Testovací notifikace ({stamp}). Když tohle čtete, doručování funguje.",
               PRIO_HIGH, tags=["bell"])

    # 1) hlavní stránka
    try:
        status, main_html = fetch(MAIN_URL)
        if status != 200:
            raise RuntimeError(f"HTTP {status}")
    except Exception as e:  # noqa: BLE001
        state["errors"] = state.get("errors", 0) + 1
        print(f"Chyba načtení hlavní stránky ({state['errors']}× za sebou): {e}")
        if state["errors"] == ERROR_ALERT_AFTER:
            notify("⚠️ Hlídač CPM Třinec: web nejde načíst",
                   f"Stránka {MAIN_URL} se nepodařilo načíst už {ERROR_ALERT_AFTER}× za sebou (poslední chyba: {e}). "
                   "Zkontrolujte ji prosím ručně.", PRIO_HIGH, tags=["warning"], click=MAIN_URL)
        save_state(state)
        finish(summary)
        return

    if state.get("errors", 0) >= ERROR_ALERT_AFTER:
        notify("✅ Hlídač CPM Třinec: web je znovu dostupný", f"Načtení funguje ({stamp}).", PRIO_LOW)
    state["errors"] = 0

    # 2) záložka Třinec
    panel_html = trinec_panel(main_html)
    if panel_html is None:
        panel_text = "(záložka Pracoviště Třinec nenalezena – web změnil strukturu)"
        panel_links = []
    else:
        panel_text = text_of(panel_html)
        panel_links = dotaznik_links(panel_html, MAIN_URL)
    summary.append(f"Záložka Třinec: {panel_text[:300]}")

    old_panel = state.get("panel_text")
    if old_panel is not None and panel_text != old_panel:
        if panel_links:
            level, prio, icon = "odkaz na registraci", PRIO_URGENT, "🔴"
        elif DATE_RE.search(panel_text) or START_RE.search(panel_text):
            level, prio, icon = "oznámení termínu", PRIO_HIGH, "🟠"
        else:
            level, prio, icon = "změna textu", PRIO_DEFAULT, "🟡"
        notify(f"{icon} CPM Třinec: {level} na webu",
               f"Text záložky Pracoviště Třinec se změnil ({stamp}):\n\n{panel_text[:700]}"
               + (f"\n\nOdkaz: {panel_links[0]}" if panel_links else ""),
               prio, tags=["rotating_light" if prio == PRIO_URGENT else "warning"],
               click=panel_links[0] if panel_links else MAIN_URL, email=prio >= PRIO_HIGH)
    state["panel_text"] = panel_text

    # 3) seznam dotazníků k hlídání
    candidates = list(KNOWN_FORMS) + panel_links + dotaznik_links(main_html, MAIN_URL)
    for page in EXTRA_PAGES:
        try:
            st, h = fetch(page)
            if st == 200:
                candidates += dotaznik_links(h, page)
        except Exception as e:  # noqa: BLE001
            print(f"Nepodařilo se načíst {page}: {e}")
    panel_norm = {norm(u) for u in panel_links}
    forms, seen = [], set()
    for u in candidates:
        n = norm(u)
        if n in seen:
            continue
        seen.add(n)
        if any(p in n for p in IGNORED_FORM_PARTS) and n not in panel_norm:
            continue
        forms.append(u)

    # 4) stav dotazníků
    for url in forms:
        key = norm(url)
        try:
            st, h = fetch(url)
            kind, msg = classify_form(st, h)
        except Exception as e:  # noqa: BLE001
            print(f"Nepodařilo se načíst {url}: {e}")
            summary.append(f"{url}: nenačteno ({e})")
            continue
        summary.append(f"{url}: {LABEL.get(kind, kind)} – {msg}")
        old = state["forms"].get(key)
        state["forms"][key] = {"url": url, "kind": kind, "msg": msg}

        if kind == "OPEN":
            open_forms.append(url)
            # Urgentní notifikace při KAŽDÉM běhu, dokud je dotazník otevřený.
            notify("🔴 REGISTRACE OTEVŘENA – přihlas se HNED!",
                   f"Dotazník je dostupný k vyplnění ({stamp}):\n{url}\n\n„{msg}“\n\n"
                   "Tahle zpráva bude chodit každých ~15 min, dokud je dotazník otevřený. "
                   "Po přihlášení hlídač vypněte (GitHub → Actions → Hlídač CPM Třinec → Disable workflow).",
                   PRIO_URGENT, tags=["rotating_light"], click=url,
                   email=(old is None or old.get("kind") != "OPEN"))
            continue

        if first_run:
            continue
        if old is None:
            notify("🟡 CPM: nový dotazník na webu",
                   f"Objevil se nový odkaz na dotazník ({stamp}):\n{url}\nStav: {LABEL.get(kind, kind)} – {msg}",
                   PRIO_HIGH if kind in ("SCHEDULED", "UNKNOWN") else PRIO_DEFAULT, tags=["mag"], click=url)
        elif (old.get("kind"), old.get("msg")) != (kind, msg):
            if kind == "ERROR" or old.get("kind") == "ERROR":
                continue  # výpadek serveru neohlašujeme jako změnu
            prio = PRIO_HIGH if kind in ("SCHEDULED", "UNKNOWN") else PRIO_DEFAULT
            icon = "🟠" if kind == "SCHEDULED" else "🟡"
            notify(f"{icon} CPM: změna stavu dotazníku",
                   f"{url}\nDříve: {LABEL.get(old.get('kind'), old.get('kind'))} – {old.get('msg')}\n"
                   f"Nyní: {LABEL.get(kind, kind)} – {msg}\n({stamp})",
                   prio, tags=["warning"], click=url, email=prio >= PRIO_HIGH)

    # 5) start a denní potvrzení, že hlídač žije
    status_lines = "\n".join(f"• {s}" for s in summary)
    if first_run:
        notify("🚀 Hlídač CPM Třinec spuštěn",
               f"Hlídání běží ({stamp}). Výchozí stav:\n{status_lines}\n\n"
               "Ozvu se při jakékoli změně, každé ráno pošlu krátké potvrzení, že běžím.",
               PRIO_DEFAULT, tags=["rocket"], click=MAIN_URL)
        state["last_heartbeat"] = today
    elif now.hour >= HEARTBEAT_HOUR and state.get("last_heartbeat") != today and not open_forms:
        notify("✅ Hlídač CPM Třinec běží", f"Ranní kontrola ({stamp}) – beze změny.\n{status_lines}",
               PRIO_LOW, tags=["white_check_mark"])
        state["last_heartbeat"] = today

    if state != prev:
        save_state(state)
    finish(summary, open_forms)


def finish(summary, open_forms=()):
    print("\n".join(summary))
    out = os.environ.get("GITHUB_STEP_SUMMARY")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write("## Hlídač CPM Třinec\n\n" + "\n".join(f"- {s}" for s in summary) + "\n")
            if open_forms:
                f.write("\n### 🔴 REGISTRACE OTEVŘENA\n" + "\n".join(f"- {u}" for u in open_forms) + "\n")
    if FAILED_SENDS:
        print("NEPODAŘILO SE ODESLAT NOTIFIKACI:", *FAILED_SENDS, sep="\n  ")
        sys.exit(1)
    if open_forms:
        # Červený běh v GitHub Actions = další viditelný signál (GitHub může poslat e-mail o selhání).
        print("REGISTRACE OTEVŘENA:", *open_forms, sep="\n  ")
        sys.exit(2)


if __name__ == "__main__":
    main()
