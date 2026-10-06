#!/usr/bin/env python3
"""
ChartGen gallery — browse the library, and take a template through to a chart.

    THE RENDER PATH exec()s TEMPLATE CODE.

    Run locally it binds to 127.0.0.1 with no auth and no accounts. Deployed, it
    serves gallery/bundle/ -- no Supabase key, no Notion token, and no network
    call on the request path -- so the only code exec() can reach is the reviewed
    set frozen into the bundle at build time. Rebuilding the bundle is the review
    gate.

    It is still NOT a sandbox. Before this serves data from anyone you would not
    run locally, move build_figure into an isolated worker: separate process, no
    network, no filesystem, hard timeout. See gallery/render_local.py.

Run:  python3 gallery/app.py     (from the repo root, so .env.local resolves)
"""
from __future__ import annotations

import io
import functools
import json
import math
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
# Scripts/lib for local work; the bundle's vendored copy for a deployment, which
# ships no Scripts/ at all. Whichever exists wins, so this module imports the
# same way however it is entered -- directly, or as gallery.app from the root.
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "Scripts", "lib"))
sys.path.insert(0, os.path.join(_HERE, "bundle", "lib"))

import numpy as np
import pandas as pd
import requests
from flask import (Flask, Response, abort, jsonify, redirect, render_template, request,
                   send_file, url_for)

import bundle
import catalog
import chartgen
import library
import previews
import runs
import tabular
from demo_data import demo_frame
from contract_view import describe_contract, describe_proposal
from data_contract import derive_contract
from input_check import check_input, blocking, repairs
from render_guard import (AUTOMATION, HUMAN, SelectionRefused, confirm_selection,
                          derive_parameters, manual_proposal, propose_parameters,
                          reject_proposal, review_label, select_parameters)
from render_local import RenderRefused, render as do_render
from template_iface import read_interface, suggest_mapping

app = Flask(__name__)
YOU = "you"                       # the single local operator

# Serve the frozen bundle when one is present. A deployment has no Supabase
# key and no Notion token, so every route has to be satisfiable from files in
# the repo; locally the bundle is simply a faster, offline path.
BUNDLED = bundle.available()

# A deployed instance is reachable by people who did not build it. The limits
# below are not a sandbox -- they bound the obvious ways a paste can cost the
# server more than it should.
MAX_BODY_BYTES = 2_000_000
MAX_ROWS = 5_000
MAX_CELLS = 50_000
app.config["MAX_CONTENT_LENGTH"] = MAX_BODY_BYTES


def _local_only(view):
    """
    Mark a route as part of the local inspection flow.

    These read Notion live and show the pipeline's own view of an entry. A
    deployment has no Notion token and no business serving them, so they answer
    404 there rather than failing halfway through with a credential error.
    """
    @functools.wraps(view)
    def guarded(*args, **kwargs):
        if BUNDLED:
            abort(404)
        return view(*args, **kwargs)
    return guarded


def _dev() -> bool:
    """
    Developer view. Everything the pipeline knows about an entry -- ids, status,
    caveat counts, contracts, provenance -- is still here and still true. It is
    simply not what someone choosing a chart is trying to find out, so it lives
    behind this rather than on the page by default.
    """
    return request.args.get("dev") in ("1", "true", "on")


@app.context_processor
def _globals():
    args = request.args.to_dict()
    if _dev():
        args.pop("dev", None)
    else:
        args["dev"] = "1"
    # A bundled deployment has no credentials by design, so it has none to
    # complain about. Checking would report their absence as a fault.
    return {"config_problems": [] if BUNDLED else library.check_credentials(),
            "dev": _dev(),
            "dev_href": url_for(request.endpoint, **{**(request.view_args or {}), **args})
                        if request.endpoint else "?dev=1"}


# --------------------------------------------------------------------------- #
# library -- choose a chart
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    if BUNDLED:
        data = bundle.entries()
        entries = [bundle.Entry(cid, data[cid]) for cid in data]
        error = None
    else:
        try:
            entries, error = library.list_entries(), None
        except Exception as exc:
            entries, error = [], f"{type(exc).__name__}: {exc}"

    rank = {cid: i for i, cid in enumerate(catalog.ORDER)}
    cards, undescribed = [], []
    for e in entries:
        spec = catalog.entry(e.chartid)
        if spec is None:
            # Not hidden: a template nobody has described is a real state of the
            # library, and a card that says so is more use than a silent omission.
            undescribed.append(e)
            continue
        # Bundled, a preview exists if its file does. Asking previews.status()
        # reads the build manifest under gallery/cache/, which is deliberately
        # not shipped -- so every card reported "this template did not draw"
        # while the PNG sat right there in the bundle.
        if BUNDLED:
            df = demo_frame(e.chartid)
            preview = {"ok": bundle.preview(e.chartid) is not None,
                       "problem": None if bundle.preview(e.chartid) else
                                  "No preview was built for this template.",
                       "rows": int(len(df)) if df is not None else None}
        else:
            preview = previews.status(e.chartid)
        cards.append({"chartid": e.chartid, "entry": e, "spec": spec,
                      "preview": preview})
    cards.sort(key=lambda c: rank.get(c["chartid"], 99))
    return render_template("index.html", cards=cards, undescribed=undescribed, error=error)


