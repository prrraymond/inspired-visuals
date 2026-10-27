#!/usr/bin/env python3
"""
PRD v3.3 checks, driven through a real browser (R13-R16).

    python3 tests/format_fit_flow.py [screenshot-dir]   # needs gallery/app.py on :5111

Fit: every template, at two widths, with each caption three times its sample
length -- no text outside the figure, none overlapping other text, the title
clear of the plot, and the PNG download the size of the fitted figure. Then
columns bound by position, header detection and its override, the format panel,
the designer-credit placeholder, and the library card's call to action.
"""
import sys
import tempfile
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5111"
OUT = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="format_fit_")
IDS = ["CHT-77B304", "CHT-BC77C6", "CHT-26F750", "CHT-3389CA", "CHT-ABA629", "CHT-2AAEE9"]
ok, fail = [], []


def check(label, cond, detail=""):
    (ok if cond else fail).append(label)
    print(("  PASS  " if cond else "  FAIL  ") + label + (f"   {detail}" if detail else ""))


OVERFLOW = """() => {
  const gd = document.getElementById('chart'); const box = gd.getBoundingClientRect();
  const full = gd._fullLayout; const bad = [];
  gd.querySelectorAll('.main-svg text').forEach(t => {
    if (!t.textContent.trim()) return;
    const r = t.getBoundingClientRect(); if (!r.height) return;
    const l=r.left-box.left, rt=r.right-box.left, tp=r.top-box.top, b=r.bottom-box.top;
    if (l < -1 || rt > full.width+1 || tp < -1 || b > full.height+1)
      bad.push(t.textContent.slice(0,40)+` [${l|0},${rt|0},${tp|0},${b|0}] in ${full.width}x${full.height}`);
  });
  const rs = Array.from(gd.querySelectorAll('.main-svg text')).filter(t => t.textContent.trim())
    .map(t => [t, t.getBoundingClientRect()]).filter(([t, r]) => r.height);
  for (let i = 0; i < rs.length; i++) for (let j = i + 1; j < rs.length; j++) {
    const [ta, a] = rs[i], [tb, c] = rs[j];
    const w = Math.min(a.right, c.right) - Math.max(a.left, c.left);
    const h = Math.min(a.bottom, c.bottom) - Math.max(a.top, c.top);
    if (w > 2 && h > 2) bad.push('overlap: "' + ta.textContent.slice(0,25) + '" / "' + tb.textContent.slice(0,25) + '"');
  }
  const title = gd.querySelector('.infolayer .gtitle');
  if (title && title.getBoundingClientRect().bottom - box.top > full._size.t + 1)
    bad.push('title overlaps plot');
  return bad;
}"""


def settle(pg):
    pg.wait_for_function("() => document.getElementById('chart-state').textContent === ''",
                         timeout=15000)
    time.sleep(1.0)            # fit runs after the draw resolves


