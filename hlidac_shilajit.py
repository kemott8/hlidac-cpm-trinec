#!/usr/bin/env python3
"""
Hlídač ceny: IMMORTAL SHILAJIT – Primal Alchemy (adamraw.cz), balení 100 g.

Cena 100g varianty se čte přímo z produktové stránky s parametrem ?variant=54
(server ji vypíše do <div id="main_price" content="...">). Nepoužívá se /ajax/, který e-shop v robots.txt zakazuje.

Notifikace přijde jen tehdy, když je cena aspoň o 10 % nižší než běžná cena 5 199 Kč (tj. 4 679 Kč a méně).
Během jedné akce přijde jen jednou; znovu jen pokud cena klesne ještě níž, nebo začne nová akce.
"""
import datetime
import json
import os
import re
import sys

from hlidac import FAILED_SENDS, PRIO_HIGH, TZ, fetch, notify

PRODUCT_URL = "https://www.adamraw.cz/immortal-shilajit-primal-alchemy/"
VARIANT_ID = "54"                      # 100g
REGULAR_PRICE = 5199                   # běžná cena 100 g (listopad 2026)
MIN_DISCOUNT = 0.10                    # 10 %
THRESHOLD = int(REGULAR_PRICE * (1 - MIN_DISCOUNT))   # 4679 Kč
ERROR_FAIL_AFTER = 3                   # po kolika nepovedených bězích za sebou skončit chybou (GitHub pošle e-mail)
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state_shilajit.json")


def read_price():
    url = f"{PRODUCT_URL}?variant={VARIANT_ID}"
    status, html = fetch(url)
    if status != 200:
        raise RuntimeError(f"HTTP {status}")
    m = re.search(r'id="main_price"[^>]*content="(\d+(?:[.,]\d+)?)"', html)
    if not m:
        raise RuntimeError("na stránce chybí main_price")
    price = round(float(m.group(1).replace(",", ".")))
    sel = re.search(r'<option[^>]*value="' + VARIANT_ID + r'"[^>]*selected[^>]*>([^<]*)<', html)
    if not sel or "100" not in sel.group(1):
        raise RuntimeError("na stránce není vybraná varianta 100g – e-shop asi změnil čísla variant")
    basic = re.search(r'id="calc_basicprice"[^>]*value="(\d+(?:[.,]\d+)?)"', html)
    basic = round(float(basic.group(1).replace(",", "."))) if basic else None
    if not 1000 <= price <= 30000:
        raise RuntimeError(f"nepravděpodobná cena {price} Kč")
    return price, basic, sel.group(1).strip(), url


def main():
    now = datetime.datetime.now(TZ)
    today = now.strftime("%Y-%m-%d")
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except FileNotFoundError:
        state = {}
    prev = json.loads(json.dumps(state))
    state.setdefault("history", [])

    try:
        price, basic, label, url = read_price()
    except Exception as e:  # noqa: BLE001
        state["errors"] = state.get("errors", 0) + 1
        print(f"Cenu se nepodařilo přečíst ({state['errors']}× za sebou): {e}")
        save(state, prev)
        sys.exit(1 if state["errors"] >= ERROR_FAIL_AFTER else 0)
    state["errors"] = 0

    pct = (1 - price / REGULAR_PRICE) * 100
    line = f"Shilajit {label}: {price} Kč (běžně {REGULAR_PRICE} Kč, {pct:+.1f} % sleva; základní cena e-shopu {basic})"
    print(line)
    if not state["history"] or state["history"][-1]["p"] != price:
        state["history"].append({"d": today, "p": price})
    state["last_price"], state["last_check"] = price, today

    if price <= THRESHOLD:
        new_sale = not state.get("in_sale")
        deeper = price < state.get("alert_price", 10 ** 9)
        if new_sale or deeper:
            notify(f"💰 SLEVA {pct:.0f} %: Shilajit 100 g za {price} Kč",
                   f"IMMORTAL SHILAJIT – Primal Alchemy, balení 100 g\n"
                   f"Nyní: {price} Kč (běžně {REGULAR_PRICE} Kč) → ušetříte {REGULAR_PRICE - price} Kč, −{pct:.0f} %.\n\n{url}",
                   PRIO_HIGH, tags=["moneybag"], click=url, email=True)
            state["alert_price"] = price
        state["in_sale"] = True
    else:
        state["in_sale"] = False
        state.pop("alert_price", None)

    out = os.environ.get("GITHUB_STEP_SUMMARY")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"## Hlídač ceny Shilajit 100 g\n\n- {line}\n- Práh upozornění: {THRESHOLD} Kč\n")
    save(state, prev)
    if FAILED_SENDS:
        print("NEPODAŘILO SE ODESLAT NOTIFIKACI:", *FAILED_SENDS, sep="\n  ")
        sys.exit(1)


def save(state, prev):
    if state != prev:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")


if __name__ == "__main__":
    main()
