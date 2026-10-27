#!/usr/bin/env python3
"""
Serve the app from only the files a deployment would ship, and check what it says.

    python3 tests/deploy_check.py

Copies the repo minus `.vercelignore` into a temporary directory and exercises
the entrypoint there. Checking status codes alone is not enough: the index
answered 200 while every card read "this template did not draw", because the
preview manifest it consulted lives in a directory the deployment does not ship.
So this asserts on content, and on the absence of the failure text.
"""
import fnmatch
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent


def shippable() -> list[str]:
    rules = [l.strip() for l in (ROOT / ".vercelignore").read_text().splitlines()
             if l.strip() and not l.startswith("#")]

    def ignored(rel: str) -> bool:
        # gitignore semantics, which is what Vercel applies: a pattern with no
        # slash before its end matches at ANY depth, so `data/` also strips
        # gallery/stories/data/. Matching it only at the root is how a deploy
        # once shipped every story without its data while this check passed.
        parts = pathlib.PurePosixPath(rel).parts
        for r in rules:
            anchored = r.startswith("/") or "/" in r.strip("/")
            d = r.strip("/")
            if anchored:
                if rel == d or rel.startswith(d + "/") or fnmatch.fnmatch(rel, d):
                    return True
                continue
            # unanchored: any path component (a directory or the file) may match
            if any(fnmatch.fnmatch(part, d) for part in parts):
                return True
        return False

    out = []
    for src in ROOT.rglob("*"):
        rel = str(src.relative_to(ROOT))
        if rel.startswith((".git/", ".vercel/")) or "__pycache__" in rel:
            continue
        if src.is_file() and not ignored(rel):
            out.append(rel)
    return out


PROBE = '''
import json, sys
from gallery.app import app
c = app.test_client()
out = {}
r = c.get("/")
out["index_status"] = r.status_code
out["index_text"] = r.get_data(as_text=True)
for cid in ["CHT-77B304", "CHT-2AAEE9", "story-stocks-vs-mood", "story-nfl-home-states"]:
    out[f"ws_{cid}"] = c.get(f"/workspace/{cid}").status_code
    out[f"png_{cid}"] = len(c.get(f"/preview/{cid}.png").data)
out["topojson"] = len(c.get("/vendor/topojson/usa_110m.json").data)
out["plotly"] = len(c.get("/vendor/plotly.min.js").data)
out["inspection_404"] = c.get("/chart/CHT-2AAEE9").status_code
rr = c.post("/api/render/CHT-2AAEE9", json={"columns": ["state_code", "category"],
     "rows": [["CA", "Above threshold"], ["TX", "Below threshold"]],
     "captions": {}, "settings": {}})
out["render_ok"] = rr.get_json()["ok"]
rs = c.post("/api/render/story-311-week", json={"columns": ["borough", "requests"],
     "rows": [["Bronx", 3], ["Queens", 5]], "captions": {}, "settings": {}})
out["story_render_ok"] = rs.get_json()["ok"]
print("@@" + json.dumps(out))
'''


def main() -> int:
    files = shippable()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="deploycheck-"))
    for rel in files:
        dst = tmp / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dst)
    size = sum(f.stat().st_size for f in tmp.rglob("*") if f.is_file()) / 1e6
    print(f"shipping {len(files)} files, {size:.1f} MB")

    run = subprocess.run([sys.executable, "-c", PROBE], cwd=tmp,
                         capture_output=True, text=True)
    shutil.rmtree(tmp)
    if "@@" not in run.stdout:
        print(run.stderr[-2500:])
        print("\nFAILED: the app did not start from the shippable files")
        return 1

    import json
    got = json.loads(run.stdout.split("@@", 1)[1])
    text = got.pop("index_text")

    checks = [
        ("index serves", got["index_status"] == 200),
        ("every card carries a preview image", text.count("/preview/") >= 17),
        ("stories lead the page", 0 <= text.find("Start from a story")
                                  < text.find("Or start from a basic shape")),
        ("no card reports a failed preview", "did not draw" not in text
                                             and "Preview unavailable" not in text),
        ("no configuration banner", "Configuration incomplete" not in text),
        ("workspaces serve", all(v == 200 for k, v in got.items() if k.startswith("ws_"))),
        ("preview PNGs served", all(v > 10_000 for k, v in got.items() if k.startswith("png_"))),
        ("map geometry served", got["topojson"] > 10_000),
        ("plotly served", got["plotly"] > 1_000_000),
        ("inspection flow closed", got["inspection_404"] == 404),
        ("map renders", got["render_ok"] is True),
        ("a story renders with its data", got["story_render_ok"] is True),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"\n{len(checks) - len(bad)}/{len(checks)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
