/* Parameter review: the distribution is the control, the number is a readout.
   Ported from the design canvas. No framework; one listener set per parameter. */
(function () {
  "use strict";
  var COLOURS = ["#86b6ef", "#3987e5", "#1c5cab"];
  var TINTS = ["rgba(134,182,239,.16)", "rgba(57,135,229,.15)", "rgba(28,92,171,.14)"];
  var LABELS = ["Category A", "Category B", "Category C"];

  function nice(v) {
    var a = Math.abs(v);
    if (a >= 1e6) return (v / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
    if (a >= 1e4) return Math.round(v).toLocaleString();
    if (a >= 100) return v.toFixed(0);
    return v.toFixed(a < 1 ? 3 : 2).replace(/0+$/, "").replace(/\.$/, "");
  }

  function setup(root) {
    var values = JSON.parse(root.dataset.values);
    var domain = JSON.parse(root.dataset.domain);
    var proposed = JSON.parse(root.dataset.proposed);
    var d0 = domain[0], d1 = domain[1];
    var edges = proposed.slice();
    var dragging = null;

    var strip = root.querySelector('[data-role="strip"]');
    var el = {
      regions: root.querySelector('[data-role="regions"]'),
      ghosts: root.querySelector('[data-role="ghosts"]'),
      dots: root.querySelector('[data-role="dots"]'),
      ticks: root.querySelector('[data-role="ticks"]'),
      handles: root.querySelector('[data-role="handles"]'),
      bins: root.querySelector('[data-role="bins"]'),
      edges: root.querySelector('[data-role="edges"]'),
      action: root.querySelector('[data-role="action"]'),
      chip: root.querySelector('[data-role="statechip"]'),
      reset: root.querySelector('[data-role="resetchip"]'),
      author: root.querySelector('[data-role="authorchip"]'),
      whyhead: root.querySelector('[data-role="whyhead"]'),
      reasons: root.querySelector('[data-role="reasons"]')
    };
    var baseReasons = Array.prototype.map.call(el.reasons.children, function (li) {
      return li.textContent;
    });

    function pct(v) { return ((v - d0) / (d1 - d0)) * 100; }
    function binOf(v) { return v < edges[0] ? 0 : (edges.length > 1 && v < edges[1] ? 1 : edges.length); }
    function dirty() {
      return edges.length !== proposed.length ||
        edges.some(function (e, i) { return Math.abs(e - proposed[i]) > 1e-9; });
    }

    function counts() {
      var c = new Array(edges.length + 1).fill(0);
      values.forEach(function (v) { c[binOf(v)] += 1; });
      return c;
    }

    function render() {
      var n = edges.length + 1, bounds = [d0].concat(edges, [d1]);

      el.regions.innerHTML = "";
      for (var i = 0; i < n; i++) {
        var r = document.createElement("div");
        r.className = "region";
        r.style.left = pct(bounds[i]) + "%";
        r.style.width = (pct(bounds[i + 1]) - pct(bounds[i])) + "%";
        r.style.background = TINTS[Math.min(i, TINTS.length - 1)];
        el.regions.appendChild(r);
      }

      var COLS = 46, colW = (d1 - d0) / COLS, stack = {};
      el.dots.innerHTML = "";
      values.forEach(function (v) {
        var c = Math.min(COLS - 1, Math.max(0, Math.floor((v - d0) / colW)));
        stack[c] = (stack[c] || 0) + 1;
        var dot = document.createElement("div");
        dot.className = "dot";
        dot.style.left = pct(d0 + (c + 0.5) * colW) + "%";
        dot.style.bottom = (44 + (stack[c] - 1) * 11) + "px";
        dot.style.background = COLOURS[Math.min(binOf(v), COLOURS.length - 1)];
        el.dots.appendChild(dot);
      });

      el.ghosts.innerHTML = "";
      if (dirty()) {
        proposed.forEach(function (v) {
          var g = document.createElement("div");
          g.className = "ghost"; g.style.left = pct(v) + "%";
          var lab = document.createElement("span");
          lab.className = "ghostlab"; lab.textContent = "proposed " + nice(v);
          g.appendChild(lab); el.ghosts.appendChild(g);
        });
      }

      // Edge labels are clamped rather than centred: a centred first/last tick is
      // half outside the clipped strip, which read as "02" instead of "9.02".
      el.ticks.innerHTML = "";
      for (var t = 0; t < 5; t++) {
        var tv = d0 + ((d1 - d0) * t) / 4;
        var tick = document.createElement("div");
        tick.className = "tick";
        tick.textContent = nice(tv);
        if (t === 0) { tick.style.left = "6px"; tick.style.transform = "none"; }
        else if (t === 4) { tick.style.right = "6px"; tick.style.transform = "none"; }
        else { tick.style.left = pct(tv) + "%"; }
        el.ticks.appendChild(tick);
      }

      el.handles.innerHTML = "";
      edges.forEach(function (v, i) {
        var hit = document.createElement("div");
        hit.className = "hhit"; hit.dataset.idx = String(i);
        hit.style.left = "calc(" + pct(v) + "% - 13px)";
        var line = document.createElement("div");
        line.className = "hline"; line.style.left = pct(v) + "%";
        var tag = document.createElement("div");
        tag.className = "htag"; tag.style.left = pct(v) + "%"; tag.textContent = nice(v);
        el.handles.appendChild(hit); el.handles.appendChild(line); el.handles.appendChild(tag);
      });

      var cs = counts(), total = values.length;
      el.bins.innerHTML = "";
      for (var b = 0; b < n; b++) {
        var card = document.createElement("div");
        card.className = "bincard" + (cs[b] === 0 ? " zero" : "");
        var range = b === 0 ? "below " + nice(edges[0])
          : (b === n - 1 ? nice(edges[edges.length - 1]) + " and above"
                         : nice(edges[b - 1]) + " to " + nice(edges[b]));
        card.innerHTML =
          '<div class="binh"><span class="sw" style="background:' +
          COLOURS[Math.min(b, COLOURS.length - 1)] + '"></span><span class="binlabel">' +
          (LABELS[b] || "Category " + (b + 1)) + "</span></div>" +
          '<p class="mono binrange">' + range + "</p>" +
          '<p class="bincount">' + (cs[b] === 0
            ? "no rows — an empty legend entry"
            : cs[b] + " of " + total) + "</p>";
        el.bins.appendChild(card);
      }

      el.edges.value = edges.join(",");
      var wasDirty = dirty();
      if (el.reset) el.reset.hidden = !wasDirty;
      if (el.author) el.author.hidden = !wasDirty;
      if (wasDirty) {
        el.action.value = "author";
        el.chip.textContent = "chosen by you";
        el.chip.className = "rstate authored";
        el.whyhead.textContent = "Why the system proposed " + proposed.map(nice).join(" and ");
        el.reasons.innerHTML = "";
        var head = document.createElement("li");
        head.className = "now";
        head.textContent = "You moved the boundaries to " + edges.map(nice).join(" and ") +
          ". Your bins hold [" + cs.join(", ") + "] against an even split of about " +
          Math.round(total / n) + " each.";
        el.reasons.appendChild(head);
        baseReasons.forEach(function (txt) {
          var li = document.createElement("li"); li.className = "past"; li.textContent = txt;
          el.reasons.appendChild(li);
        });
      }
    }

    function fromX(e) {
      var r = strip.getBoundingClientRect();
      var f = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
      return d0 + f * (d1 - d0);
    }
    function setEdge(i, raw) {
      var lo = i === 0 ? d0 : edges[i - 1] + (d1 - d0) * 0.02;
      var hi = i === edges.length - 1 ? d1 : edges[i + 1] - (d1 - d0) * 0.02;
      var span = d1 - d0;
      var dp = span >= 1e4 ? 0 : (span >= 100 ? 1 : 2);
      edges[i] = Number(Math.min(hi, Math.max(lo, raw)).toFixed(dp));
      render();
    }

    strip.addEventListener("pointerdown", function (e) {
      var idx = e.target && e.target.dataset ? e.target.dataset.idx : undefined;
      if (idx !== undefined) { dragging = Number(idx); }
      else {
        var v = fromX(e), best = 0, bd = Infinity;
        edges.forEach(function (ed, i) {
          var d = Math.abs(v - ed); if (d < bd) { bd = d; best = i; }
        });
        dragging = best; setEdge(best, v);
      }
      strip.setPointerCapture(e.pointerId);
    });
    strip.addEventListener("pointermove", function (e) {
      if (dragging !== null) setEdge(dragging, fromX(e));
    });
    ["pointerup", "pointercancel"].forEach(function (evt) {
      strip.addEventListener(evt, function () { dragging = null; });
    });

    root.querySelectorAll("[data-act]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        el.action.value = btn.dataset.act;
        root.querySelectorAll("[data-act]").forEach(function (b) { b.classList.remove("on"); });
        btn.classList.add("on");
        if (btn.dataset.act === "dismiss") {
          el.chip.textContent = "dismissed — not a measure";
          el.chip.className = "rstate rejected";
        } else if (btn.dataset.act === "confirm") {
          el.chip.textContent = "confirmed by you";
          el.chip.className = "rstate confirmed";
        }
      });
    });
    if (el.reset) {
      el.reset.addEventListener("click", function () {
        edges = proposed.slice();
        el.chip.textContent = "chosen by automation, not reviewed";
        el.chip.className = "rstate unreviewed";
        el.action.value = "confirm";
        el.whyhead.textContent = "Why these values";
        el.reasons.innerHTML = "";
        baseReasons.forEach(function (txt) {
          var li = document.createElement("li"); li.textContent = txt; el.reasons.appendChild(li);
        });
        render();
      });
    }
    render();
  }

  document.querySelectorAll(".param[data-values]").forEach(setup);
})();