def main():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        for width in (1280, 900):
            pg = b.new_page(viewport={"width": width, "height": 1000}, accept_downloads=True)
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            for cid in IDS:
                pg.goto(f"{BASE}/workspace/{cid}")
                settle(pg)
                tag = f"{cid}@{width}"
                caps = pg.locator("[data-caption]")
                for i in range(caps.count()):
                    c = caps.nth(i)
                    role = c.get_attribute("data-caption")
                    base = {"title": "Percent of test takers who scored high, by income group",
                            "subtitle": "Share of all students in each group, percent",
                            "source": "Source: A long source line naming the study and its years"}.get(
                        role, "Label text that is fairly long")
                    c.fill(" ".join([base] * 3))
                settle(pg)
                bad = pg.evaluate(OVERFLOW)
                check(f"{tag}: long captions stay inside the figure", not bad, "; ".join(bad[:3]))
                if cid == "CHT-77B304":
                    pg.locator("#chart").screenshot(path=f"{OUT}/fit-{width}.png")
                    with pg.expect_download() as d:
                        pg.locator("#download-png").click()
                    path = d.value.path()
                    from PIL import Image
                    im = Image.open(path)
                    full = pg.evaluate("() => [document.getElementById('chart')._fullLayout.width,"
                                       " document.getElementById('chart')._fullLayout.height]")
                    check(f"{tag}: PNG is 2x the fitted figure", im.size == (full[0] * 2, full[1] * 2),
                          f"{im.size} vs {full}")
                    im.save(f"{OUT}/download-{width}.png")
                    with pg.expect_download() as d:
                        pg.locator("#download-svg").click()
                    svg = open(d.value.path()).read()
                    check(f"{tag}: SVG downloads", svg.startswith("<svg") or "<svg" in svg[:200])
            check(f"no JS errors @{width}", not errs, "; ".join(errs[:2]))
            pg.close()

        # --- binding, header detection, format ---
        pg = b.new_page(viewport={"width": 1280, "height": 1000})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(f"{BASE}/workspace/CHT-77B304")
        settle(pg)
        check("needs list is ordered", pg.locator("#needs li .pos").count() == 2)

        def paste(text):
            pg.locator("#open-replace").click()
            pg.locator("#paste").fill(text)
            pg.locator("#use-paste").click()
            settle(pg)

        paste("Bottom 20%,2.4\n20th-40th,3.1\nTop 1%,30.5\nTop 0.1%,38\n")
        notice = pg.locator(".note.binding").inner_text()
        check("headerless paste: first row kept as data",
              pg.locator("#grid tbody tr").count() == 4, notice.replace("\n", " | "))
        check("headerless paste: notice says no header", "no header row" in notice)
        check("headerless paste: draws", pg.evaluate("() => !document.getElementById('chart').hidden"))
        pg.locator("#flip-header").click(); settle(pg)
        check("flip: first row becomes names", pg.locator("#grid tbody tr").count() == 3
              and "column names" in pg.locator(".note.binding").inner_text())

        paste("Income group,Pct,Extra\nBottom,2.4,x\nMiddle,7,y\nTop,38,z\n")
        notice = pg.locator(".note.binding").inner_text()
        check("any header names accepted", "“Income group”" in notice and "“Pct”" in notice,
              notice.replace("\n", " | "))
        check("extra column reported as unused", "Extra" in notice)
        check("no rename button anywhere", pg.locator("text=Rename").count() == 0)

        paste("Pct,Income group\n2.4,Bottom\n7,Middle\n38,Top\n")
        txt = pg.locator("#notes").inner_text()
        check("wrong order: says which column and to reorder",
              "Column 2" in txt and "order" in txt, txt.replace("\n", " | ")[:300])

        pg.locator("#reset-data").click(); settle(pg)
        pg.locator("#format-panel summary").click()
        check("format panel collapsible, opens", pg.locator("#format-panel[open]").count() == 1)
        pg.locator("[data-color=color_0]").evaluate(
            "(e) => { e.value = '#2266aa'; e.dispatchEvent(new Event('input', {bubbles:true})); }")
        pg.locator("[data-format=background]").evaluate(
            "(e) => { e.value = '#fff8e7'; e.dispatchEvent(new Event('input', {bubbles:true})); }")
        pg.locator("#f-font").select_option("Georgia")
        pg.locator("#f-font").dispatch_event("input")
        pg.locator("[data-format=font_size]").fill("16")
        settle(pg)
        got = pg.evaluate("""() => { const gd = document.getElementById('chart');
          return [gd.data[0].marker.color, gd.layout.paper_bgcolor, gd._fullLayout.font.family,
                  gd._fullLayout.font.size]; }""")
        check("format applied (bars, background, font, size)",
              got[0] == "#2266aa" and got[1] == "#fff8e7" and "Georgia" in got[2] and got[3] == 16,
              str(got))
        bad = pg.evaluate(OVERFLOW)
        check("bigger font still fits", not bad, "; ".join(bad[:3]))
        pg.locator("#chart").screenshot(path=f"{OUT}/format.png")
        pg.locator("#reset-format").click(); settle(pg)
        got = pg.evaluate("() => document.getElementById('chart').data[0].marker.color")
        check("reset format restores template colour", got == "#cc4b16", str(got))
        check("credit placeholder shown", "credit to be added" in pg.locator("#credit").inner_text())
        check("no JS errors (flows)", not errs, "; ".join(errs[:2]))

        pg.goto(BASE + "/")
        h = pg.locator(".card-cta").first.evaluate("e => [getComputedStyle(e).backgroundColor, e.offsetHeight]")
        check("card CTA is a small link, not a dark button", h[0] in ("rgba(0, 0, 0, 0)", "transparent") and h[1] < 40, str(h))
        pg.screenshot(path=f"{OUT}/index.png", full_page=False)
        b.close()
    print(f"\n{len(ok)} passed, {len(fail)} failed")
    sys.exit(1 if fail else 0)


main()