@app.route("/preview/<chartid>.png")
def preview_image(chartid):
    path = bundle.preview(chartid) if BUNDLED else previews.path(chartid)
    if path is None:
        abort(404)
    return Response(path.read_bytes(), mimetype="image/png",
                    headers={"Cache-Control": "no-cache"})


# --------------------------------------------------------------------------- #
# workspace -- the chart, its data, and its words, on one page
# --------------------------------------------------------------------------- #
# Plotly ships its own bundle inside the Python package. Serving that rather than
# a CDN keeps the workspace working with the network off, and guarantees the
# browser draws with the same version that rendered the preview.
import plotly                                                        # noqa: E402
PLOTLY_JS = os.path.join(os.path.dirname(plotly.__file__), "package_data", "plotly.min.js")


@app.route("/vendor/plotly.min.js")
def plotly_js():
    return send_file(PLOTLY_JS, mimetype="text/javascript", conditional=True)


# Plotly fetches map geometry at draw time, from cdn.plot.ly by default. That
# makes the first paint of a map wait on the network, and makes the workspace
# fail entirely offline. The file is small, public and immutable, so it is
# fetched once and served from disk afterwards.
TOPOJSON_DIR = previews.CACHE / "topojson"
_TOPOJSON_NAME = re.compile(r"^[a-z_]+_\d+m\.json$")


@app.route("/vendor/topojson/<name>")
def topojson(name):
    if not _TOPOJSON_NAME.match(name):
        abort(404)
    # Frozen into the bundle for a deployment: the request path must not fetch
    # anything, and on a read-only filesystem it could not cache it anyway.
    vendored = bundle.vendored(name)
    if vendored is not None:
        return send_file(vendored, mimetype="application/json", conditional=True)

    path = TOPOJSON_DIR / name
    if path.exists():
        return send_file(path, mimetype="application/json", conditional=True)
    try:
        r = requests.get(f"https://cdn.plot.ly/{name}", timeout=20)
        r.raise_for_status()
    except requests.RequestException as exc:
        return jsonify({"error": f"could not fetch {name}: {exc}"}), 502
    try:
        TOPOJSON_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
        print(f"  - cached map geometry {name} ({len(r.content):,}B)")
    except OSError:
        pass                      # read-only filesystem: serve it without caching
    return Response(r.content, mimetype="application/json")


def _template_for(chartid):
    """(spec, source) for a catalogued chart, or a 404."""
    spec = catalog.entry(chartid)
    if spec is None:
        abort(404)
    if BUNDLED:
        src = bundle.template(chartid)
        if src is None:
            abort(503)
        return spec, src
    src = previews.source(chartid)
    if src is None:
        try:
            entry = library.get_entry(chartid)
            src = entry._code if entry else None
        except Exception:
            src = None
    if src is None:
        abort(503)
    return spec, src


@app.route("/workspace/<chartid>")
def workspace(chartid):
    spec, src = _template_for(chartid)
    state = chartgen.state(chartid, src, demo_frame(chartid))
    # The catalog row is for the collapsed details section only. A slow or absent
    # Notion must not stop someone making a chart, so its failure is silent here.
    if BUNDLED:
        data = bundle.entries().get(chartid)
        entry = bundle.Entry(chartid, data) if data else None
    else:
        try:
            entry = library.get_entry(chartid)
        except Exception:
            entry = None
    return render_template("workspace.html", chartid=chartid, spec=spec,
                           state=state, entry=entry)


def _too_big(columns, rows) -> str | None:
    """
    Refuse a table that would cost more to draw than it is worth.

    Said in the same plain terms as every other refusal, because a person who
    pastes a large export should be told what the limit is, not shown a timeout.
    """
    if len(rows) > MAX_ROWS:
        return (f"That is {len(rows):,} rows. This tool draws up to {MAX_ROWS:,} — "
                f"summarise the data first, or chart a slice of it.")
    cells = len(rows) * max(1, len(columns))
    if cells > MAX_CELLS:
        return (f"That is {cells:,} cells. This tool handles up to {MAX_CELLS:,} — "
                f"try fewer columns, or fewer rows.")
    return None


