#!/usr/bin/env python3
"""
The first acceptance flow, driven through a real browser.

    python3 tests/acceptance_flow.py          # needs gallery/app.py running on :5111

Checks what a person does, not what the code returns: pick a chart, see it draw,
edit a number, edit the title, replace the data, and be told something useful when
the data is wrong. Every template in the catalog goes through the same path.

Requires playwright. It is a product check, not a unit test -- it fails when the
flow breaks, which is the only kind of breakage that matters here.
"""
import json
import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5111"
ok, fail = [], []


def check(label, cond, detail=""):
    (ok if cond else fail).append(label)
    print(("  PASS  " if cond else "  FAIL  ") + label + (f"   {detail}" if detail else ""))


def chart_sig(pg):
    return pg.evaluate("""() => {
      const d = document.getElementById('chart');
      if (!d || !d.data) return null;
      const arr = v => Array.isArray(v) ? v : (v == null ? [] : [v]);
      return JSON.stringify(d.data.map(t => [t.type, arr(t.z||t.y||t.locations).length,
             JSON.stringify(arr(t.y||t.z||t.text).slice(0, 60))]));
    }""")


def chart_title(pg):
    return pg.evaluate("""() => {
      const lay = (document.getElementById('chart') || {}).layout || {};
      return [lay.title && lay.title.text, (lay.annotations||[]).map(a => a.text)];
    }""")


def settle(pg, timeout=15000):
    pg.wait_for_function(
        "() => document.getElementById('chart-state').textContent !== 'updating…'",
        timeout=timeout)
    pg.wait_for_timeout(500)


def drawn(pg, timeout=15000):
    pg.wait_for_selector("#chart .plot-container", timeout=timeout)
    pg.wait_for_function(
        "() => document.querySelectorAll('#chart .choroplethlayer path, #chart .barlayer path,"
        " #chart .scatterlayer .js-line, #chart .points path').length > 0", timeout=timeout)


def run(pw, chartid, edit_col, paste_good, paste_bad):
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 1000})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))

    # 1-2. the library ------------------------------------------------------
    pg.goto(BASE + "/", wait_until="networkidle")
    imgs = pg.evaluate("""() => [...document.querySelectorAll('.shot img')]
        .map(i => [i.naturalWidth, i.naturalHeight])""")
    check("1. three rendered previews, all loaded",
          len(imgs) == 3 and all(w > 0 and h > 0 for w, h in imgs), f"sizes={imgs}")
    check("1b. no ids, status or caveat counts on the library page",
          not pg.evaluate("""() => /CHT-[0-9A-F]{6}|Needs hydration|Caveats/.test(
              document.querySelector('main').innerText)"""))

    card = pg.locator(f'a.card-link[href="/workspace/{chartid}"]')
    check("2. the card opens a workspace", card.count() == 1)
    card.click()
    pg.wait_for_load_state("networkidle")

    # 3-4. the chart is there, and so are its rows --------------------------
    drawn(pg)
    check("3. chart opens immediately, no further clicks", chart_sig(pg) is not None)
    rows = pg.locator("#grid tbody tr").count()
    check("4. the underlying rows are visible", rows > 0, f"{rows} rows")

    # 5-6. edit a number ----------------------------------------------------
    before = chart_sig(pg)
    cell = pg.locator(f"#grid tbody tr:nth-child(1) td:nth-child({edit_col}) input")
    cell.click()
    cell.fill("999")
    settle(pg)
    check("5-6. editing a number changes the chart", before != chart_sig(pg))

    # 7-8. edit the title ---------------------------------------------------
    title = pg.locator('input[data-caption="title"]')
    title.click()
    title.fill("Acceptance test heading")
    settle(pg)
    after = chart_title(pg)
    check("7-8. editing the title changes the title",
          after[0] == "Acceptance test heading"
          or any("Acceptance test heading" in (a or "") for a in after[1]))

    # 9-10. replace the data with something compatible ----------------------
    pg.evaluate("document.getElementById('replace').showModal()")
    pg.locator("#paste").fill(paste_good)
    pg.locator("#use-paste").click()
    settle(pg)
    new_rows = pg.locator("#grid tbody tr").count()
    check("9-10. compatible data renders in the same template",
          pg.evaluate("() => !document.getElementById('chart').hidden")
          and new_rows == len(paste_good.strip().splitlines()) - 1,
          f"{new_rows} rows")

    # 11. and something incompatible ---------------------------------------
    pg.evaluate("document.getElementById('replace').showModal()")
    pg.locator("#paste").fill(paste_bad)
    pg.locator("#use-paste").click()
    settle(pg)
    notes = pg.evaluate("""() => [...document.querySelectorAll('#notes .note')]
        .map(n => [n.className.replace('note ',''), n.innerText.trim()])""")
    surfaced = [t for lvl, t in notes if lvl in ("error", "warning")]
    check("11. incompatible data produces an actionable error", bool(surfaced),
          json.dumps(surfaced[:1])[:200])
    check("11b. the message names the column, not a stack trace",
          bool(surfaced) and "value" in surfaced[0] and "Traceback" not in surfaced[0])

    # the fixes from the 2026-09-29 review ---------------------------------
    check("headers sit over their own values",
          pg.evaluate("""() => [...document.querySelectorAll('#grid thead th')]
              .filter(th => th.classList.contains('k-number'))
              .every(th => getComputedStyle(th).textAlign === 'right')"""))
    check("no pandas storage types on screen",
          not pg.evaluate("""() => /\\bobject\\b|float64|int64|datetime64/.test(
              document.querySelector('main').innerText)"""))

    check("no uncaught JS errors", not errs, "; ".join(errs[:2]))
    b.close()


CASES = [
    ("CHT-678195", "Before/after trend", 2,
     "month,value\n2024-01-01,120\n2024-02-01,140\n2024-03-01,131\n2024-04-01,88\n"
     "2024-05-01,96\n2024-06-01,109\n",
     "month,value\n2024-01-01,a\n2024-02-01,b\n2024-03-01,c\n"),
    ("CHT-6FBD47", "State comparison map", 3,
     "state,value\nCA,10\nTX,55\nNY,30\nFL,42\nWA,18\nIL,26\nOH,9\nGA,61\n",
     "state,value\nCA,high\nTX,low\nNY,mid\n"),
    ("CHT-85FB02", "Small-multiple comparison", 3,
     "group,year,value\nNorth,2021,104\nNorth,2022,97\nNorth,2023,112\n"
     "South,2021,88\nSouth,2022,95\nSouth,2023,101\n",
     "group,year,value\nNorth,2021,x\nNorth,2022,y\nSouth,2021,z\n"),
]


def main():
    with sync_playwright() as pw:
        for cid, name, col, good, bad in CASES:
            print(f"=== {cid}  {name} ===")
            run(pw, cid, col, good, bad)
            print()
    print(f"{len(ok)} passed, {len(fail)} failed")
    if fail:
        print("FAILED: " + "; ".join(fail))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
