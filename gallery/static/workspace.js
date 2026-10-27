/*
 * The workspace: one chart, the rows behind it, and the words on it.
 *
 * The working dataset lives HERE, in the page, and travels with every render
 * request. There is no run id and nothing server-side to expire, so a reload is
 * the only thing that ends a session -- and it ends it cleanly.
 *
 * The chart is drawn from Plotly figure JSON rather than a PNG: the same server
 * round-trip either way, but the result has hover values and no image flicker
 * between edits.
 */
(function () {
  "use strict";

  // Map geometry comes from this app, not cdn.plot.ly -- see the topojson route.
  Plotly.setPlotConfig({ topojsonURL: "/vendor/topojson/" });

  const boot = JSON.parse(document.getElementById("bootstrap").textContent);
  const CHART_ID = window.CHART_ID;

  const state = {
    columns: boot.grid.columns.slice(),
    kinds: boot.grid.kinds.slice(),
    rows: boot.grid.rows.map((r) => r.slice()),
    captions: Object.assign({}, boot.captions),
    settings: { controls: {} },
    slots: boot.caption_slots.slice(),
    settingsSpec: boot.settings.slice(),
    controls: boot.controls.slice(),
    roles: (boot.roles || []).slice(),
    // Only what the person changed. The template's own look is boot.format's
    // defaults, so an empty object here IS the default, and Reset is `{}`.
    format: { colors: {} },
    formatSpec: boot.format || null,
    // The last paste, kept so the header decision can be flipped without
    // asking for the data again.
    paste: null,
    binding: null,
  };
  const pristine = JSON.parse(JSON.stringify({ columns: state.columns, kinds: state.kinds, rows: state.rows }));

  const el = {
    chart: document.getElementById("chart"),
    problem: document.getElementById("chart-problem"),
    chartState: document.getElementById("chart-state"),
    grid: document.getElementById("grid"),
    dataCount: document.getElementById("data-count"),
    notes: document.getElementById("notes"),
    captions: document.getElementById("captions"),
    settingsPanel: document.getElementById("settings-panel"),
    settings: document.getElementById("settings"),
    needs: document.getElementById("needs"),
    log: document.getElementById("log"),
  };

  // Reading order on the chart, not alphabetical order in a set.
  const KIND_LABELS = { number: "number", date: "date", text: "text", boolean: "yes / no" };

  const CAPTION_ORDER = ["title", "subtitle", "units", "above", "below", "source"];
  const CAPTION_LABELS = {
    title: "Title",
    subtitle: "Subtitle",
    units: "Units",
    source: "Source",
    above: "Label above the baseline",
    below: "Label below the baseline",
  };

  // ---------------------------------------------------------------- chart ---
  let lastFigure = null;
  let drawSeq = 0;

  function draw(figure) {
    if (!figure) return;
    lastFigure = figure;
    wraps = {};
    const seq = ++drawSeq;
    const layout = JSON.parse(JSON.stringify(figure.layout || {}));
    layout.autosize = true;
    // The template fixes a width so its PNG export is deterministic. On screen
    // that would letterbox the chart inside the panel, so the width is dropped
    // and only here -- the stored template is not touched.
    delete layout.width;
    Plotly.react(el.chart, figure.data, layout, {
      responsive: true,
      displayModeBar: false,
      scrollZoom: false,
    }).then(() => fit(el.chart, seq));
  }

  // ------------------------------------------------------------------ fit ---
  // Templates fix their margins and height, and Plotly does not wrap text, so a
  // longer subtitle ran off the right edge and a second line ran into the plot
  // (PRD R15). This measures what was actually drawn -- not an estimate from
  // character counts -- wraps any line wider than its space, then grows the
  // margins until every piece of text is inside the figure. The plot area keeps
  // its size; the figure gets taller. Downloads are taken from the fitted figure.
  const PAD = 8;
  const BR = /<br\s*\/?>/i;

  function wrapLine(seg, budget) {
    // Break at spaces only, never inside markup: tags cost nothing, an entity
    // costs one character, and a word longer than the budget stays whole.
    const parts = seg.split(/(<[^>]*>|&[#\w]+;|\s+)/).filter((x) => x !== "");
    let out = "", len = 0, gap = "";
    for (const part of parts) {
      if (/^\s+$/.test(part)) { gap = len ? " " : gap; continue; }
      if (part[0] === "<") { out += gap ? gap : ""; gap = ""; out += part; continue; }
      const w = part[0] === "&" ? 1 : part.length;
      if (gap && len && len + 1 + w > budget) { out += "<br>"; len = 0; }
      else if (gap) { out += gap; len += 1; }
      gap = "";
      out += part; len += w;
    }
    return out;
  }

  function visibleLength(seg) {
    return seg.replace(/<[^>]*>/g, "").replace(/&[#\w]+;/g, "x").length;
  }

  // What each text looked like before fitting, and how many drawn lines each
  // of its own <br>-separated segments became. Rewrapping always reflows from
  // the original: wrapping the already-wrapped text again, when a later pass
  // narrowed its space, left single words stranded on lines of their own.
  let wraps = {};

  // Rewrap the text at `key` so each drawn line fits in `room` px. `lineEls`
  // are the drawn lines, in order. Returns the new text, or null if it fits.
  function rewrap(key, text, lineEls, room) {
    if (!wraps[key]) {
      const segs = String(text).split(BR);
      wraps[key] = { segs: segs, counts: segs.map(() => 1) };
    }
    const w = wraps[key];
    if (w.counts.reduce((x, y) => x + y, 0) !== lineEls.length) return null;
    let changed = false, at = 0;
    const out = w.segs.map((seg, i) => {
      const mine = lineEls.slice(at, at + w.counts[i]);
      at += w.counts[i];
      const widths = mine.map((l) => l.getBoundingClientRect().width);
      const current = String(text).split(BR).slice(at - w.counts[i], at).join("<br>");
      if (Math.max(...widths) <= room) return current;
      // Width per character, measured on this segment's own drawn lines.
      const perChar = widths.reduce((x, y) => x + y, 0) / Math.max(1, visibleLength(seg));
      const budget = Math.max(8, Math.floor(room / perChar * 0.97));
      const wrapped = wrapLine(seg, budget);
      w.counts[i] = wrapped.split(BR).length;
      if (wrapped !== current) changed = true;
      return wrapped;
    });
    return changed ? out.join("<br>") : null;
  }

  function lines(textEl) {
    const ls = textEl.querySelectorAll("tspan.line");
    return ls.length ? Array.from(ls) : [textEl];
  }

  // Annotations that share a row -- the "← lower · axis label · higher →" line
  // under an axis -- may not each take the full width: wrapped independently,
  // every one of them fitted the figure and they overprinted. Each gets the
  // space between its own anchor and the midpoint to its neighbour's.
  function rowBounds(gd, box, W) {
    const anns = gd.layout.annotations || [];
    const rows = {};
    gd.querySelectorAll(".annotation").forEach((node) => {
      const i = +node.getAttribute("data-index");
      const a = anns[i];
      const t = node.querySelector(".annotation-text-g text");
      if (!a || !t || !String(a.yref || "y").startsWith("paper")) return;
      const r = t.getBoundingClientRect();
      const l = r.left - box.left, rt = r.right - box.left;
      const anchor = a.xanchor === "left" || a.xanchor === "right" ? a.xanchor : "center";
      const at = anchor === "left" ? l : anchor === "right" ? rt : (l + rt) / 2;
      const key = [a.y, a.yref, a.yshift || 0].join("|");
      (rows[key] = rows[key] || []).push({ i, at });
    });
    const bounds = {};
    Object.values(rows).forEach((row) => {
      row.sort((p, q) => p.at - q.at);
      row.forEach((m, k) => {
        bounds[m.i] = [
          k ? (row[k - 1].at + m.at) / 2 + 8 : PAD,
          k < row.length - 1 ? (m.at + row[k + 1].at) / 2 - 8 : W - PAD,
        ];
      });
    });
    return bounds;
  }

  function textRects(gd, box, skip) {
    const out = [];
    gd.querySelectorAll(".main-svg text").forEach((t) => {
      if (!t.textContent.trim() || (skip && skip.contains(t))) return;
      const r = t.getBoundingClientRect();
      if (!r.height) return;
      out.push({ top: r.top - box.top, bottom: r.bottom - box.top,
                 left: r.left - box.left, right: r.right - box.left });
    });
    return out;
  }

  async function fit(gd, seq) {
    for (let pass = 0; pass < 10; pass++) {
      if (seq !== drawSeq || !gd._fullLayout) return;
      const full = gd._fullLayout;
      const W = full.width, H = full.height;
      const box = gd.getBoundingClientRect();
      const update = {};

      // 1. too long for its space: wrap
      const title = gd.querySelector(".infolayer .gtitle");
      const titleText = full.title && full.title.text;
      if (title && titleText) {
        const r = title.getBoundingClientRect();
        const room = W - PAD - Math.max(r.left - box.left, PAD);
        const next = rewrap("title.text", titleText, lines(title), room);
        if (next) update["title.text"] = next;
      }
      const bounds = rowBounds(gd, box, W);
      gd.querySelectorAll(".annotation").forEach((node) => {
        const i = +node.getAttribute("data-index");
        const a = (gd.layout.annotations || [])[i];
        const textEl = node.querySelector(".annotation-text-g text");
        // Any annotation, wherever it is anchored: a diverging chart's statement
        // labels sit at the data and are exactly the text a person makes long.
        if (!a || !textEl || !a.text) return;
        const r = textEl.getBoundingClientRect();
        const left = r.left - box.left, right = r.right - box.left;
        const [lo, hi] = bounds[i] || [PAD, W - PAD];
        const anchor = a.xanchor || "center";
        const room = anchor === "left" ? hi - left
          : anchor === "right" ? right - lo
            : 2 * Math.min((left + right) / 2 - lo, hi - (left + right) / 2);
        const next = rewrap("annotations[" + i + "].text", a.text, lines(textEl), room);
        if (!next) return;
        update["annotations[" + i + "].text"] = next;
        // Grow away from the plot: text above it upward, text below it downward.
        // Left centred on its anchor, a wrapped line pushed into the ticks or
        // the legend, where no margin can make room for it.
        const paperY = String(a.yref || "y").startsWith("paper");
        if (paperY && (!a.yanchor || a.yanchor === "auto" || a.yanchor === "middle")) {
          if (a.y >= 1) update["annotations[" + i + "].yanchor"] = "bottom";
          else if (a.y <= 0) update["annotations[" + i + "].yanchor"] = "top";
        }
      });
      // Axis titles: a rotated y title longer than the plot ran into the title.
      [["y", ".g-ytitle text", full._size.h], ["x", ".g-xtitle text", full._size.w]]
        .forEach(([ax, sel, span]) => {
          const t = gd.querySelector(sel);
          const axis = full[ax + "axis"];
          const text = axis && axis.title && axis.title.text;
          if (!t || !text) return;
          // Measured along the text, whichever way it is turned.
          const along = lines(t).map((l) => ({ getBoundingClientRect: () => {
            const rr = l.getBoundingClientRect();
            return { width: ax === "y" ? rr.height : rr.width };
          } }));
          const next = rewrap(ax + "axis.title.text", text, along, span);
          if (next) update[ax + "axis.title.text"] = next;
        });
      if (Object.keys(update).length) {
        await Plotly.relayout(gd, update);
        continue;
      }

      // 1b. stacked annotations in the same margin: when one wraps into the
      // next, move the one farther from the plot further away. The margin then
      // grows to hold it in step 3.
      const plotTop = full._size.t, plotBottom = full._size.t + full._size.h;
      const ann = [];
      gd.querySelectorAll(".annotation").forEach((node) => {
        const i = +node.getAttribute("data-index");
        const a = (gd.layout.annotations || [])[i];
        const t = node.querySelector(".annotation-text-g text");
        if (!a || !t || !String(a.yref || "y").startsWith("paper")) return;
        const r = t.getBoundingClientRect();
        const q = { i, a, top: r.top - box.top, bottom: r.bottom - box.top,
                    left: r.left - box.left, right: r.right - box.left };
        q.side = q.bottom <= plotTop + 2 ? "above" : q.top >= plotBottom - 2 ? "below" : null;
        if (q.side) ann.push(q);
      });
      ann.forEach((p) => ann.forEach((q) => {
        if (p === q || p.side !== q.side || update["annotations[" + q.i + "].yshift"] !== undefined) return;
        const w = Math.min(p.right, q.right) - Math.max(p.left, q.left);
        const h = Math.min(p.bottom, q.bottom) - Math.max(p.top, q.top);
        if (w <= 2 || h <= 2) return;
        // q is the farther one from the plot
        const farther = q.side === "below" ? q.top > p.top : q.bottom < p.bottom;
        if (!farther) return;
        const d = Math.ceil(h + 4) * (q.side === "below" ? -1 : 1);
        update["annotations[" + q.i + "].yshift"] = (q.a.yshift || 0) + d;
      }));
      if (Object.keys(update).length) {
        await Plotly.relayout(gd, update);
        continue;
      }

      // 2. the title: inside the top edge, and clear of whatever sits under it
      const m = full.margin;
      const relayout = {};
      let grow = 0;
      const pinned = full.title && full.title.yref === "container" && full.title.yanchor === "top";
      // Pinned, the title keeps its distance from the top edge in pixels, which
      // as a fraction of the height changes every time the figure grows.
      let titleOffset = pinned ? (1 - full.title.y) * H : null;
      if (title) {
        const r = title.getBoundingClientRect();
        const tTop = r.top - box.top, tBottom = r.bottom - box.top;
        if (tTop < PAD) {
          titleOffset = (titleOffset === null ? PAD : titleOffset + (PAD - tTop));
        }
        const below = textRects(gd, box, title).filter((q) =>
          q.top < full._size.t && q.top > tTop && q.right > r.left - box.left &&
          q.left < r.right - box.left);
        const limit = Math.min(full._size.t, ...below.map((q) => q.top)) - 6;
        if (tBottom > limit) {
          const d = Math.ceil(tBottom - limit);
          relayout["margin.t"] = m.t + d;
          grow += d;
          if (titleOffset === null) titleOffset = Math.max(PAD, tTop);
        }
      }

      // 3. everything else: grow the margin on whichever side it overflows
      const rects = textRects(gd, box, title);
      const top = Math.min(...rects.map((q) => q.top));
      const bottom = Math.max(...rects.map((q) => q.bottom));
      const lo = Math.min(...rects.map((q) => q.left));
      const hi = Math.max(...rects.map((q) => q.right));
      if (top < PAD) {
        const d = Math.ceil(PAD - top);
        relayout["margin.t"] = (relayout["margin.t"] || m.t) + d;
        grow += d;
      }
      if (bottom > H - PAD) {
        const d = Math.ceil(bottom - (H - PAD));
        relayout["margin.b"] = m.b + d;
        grow += d;
      }
      if (lo < PAD) relayout["margin.l"] = m.l + Math.ceil(PAD - lo);
      if (hi > W - PAD) relayout["margin.r"] = m.r + Math.ceil(hi - (W - PAD));

      const moveTitle = titleOffset !== null &&
        (!pinned || grow || Math.abs(titleOffset - (1 - full.title.y) * H) > 0.5);
      if (moveTitle) {
        Object.assign(relayout, { "title.yref": "container", "title.yanchor": "top",
                                  "title.y": 1 - titleOffset / (H + grow) });
      }
      if (!Object.keys(relayout).length) return;
      if (grow) relayout.height = H + grow;
      await Plotly.relayout(gd, relayout);
    }
  }

  window.addEventListener("resize", debounce(() => draw(lastFigure), 200));

  // -------------------------------------------------------------- download ---
  function download(format) {
    const full = el.chart._fullLayout;
    if (!full || el.chart.hidden) return;
    const name = (state.captions.title || CHART_ID).toLowerCase()
      .replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || CHART_ID;
    // The size on screen, after fitting: what is downloaded is what was seen.
    Plotly.downloadImage(el.chart, {
      format: format, filename: name, width: full.width, height: full.height,
      scale: format === "png" ? 2 : 1,
    });
  }
  document.getElementById("download-png").addEventListener("click", () => download("png"));
  document.getElementById("download-svg").addEventListener("click", () => download("svg"));

  function showResult(res) {
    el.problem.hidden = res.ok;
    el.chart.hidden = !res.ok;
    if (res.ok) {
      draw(res.figure);
      el.chartState.textContent = "";
    } else {
      el.problem.innerHTML =
        '<p class="refusal-h">This didn’t draw.</p>' +
        "<ul>" + (res.problems || []).map((p) => "<li>" + esc(p) + "</li>").join("") + "</ul>";
      el.chartState.textContent = "not drawn";
    }
    if (res.settings || res.controls) {
      if (res.settings) state.settingsSpec = res.settings;
      if (res.controls) state.controls = res.controls;
      renderSettings();
    }
    if (res.caption_slots && res.caption_slots.length) {
      state.slots = res.caption_slots;
    }
    if (res.format) {
      state.formatSpec = res.format;
      renderFormat();
    }
    if (res.binding) state.binding = res.binding;
    if (el.log) el.log.textContent = (res.log || []).join("\n");
    renderNotes(res.notes || []);
  }

  // ------------------------------------------------------------- requests ---
  let pending = null;
  let inflight = false;

  function redraw() {
    if (inflight) { pending = true; return; }
    inflight = true;
    el.chartState.textContent = "updating…";
    fetch("/api/render/" + encodeURIComponent(CHART_ID), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        columns: state.columns,
        rows: state.rows,
        captions: state.captions,
        settings: state.settings,
        format: state.format,
      }),
    })
      .then((r) => r.json())
      .then(showResult)
      .catch((e) => showResult({ ok: false, problems: [String(e)] }))
      .finally(() => {
        inflight = false;
        if (pending) { pending = false; redraw(); }
      });
  }

  const debounced = debounce(redraw, 220);

  // ----------------------------------------------------------------- grid ---
  function renderGrid() {
    const head = el.grid.tHead;
    // The header has to sit over its own values. Numbers are right-aligned, so a
    // left-aligned heading floated away from the column it names -- across a wide
    // column the two looked unrelated.
    head.innerHTML =
      "<tr>" +
      state.columns.map((c, i) =>
        '<th class="k-' + esc(state.kinds[i] || "text") + '">' +
        '<span class="col-name">' + esc(c) + "</span>" +
        '<span class="col-kind">' + esc(KIND_LABELS[state.kinds[i]] || state.kinds[i] || "") +
        "</span></th>").join("") +
      "<th class='row-tools'></th></tr>";

    const body = el.grid.tBodies[0];
    body.innerHTML = state.rows.map((row, r) =>
      "<tr>" +
      row.map((v, c) =>
        '<td class="k-' + esc(state.kinds[c] || "text") + '">' +
        '<input value="' + esc(v === null || v === undefined ? "" : v) +
        '" data-r="' + r + '" data-c="' + c + '" spellcheck="false"></td>').join("") +
      '<td class="row-tools"><button type="button" class="rm" data-rm="' + r +
      '" title="Remove this row">&times;</button></td>' +
      "</tr>").join("");

    el.dataCount.textContent =
      state.rows.length + (state.rows.length === 1 ? " row" : " rows") +
      " · " + state.columns.length + " columns";
  }

  el.grid.addEventListener("input", (ev) => {
    const t = ev.target;
    if (t.tagName !== "INPUT") return;
    const r = +t.dataset.r, c = +t.dataset.c;
    state.rows[r][c] = t.value === "" ? null : t.value;
    debounced();
  });

  el.grid.addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-rm]");
    if (!btn) return;
    state.rows.splice(+btn.dataset.rm, 1);
    renderGrid();
    redraw();
  });

  document.getElementById("add-row").addEventListener("click", () => {
    state.rows.push(state.columns.map(() => null));
    renderGrid();
    const last = el.grid.querySelector("tbody tr:last-child input");
    if (last) last.focus();
  });

  document.getElementById("reset-data").addEventListener("click", () => {
    state.columns = pristine.columns.slice();
    state.kinds = pristine.kinds.slice();
    state.rows = pristine.rows.map((r) => r.slice());
    state.paste = null;
    renderGrid();
    redraw();
  });

  // -------------------------------------------------------------- captions ---
  function renderCaptions() {
    const slots = state.slots.slice().sort(
      (a, b) => (CAPTION_ORDER.indexOf(a) + 1 || 99) - (CAPTION_ORDER.indexOf(b) + 1 || 99));
    el.captions.innerHTML = slots.map((role) =>
      '<label class="field"><span>' + esc(CAPTION_LABELS[role] || role) + "</span>" +
      '<input data-caption="' + esc(role) + '" value="' +
      esc(state.captions[role] || "") + '" spellcheck="false"></label>').join("");
  }

  el.captions.addEventListener("input", (ev) => {
    const role = ev.target.dataset.caption;
    if (!role) return;
    state.captions[role] = ev.target.value;
    debounced();
  });

  // -------------------------------------------------------------- settings ---
  function renderControls() {
    // A control always shows the value the chart was actually drawn with, and
    // says whether that value came from a person or from the app.
    return (state.controls || []).map((c) => {
      const badge = c.by_person
        ? '<p class="chosen by-you">Set by you.</p>'
        : '<p class="chosen">Chosen automatically — adjust if needed.</p>';
      const problem = c.problem
        ? '<p class="chosen warn">' + esc(c.problem) + "</p>" : "";
      return '<div class="setting">' + badge + problem +
        '<label class="field"><span>' + esc(c.label) + "</span>" +
        '<input data-control="' + esc(c.const) + '" value="' + esc(c.value) +
        '" spellcheck="false"></label>' +
        (c.help ? '<p class="setting-help">' + esc(c.help) + "</p>" : "") +
        "</div>";
    }).join("");
  }

  function renderSettings() {
    const specs = state.settingsSpec || [];
    const usable = specs.filter((s) => s.uses_edges || s.uses_baseline);
    const controls = renderControls();
    el.settingsPanel.hidden = usable.length === 0 && !controls;
    el.settings.innerHTML = controls + usable.map((s) => {
      let body = "";
      if (s.uses_edges) {
        body +=
          '<label class="field"><span>Value ranges split at</span>' +
          '<input data-setting="edges" data-column="' + esc(s.column) + '" value="' +
          esc((s.edges || []).join(", ")) + '" spellcheck="false"></label>' +
          '<ul class="ranges">' + (s.ranges || []).map((r, i) =>
            "<li><span>" + esc(r) + "</span><span class='n'>" +
            (s.occupancy ? s.occupancy[i] + " rows" : "") + "</span></li>").join("") + "</ul>";
      }
      if (s.uses_baseline) {
        body +=
          '<label class="field"><span>Baseline</span>' +
          '<input data-setting="baseline" data-column="' + esc(s.column) + '" value="' +
          esc(s.baseline === null || s.baseline === undefined ? "" : s.baseline) + '"></label>';
      }
      // Never "confirmed", never "accepted". A value that has drawn a hundred
      // charts is still a value nobody has looked at.
      const badge = s.reviewed
        ? '<p class="chosen by-you">Set by you.</p>'
        : '<p class="chosen">Chosen automatically — adjust if needed.</p>';
      const warn = (s.warnings || []).length
        ? '<p class="chosen warn">' + esc(s.warnings.join("; ")) + "</p>" : "";
      return '<div class="setting">' + badge + warn + body + "</div>";
    }).join("");
  }

  el.settings.addEventListener("input", debounce((ev) => {
    const control = ev.target.dataset.control;
    if (control) {
      state.settings.controls[control] = ev.target.value;
      redraw();
      return;
    }
    const kind = ev.target.dataset.setting;
    if (!kind) return;
    if (kind === "edges") {
      const nums = ev.target.value.split(",")
        .map((x) => parseFloat(x.trim())).filter((x) => !isNaN(x));
      state.settings.edges = nums.length ? nums : undefined;
    } else if (kind === "baseline") {
      const v = parseFloat(ev.target.value);
      state.settings.baseline = isNaN(v) ? undefined : v;
    }
    redraw();
  }, 320));

  // ----------------------------------------------------------------- notes ---
  function renderNotes(notes) {
    el.notes.innerHTML = bindingNotice() + notes.map((n) =>
      '<div class="note ' + esc(n.level) + '">' +
      "<p>" + esc(n.message) + "</p>" +
      (n.hint ? '<p class="note-hint">' + esc(n.hint) + "</p>" : "") +
      "</div>").join("");
  }

  // After every replace, say exactly what was used for what (PRD R14). Columns
  // are bound by order, so two number columns in the wrong order draw a valid,
  // wrong chart -- this notice is the only thing that catches it, which is why
  // it appears every time and not only when something failed.
  function bindingNotice() {
    if (!state.paste || !state.binding) return "";
    const b = state.binding;
    const used = b.roles.map((r) =>
      "<li><b>" + esc(r.label) + "</b> ← " +
      (r.column === null
        ? (r.optional ? "<i>not provided (optional)</i>" : "<i>missing</i>")
        : "column " + r.position + ", “" + esc(r.column) + "”") + "</li>").join("");
    const ignored = b.ignored.length
      ? "<p class='note-hint'>Not used by this chart: " +
        b.ignored.map((c) => "column " + c.position + ", “" + esc(c.column) + "”").join("; ") +
        ".</p>" : "";
    const header = state.paste.header
      ? "The first row was read as column names."
      : "The first row was read as data — there was no header row.";
    const flip = state.paste.header ? "First row is data" : "First row is column names";
    return '<div class="note info binding">' +
      "<p>Using your columns in order:</p><ul>" + used + "</ul>" + ignored +
      "<p class='note-hint'>" + header + " If a column is in the wrong place, reorder " +
      "your data and replace it again.</p>" +
      '<button type="button" class="btn tiny" id="flip-header">' + flip + "</button></div>";
  }

  el.notes.addEventListener("click", (ev) => {
    if (!ev.target.closest("#flip-header") || !state.paste) return;
    parsePaste(state.paste.text, !state.paste.header);
  });

  // --------------------------------------------------------------- replace ---
  const dialog = document.getElementById("replace");
  document.getElementById("open-replace").addEventListener("click", () => dialog.showModal());
  dialog.addEventListener("close", () => {
    if (dialog.returnValue !== "use") return;
    parsePaste(document.getElementById("paste").value, null);
  });

  // `header` null lets the server decide; true/false is the person overriding it.
  function parsePaste(text, header) {
    fetch("/api/parse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text, header: header }),
    })
      .then((r) => r.json())
      .then((res) => {
        if (!res.ok) { alertInline(res.problem); return; }
        state.paste = { text: text, header: res.header };
        state.columns = res.grid.columns;
        state.kinds = res.grid.kinds;
        state.rows = res.grid.rows;
        renderGrid();
        redraw();
      });
  }

  function alertInline(msg) {
    el.notes.innerHTML = '<div class="note error"><p>' + esc(msg) + "</p></div>";
  }

  // ----------------------------------------------------------------- needs ---
  function renderNeeds() {
    const roles = state.roles.length ? state.roles : pristine.columns.map((c, i) =>
      ({ position: i + 1, label: c, kind: pristine.kinds[i], optional: false }));
    el.needs.innerHTML = roles.map((r) =>
      "<li><span class='pos'>" + r.position + "</span><b>" + esc(r.label) + "</b>" +
      "<span>" + esc(KIND_LABELS[r.kind] || r.kind) +
      (r.optional ? " · optional" : "") + "</span></li>").join("");
  }

  // ---------------------------------------------------------------- format ---
  // Defaults come from the figure the template drew (PRD R13); this only keeps
  // what the person changed, so "Reset" is clearing it.
  const fmtPanel = document.getElementById("format-panel");

  function renderFormat() {
    const spec = state.formatSpec;
    if (!spec) { fmtPanel.hidden = true; return; }
    const d = spec.defaults, f = state.format;
    const val = (k) => (f[k] !== undefined && f[k] !== "" ? f[k] : d[k]);
    document.getElementById("format-colors").innerHTML = (spec.colors || []).map((c) =>
      '<label class="field swatch"><span>' + esc(c.label) + "</span>" +
      '<input type="color" data-color="' + esc(c.key) + '" value="' +
      esc(f.colors[c.key] || c.default) + '"></label>').join("");
    fmtPanel.querySelectorAll("[data-format]").forEach((input) => {
      const k = input.dataset.format;
      if (document.activeElement === input) return;     // don't fight the typist
      if (k === "font_family") {
        input.innerHTML = (spec.fonts || []).map((n) =>
          '<option value="' + esc(n) + '"' + (n === val(k) ? " selected" : "") + ">" +
          esc(n) + "</option>").join("");
      } else if (val(k) !== null && val(k) !== undefined) {
        input.value = val(k);
      }
    });
    // Nothing to colour, nothing to offer.
    document.getElementById("f-label-row").hidden = !d.label_color;
    document.getElementById("f-grid-row").hidden = !d.grid_color;
  }

  fmtPanel.addEventListener("input", (ev) => {
    const t = ev.target;
    if (t.dataset.color) state.format.colors[t.dataset.color] = t.value;
    else if (t.dataset.format) state.format[t.dataset.format] = t.value;
    else return;
    debounced();
  });

  document.getElementById("reset-format").addEventListener("click", () => {
    state.format = { colors: {} };
    renderFormat();
    redraw();
  });

  // ------------------------------------------------------------------ util ---
  function esc(s) {
    return String(s === null || s === undefined ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function debounce(fn, ms) {
    let t;
    return function () {
      const args = arguments, self = this;
      clearTimeout(t);
      t = setTimeout(() => fn.apply(self, args), ms);
    };
  }

  // ------------------------------------------------------------------ boot ---
  renderGrid();
  renderCaptions();
  renderSettings();
  renderNeeds();
  renderFormat();
  showResult(boot);
})();