@app.route("/api/render/<chartid>", methods=["POST"])
def api_render(chartid):
    """
    Redraw with whatever the page currently holds.

    The browser owns the working dataset -- it arrives in full on every call. That
    costs a few KB and buys the absence of a session: no run to expire between an
    edit and the chart it produces, and a reload that never shows someone else's data.
    """
    _, src = _template_for(chartid)
    body = request.get_json(silent=True) or {}
    columns, rows = body.get("columns") or [], body.get("rows") or []
    too_big = _too_big(columns, rows)
    if too_big:
        return jsonify({"ok": False, "stage": "data", "problems": [too_big]}), 413
    try:
        df = tabular.from_grid(columns, rows)
    except Exception as exc:
        return jsonify({"ok": False, "stage": "data",
                        "problems": [f"could not read the table: {exc}"]}), 400

    findings = chartgen.check_against_demo(chartid, df, src)
    state = chartgen.state(chartid, src, df,
                           captions=body.get("captions") or {},
                           settings=body.get("settings") or {})
    state["notes"] = findings
    return jsonify(state)


@app.route("/api/parse", methods=["POST"])
def api_parse():
    """Turn pasted text into a grid. Parsing failures are messages, not stack traces."""
    text = (request.get_json(silent=True) or {}).get("text") or ""
    try:
        df = tabular.parse_text(text)
        over = _too_big(list(df.columns), df.values.tolist())
        if over:
            return jsonify({"ok": False, "problem": over})
    except Exception as exc:
        return jsonify({"ok": False,
                        "problem": f"That didn’t read as a table: {exc}"}), 200
    if df.empty:
        return jsonify({"ok": False, "problem": "That parsed, but there are no rows in it."})
    return jsonify({"ok": True, "grid": tabular.to_grid(df)})


@app.route("/chart/<chartid>")
@_local_only
def detail(chartid):
    try:
        entry = library.get_entry(chartid)
    except Exception as exc:
        return render_template("detail.html", entry=None, contract=None,
                               error=f"{type(exc).__name__}: {exc}"), 500
    if entry is None:
        abort(404)
    return render_template("detail.html", entry=entry,
                           contract=describe_contract(entry.contract),
                           code=entry._code, error=None)


# --------------------------------------------------------------------------- #
# 1. data in
# --------------------------------------------------------------------------- #
def _parse_upload() -> tuple[pd.DataFrame | None, str | None]:
    upload = request.files.get("file")
    if upload and upload.filename:
        raw = upload.read()
        try:
            return pd.read_csv(io.BytesIO(raw)), None
        except Exception as exc:
            return None, f"could not read {upload.filename!r} as CSV: {exc}"
    text = (request.form.get("pasted") or "").strip()
    if not text:
        return None, "Nothing supplied — paste rows or choose a CSV file."
    sep = "\t" if text.count("\t") >= text.count(",") and "\t" in text else ","
    try:
        return pd.read_csv(io.StringIO(text), sep=sep), None
    except Exception as exc:
        return None, f"could not parse what you pasted: {exc}"


def _coerce(df: pd.DataFrame) -> pd.DataFrame:
    for c in df.columns:
        if df[c].dtype == object:
            num = pd.to_numeric(df[c], errors="coerce")
            if num.notna().mean() > 0.9:
                df[c] = num
                continue
            try:
                dt = pd.to_datetime(df[c], errors="coerce", format="mixed")
                if dt.notna().mean() > 0.9:
                    df[c] = dt
            except Exception:
                pass
    return df


@app.route("/chart/<chartid>/use", methods=["GET", "POST"])
@_local_only
def use(chartid):
    entry = library.get_entry(chartid)
    if entry is None:
        abort(404)
    if request.method == "GET":
        return render_template("use.html", entry=entry,
                               contract=describe_contract(entry.contract), error=None)

    df, err = _parse_upload()
    if err:
        return render_template("use.html", entry=entry,
                               contract=describe_contract(entry.contract), error=err), 400
    df = _coerce(df)
    rid = runs.new_run(chartid=chartid, df=df, template=entry._code,
                       entry_contract=entry.contract, title=entry.title,
                       mapping={}, proposals={}, captions={}, result=None)
    return redirect(url_for("run_data", rid=rid))


