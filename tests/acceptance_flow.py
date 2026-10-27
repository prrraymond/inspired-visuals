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
import time

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
      // x matters: a horizontal bar chart puts its values there, and a
      // signature that reads only y never changes when the data does.
      return JSON.stringify(d.data.map(t => [t.type,
             arr(t.z||t.y||t.x||t.locations).length,
             JSON.stringify(arr(t.y).slice(0,60)) + "|" +
             JSON.stringify(arr(t.x).slice(0,60)) + "|" +
             JSON.stringify(arr(t.z).slice(0,60))]));
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


def until(fn, timeout=20.0, interval=0.25):
    """
    Wait for the OUTCOME, not for a guess at how long it takes.

    Edits are debounced before they are sent, so waiting on "is a request in
    flight?" can return before one has even started -- which made the title check
    pass or fail depending on timing. Polling the thing being asserted has no such
    window: it is true, or the timeout is a real failure.
    """
    end = time.time() + timeout
    while time.time() < end:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def drawn(pg, timeout=15000):
    pg.wait_for_selector("#chart .plot-container", timeout=timeout)
    pg.wait_for_function(
        "() => document.querySelectorAll('#chart .choroplethlayer path, #chart .barlayer path,"
        " #chart .scatterlayer .js-line, #chart .points path').length > 0", timeout=timeout)


def run(pw, chartid, edit_col, paste_good, paste_bad, bad_column):
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 1000})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))

    # 1-2. the library ------------------------------------------------------
    pg.goto(BASE + "/", wait_until="networkidle")
    imgs = pg.evaluate("""() => [...document.querySelectorAll('.shot img')]
        .map(i => [i.naturalWidth, i.naturalHeight])""")
    check(f"1. every preview rendered and loaded ({len(CASES)} expected)",
          len(imgs) == len(CASES) and all(w > 0 and h > 0 for w, h in imgs), f"sizes={imgs}")
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
    check("5-6. editing a number changes the chart",
          until(lambda: chart_sig(pg) not in (None, before)))

    # 7-8. edit the title ---------------------------------------------------
    title = pg.locator('input[data-caption="title"]')
    title.click()
    title.fill("Acceptance test heading")

    def title_landed():
        t = chart_title(pg)
        return ("Acceptance test heading" in (t[0] or "")
                or any("Acceptance test heading" in (a or "") for a in t[1]))

    check("7-8. editing the title changes the title", until(title_landed))

    # 9-10. replace the data with something compatible ----------------------
    pg.evaluate("document.getElementById('replace').showModal()")
    pg.locator("#paste").fill(paste_good)
    pg.locator("#use-paste").click()
    want = len(paste_good.strip().splitlines()) - 1
    landed = until(lambda: pg.locator("#grid tbody tr").count() == want
                   and pg.evaluate("() => !document.getElementById('chart').hidden"))
    check("9-10. compatible data renders in the same template", landed,
          f"{pg.locator('#grid tbody tr').count()} rows, wanted {want}")

    # 11. and something incompatible ---------------------------------------
    pg.evaluate("document.getElementById('replace').showModal()")
    pg.locator("#paste").fill(paste_bad)
    pg.locator("#use-paste").click()
    read_notes = lambda: pg.evaluate("""() => [...document.querySelectorAll('#notes .note')]
        .map(n => [n.className.replace('note ',''), n.innerText.trim()])""")
    until(lambda: any(lvl in ("error", "warning") for lvl, _ in read_notes()))
    surfaced = [t for lvl, t in read_notes() if lvl in ("error", "warning")]
    check("11. incompatible data produces an actionable error", bool(surfaced),
          json.dumps(surfaced[:1])[:200])
    check("11b. the message names the column, not a stack trace",
          bool(surfaced) and bad_column in surfaced[0] and "Traceback" not in surfaced[0],
          f"looking for {bad_column!r}")

    # the fixes from the 2026-09-29 review ---------------------------------
    check("headers sit over their own values",
          pg.evaluate("""() => [...document.querySelectorAll('#grid thead th')]
              .filter(th => th.classList.contains('k-number'))
              .every(th => getComputedStyle(th).textAlign === 'right')"""))
    # Finding 5 was on the ENTRY page, which is where the contract is printed --
    # checking the workspace for it would have passed without testing anything.
    pg.goto(f"{BASE}/chart/{chartid}", wait_until="networkidle")
    storage_types = "() => /\\bobject\\b|float64|int64|datetime64/.test(" \
                    "document.querySelector('main').innerText)"
    check("no pandas storage types on the entry page", not pg.evaluate(storage_types))
    pg.goto(f"{BASE}/chart/{chartid}?dev=1", wait_until="networkidle")
    # Only meaningful where a contract is rendered at all. These entries have not
    # been through Stage D, so there is no contract section and nothing to show.
    if pg.locator(".colcard").count():
        check("...but they are still there in developer view", pg.evaluate(storage_types))

    check("no uncaught JS errors", not errs, "; ".join(errs[:2]))
    b.close()


CASES = [
    ("CHT-77B304", "Ranked comparison", 2,
     "group,value\nAlpha,2.1\nBeta,5.4\nGamma,9.8\nDelta,18.2\nEpsilon,31.0\n",
     "group,value\nAlpha,low\nBeta,high\nGamma,mid\n", "value"),
    ("CHT-BC77C6", "Gains and losses", 2,
     "group,change\nAlpha,-2.5\nBeta,-0.8\nGamma,0.4\nDelta,1.9\nEpsilon,3.2\n",
     "group,change\nAlpha,down\nBeta,up\nGamma,flat\n", "change"),
    ("CHT-26F750", "Two-part split", 2,
     "group,share_first,share_second\nAlpha,70,30\nBeta,55,45\nGamma,88,12\n",
     "group,share_first,share_second\nAlpha,most,some\nBeta,few,many\n", "share_first"),
    ("CHT-3389CA", "Measure against a baseline", 2,
     "position,ratio\n10,1.1\n30,0.95\n50,1.02\n70,0.88\n90,1.4\n99,2.0\n",
     "position,ratio\n10,low\n30,high\n50,mid\n", "ratio"),
    ("CHT-ABA629", "Net agreement", 2,
     "statement,net\nAlpha,12\nBeta,4\nGamma,-7\nDelta,-15\n",
     "statement,net\nAlpha,agree\nBeta,disagree\nGamma,neutral\n", "net"),
    ("CHT-2AAEE9", "Highlight map", 2,
     "state_code,category\nCA,Above threshold\nTX,Below threshold\nNY,Above threshold\n"
     "FL,Below threshold\nWA,Above threshold\nIL,Below threshold\n",
     "state_code\nCA\nTX\nNY\n", "category"),
]


def main():
    with sync_playwright() as pw:
        for cid, name, col, good, bad, bad_column in CASES:
            print(f"=== {cid}  {name} ===")
            run(pw, cid, col, good, bad, bad_column)
            print()
    print(f"{len(ok)} passed, {len(fail)} failed")
    if fail:
        print("FAILED: " + "; ".join(fail))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
