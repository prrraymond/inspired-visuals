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
  function draw(figure) {
    if (!figure) return;
    const layout = Object.assign({}, figure.layout, { autosize: true });
    // The template fixes a width so its PNG export is deterministic. On screen
    // that would letterbox the chart inside the panel, so the width is dropped
    // and only here -- the stored template is not touched.
    delete layout.width;
    Plotly.react(el.chart, figure.data, layout, {
      responsive: true,
      displayModeBar: false,
      scrollZoom: false,
    });
  }

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
    if (!notes.length) { el.notes.innerHTML = ""; return; }
    el.notes.innerHTML = notes.map((n) =>
      '<div class="note ' + esc(n.level) + '">' +
      "<p>" + esc(n.message) + "</p>" +
      (n.hint ? '<p class="note-hint">' + esc(n.hint) + "</p>" : "") +
      (n.fix && n.fix.kind === "rename"
        ? '<button type="button" class="btn tiny" data-rename-from="' + esc(n.fix.from) +
          '" data-rename-to="' + esc(n.fix.to) + '">Rename “' + esc(n.fix.from) +
          '” to “' + esc(n.fix.to) + '”</button>' : "") +
      "</div>").join("");
  }

  el.notes.addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-rename-from]");
    if (!btn) return;
    const i = state.columns.indexOf(btn.dataset.renameFrom);
    if (i < 0) return;
    state.columns[i] = btn.dataset.renameTo;
    renderGrid();
    redraw();
  });

  // --------------------------------------------------------------- replace ---
  const dialog = document.getElementById("replace");
  document.getElementById("open-replace").addEventListener("click", () => dialog.showModal());
  dialog.addEventListener("close", () => {
    if (dialog.returnValue !== "use") return;
    const text = document.getElementById("paste").value;
    fetch("/api/parse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text }),
    })
      .then((r) => r.json())
      .then((res) => {
        if (!res.ok) { alertInline(res.problem); return; }
        state.columns = res.grid.columns;
        state.kinds = res.grid.kinds;
        state.rows = res.grid.rows;
        renderGrid();
        redraw();
      });
  });

  function alertInline(msg) {
    el.notes.innerHTML = '<div class="note error"><p>' + esc(msg) + "</p></div>";
  }

  // ----------------------------------------------------------------- needs ---
  function renderNeeds() {
    el.needs.innerHTML = pristine.columns.map((c, i) =>
      "<li><code>" + esc(c) + "</code><span>" +
      esc(KIND_LABELS[pristine.kinds[i]] || pristine.kinds[i]) + "</span></li>").join("");
  }

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
  showResult(boot);
})();