# --------------------------------------------------------------------------- #
# 2. check + map
# --------------------------------------------------------------------------- #
@app.route("/run/<rid>/data", methods=["GET", "POST"])
@_local_only
def run_data(rid):
    run = runs.get(rid)
    if run is None:
        abort(404)
    df = run["df"]

    if request.method == "POST" and request.form.get("apply_repairs"):
        fixes = repairs(check_input(df, run["entry_contract"] or {"columns": []}))
        if fixes:
            df = df.rename(columns=fixes)
            runs.update(rid, df=df)
        return redirect(url_for("run_data", rid=rid))

    iface = read_interface(run["template"])
    contract = derive_contract(df, name=run["chartid"])
    findings = check_input(df, run["entry_contract"] or {"columns": []})

    if request.method == "POST":
        mapping = {p.var: request.form.get(p.var) or None for p in iface["placeholders"]}
        derive_from = {}
        for p in iface["placeholders"]:
            if mapping.get(p.var) == "__derive__":
                mapping[p.var] = None
                src = request.form.get(f"{p.var}__source")
                if src:
                    derive_from[p.role] = src
        mapping = {k: v for k, v in mapping.items() if v}
        mapping["_derive"] = derive_from
        missing = [p.var for p in iface["placeholders"]
                   if not p.optional and p.var not in mapping
                   and p.role not in derive_from]
        if missing:
            return render_template("data.html", run=run, iface=iface, contract=contract,
                                   findings=findings, df=df, mapping=mapping,
                                   numeric=_numeric_cols(contract),
                                   error=f"Still unmapped: {', '.join(missing)}"), 400
        runs.update(rid, mapping=mapping, contract=contract)
        return redirect(url_for("run_parameters", rid=rid))

    mapping = run.get("mapping") or suggest_mapping(iface["placeholders"],
                                                    list(df.columns), contract)
    return render_template("data.html", run=run, iface=iface, contract=contract,
                           findings=findings, df=df, mapping=mapping,
                           numeric=_numeric_cols(contract), error=None)


def _numeric_cols(contract) -> list:
    return [c["name"] for c in contract["columns"]
            if c["kind"] == "numeric" and not c["all_null"]]


# --------------------------------------------------------------------------- #
# 3. parameters
# --------------------------------------------------------------------------- #
def _occupancy(series: pd.Series, edges: list) -> list:
    s = pd.to_numeric(series, errors="coerce").dropna().astype(float)
    cut = pd.cut(s, bins=[-np.inf] + list(edges) + [np.inf], labels=False)
    return cut.value_counts().reindex(range(len(edges) + 1), fill_value=0).tolist()


def _fresh_proposals(run) -> dict:
    """One proposal per numeric column. Every column, no heuristic about meaning."""
    contract, df = run["contract"], run["df"]
    out = {}
    for name in _numeric_cols(contract):
        d = derive_parameters(contract, name)
        edges = [e for e in d["edges"] if math.isfinite(e)]
        p = propose_parameters(contract, name, occupancy=_occupancy(df[name], edges))
        try:
            p = select_parameters(p, by="gallery", actor_type=AUTOMATION)
        except SelectionRefused:
            pass                                   # unreliable: stays PROPOSED
        out[name] = p
    return out


@app.route("/run/<rid>/parameters", methods=["GET", "POST"])
@_local_only
def run_parameters(rid):
    run = runs.get(rid)
    if run is None or run.get("contract") is None:
        abort(404)

    if not run.get("proposals"):
        runs.update(rid, proposals=_fresh_proposals(run))
        run = runs.get(rid)

    if request.method == "POST":
        props = dict(run["proposals"])
        errors = []
        for name, prop in list(props.items()):
            action = request.form.get(f"action__{name}", "keep")
            try:
                if action == "confirm":
                    props[name] = confirm_selection(prop, by=YOU)
                elif action == "author":
                    raw = request.form.get(f"edges__{name}", "")
                    edges = sorted({round(float(x), 4) for x in raw.split(",") if x.strip()})
                    if len(edges) < 1:
                        errors.append(f"{name}: no boundaries supplied")
                        continue
                    m = manual_proposal(run["contract"], name, edges=edges,
                                        occupancy=_occupancy(run["df"][name], edges),
                                        supersedes=prop)
                    props[name] = select_parameters(m, by=YOU, actor_type=HUMAN)
                elif action == "dismiss":
                    props[name] = reject_proposal(
                        prop, by=YOU, actor_type=HUMAN,
                        reason=request.form.get(f"reason__{name}") or "not a measure")
                elif action == "override":
                    reason = (request.form.get(f"reason__{name}") or "").strip()
                    props[name] = select_parameters(prop, by=YOU, actor_type=HUMAN,
                                                    override_unreliable=True, reason=reason)
            except SelectionRefused as exc:
                errors.append(f"{name}: {exc}")
            except ContractViolationAlias as exc:                      # pragma: no cover
                errors.append(f"{name}: {exc}")
        runs.update(rid, proposals=props)
        if errors:
            return _parameters_page(rid, errors=errors), 400
        return redirect(url_for("run_render", rid=rid))

    return _parameters_page(rid)


class ContractViolationAlias(Exception):
    pass


def _parameters_page(rid, errors=None):
    run = runs.get(rid)
    contract, df = run["contract"], run["df"]
    cards = []
    for name, prop in run["proposals"].items():
        col = next(c for c in contract["columns"] if c["name"] == name)
        s = pd.to_numeric(df[name], errors="coerce").dropna().astype(float)
        lo, hi = float(s.min()), float(s.max())
        pad = (hi - lo) * 0.06 or 1.0
        cards.append({
            "name": name,
            "view": describe_proposal(prop),
            "stats": col["stats"],
            # NB: not "values" -- dict.values shadows it in Jinja (this bit once already)
            "points": [round(float(v), 6) for v in s.tolist()],
            "domain": [round(lo - pad, 6), round(hi + pad, 6)],
            "proposed_edges": [e for e in prop["edges"] if math.isfinite(e)],
            "is_derive_source": name in (run["mapping"].get("_derive") or {}).values(),
        })
    return render_template("parameters.html", run=run, cards=cards, errors=errors or [])


# --------------------------------------------------------------------------- #
# 4. render + caption
# --------------------------------------------------------------------------- #
@app.route("/run/<rid>/render", methods=["GET", "POST"])
@_local_only
def run_render(rid):
    run = runs.get(rid)
    if run is None or not run.get("proposals"):
        abort(404)

    if request.method == "POST":
        captions = {k: (request.form.get(k) or "").strip()
                    for k in ("title", "subtitle", "units", "source", "above", "below")}
        runs.update(rid, captions=captions)
        run = runs.get(rid)

    settled = {n: p for n, p in run["proposals"].items() if p.get("status") == "selected"}
    refused = None
    try:
        result = do_render(run["template"], run["df"], run["contract"],
                           dict(run["mapping"]), settled, run.get("captions") or {})
        runs.update(rid, result=result)
    except RenderRefused as exc:
        result, refused = None, exc

    iface = read_interface(run["template"])
    return render_template("output.html", run=runs.get(rid), result=result,
                           refused=refused, captions=run.get("captions") or {},
                           caption_roles=sorted(
                               set(_caption_roles(iface)) | {"title", "subtitle", "source"}))


def _caption_roles(iface) -> list:
    from template_iface import caption_constants
    return list(caption_constants(iface["constants"]).keys())


@app.route("/run/<rid>/image.<fmt>")
@_local_only
def run_image(rid, fmt):
    run = runs.get(rid)
    if run is None or not run.get("result") or fmt not in run["result"]["images"]:
        abort(404)
    mime = {"png": "image/png", "svg": "image/svg+xml"}[fmt]
    return Response(run["result"]["images"][fmt], mimetype=mime)


@app.errorhandler(404)
def _404(_):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "problems": ["No such chart."]}), 404
    return render_template("404.html"), 404


@app.errorhandler(500)
def _500(exc):
    """
    An API caller gets JSON even when something unforeseen breaks.

    The browser parses every response as JSON; an HTML error page turned a clear
    server-side refusal into "Unexpected token '<'" on screen, which told the user
    nothing about their data.
    """
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "stage": "unexpected",
                        "problems": [f"{type(exc).__name__}: {exc}"]}), 500
    raise exc


if __name__ == "__main__":
    problems = library.check_credentials()
    if problems:
        print("Configuration problems (names only, no values):")
        for p in problems:
            print(f"  - {p}")
        raise SystemExit(1)
    if BUNDLED:
        print(f"Serving the frozen bundle: {len(bundle.entries())} charts, no "
              f"Notion or Supabase on the request path.")
    else:
        print("Loading templates and building previews...")
        try:
            previews.warm(library.list_entries())
        except Exception as exc:                  # a cold library is not a crash
            print(f"  ! could not warm previews: {type(exc).__name__}: {exc}")
    print("Gallery on http://127.0.0.1:5111   (local only — exec() render path)")
    app.run(host="127.0.0.1", port=5111, debug=False, threaded=True)
