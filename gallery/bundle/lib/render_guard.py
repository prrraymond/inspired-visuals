#!/usr/bin/env python3
"""
Render preconditions, derived from the data contract.

This runs BEFORE build_figure, not as a report afterward. Every check here exists
because the corresponding failure was observed on a real chart:

  * required columns  -- CHT-6FBD47's regenerated template needed a pre-binned
                         `category` column and raised KeyError at render time.
  * null profile      -- station_daily.ridership_proxy is 100% NULL; a chart built
                         on it renders empty rather than failing.
  * parameter ranges  -- CHT-85FB02 ships BASELINE=100 against values of 12.5-17.7.
                         It rendered a structurally perfect, semantically dead chart:
                         66 identical bars. Nothing but this check catches that.

`derive_parameters` closes the loop: instead of only rejecting thresholds that do
not fit, propose ones that do, from the contract's own quantiles.
"""
from __future__ import annotations
import math
from typing import Sequence

from data_contract import column, validate_bins, required_columns_present


class ContractViolation(Exception):
    """Raised when a dataset cannot safely drive a template. Carries every problem."""

    def __init__(self, chart: str | None, problems: list[str]):
        self.chart = chart
        self.problems = problems
        head = f"{chart}: " if chart else ""
        super().__init__(head + f"{len(problems)} contract violation(s):\n  - " + "\n  - ".join(problems))


# --------------------------------------------------------------------------- #
# VETO
# --------------------------------------------------------------------------- #
def check_render(
    contract: dict,
    *,
    required: Sequence[str] = (),
    value_column: str | None = None,
    bin_edges: Sequence[float] | None = None,
    baseline: float | None = None,
    max_facets: int | None = None,
    facet_column: str | None = None,
    allow_partial_last_period: bool = True,
    temporal_column: str | None = None,
) -> None:
    """
    Raise ContractViolation if the dataset cannot safely drive the template.
    Returns None when everything passes. Collects ALL problems before raising, so
    one run reports every incompatibility rather than the first.
    """
    problems: list[str] = []

    missing = required_columns_present(contract, list(required))
    if missing:
        have = [c["name"] for c in contract["columns"]]
        problems.append(f"required column(s) {missing} absent; dataset provides {have}")

    # A column that exists but is entirely null renders an empty chart, not an error.
    for c in contract["columns"]:
        if c["all_null"] and c["name"] in set(required):
            problems.append(f"required column {c['name']!r} is 100% NULL ({c['nulls']} rows)")

    if value_column and bin_edges is not None:
        problems += validate_bins(contract, value_column, list(bin_edges))

    if value_column and baseline is not None:
        c = column(contract, value_column)
        if c and c["kind"] == "numeric" and not c["all_null"]:
            lo, hi = c["stats"]["min"], c["stats"]["max"]
            if baseline > hi:
                problems.append(
                    f"baseline {baseline} is above the data maximum ({hi}); every value falls on "
                    f"one side of it and the chart reads as uniform")
            elif baseline < lo:
                problems.append(
                    f"baseline {baseline} is below the data minimum ({lo}); every value falls on "
                    f"one side of it and the chart reads as uniform")

    if facet_column and max_facets is not None:
        c = column(contract, facet_column)
        if c and c["distinct"] > max_facets:
            problems.append(
                f"facet column {facet_column!r} has {c['distinct']} distinct values but the layout "
                f"supports {max_facets}")

    if temporal_column and not allow_partial_last_period:
        c = column(contract, temporal_column)
        if c and c["kind"] == "temporal":
            problems.append(
                f"partial-period check requested for {temporal_column!r}; verify the final period "
                f"is complete before publishing")

    if problems:
        raise ContractViolation(contract.get("name"), problems)


def render_guarded(build_figure, df, contract: dict, **checks):
    """check_render() then build_figure(df). The guard cannot be skipped by accident."""
    check_render(contract, **checks)
    return build_figure(df)


# --------------------------------------------------------------------------- #
# DERIVATION
# --------------------------------------------------------------------------- #
def _nice(x: float, data_range: float) -> float:
    """
    Round a threshold to a human-looking number at a precision the range justifies.

    The grid must be fine enough not to move the threshold materially: an earlier
    version targeted ~6 steps across the range, which snapped a quartile of 12.686
    to 12.0 and turned a balanced split into 9/39/7. Target 8-25 steps instead, so
    the rounding is cosmetic rather than semantic.
    """
    if data_range <= 0 or not math.isfinite(data_range):
        return round(x, 2)
    base = 10 ** math.floor(math.log10(data_range))
    step = base
    for cand in (base / 100, base / 50, base / 20, base / 10, base / 5, base / 2, base):
        if 8 <= data_range / cand <= 25:
            step = cand
            break
    else:
        step = base / 10
    snapped = round(x / step) * step
    decimals = max(0, -int(math.floor(math.log10(step)))) if step < 1 else 0
    snapped = round(snapped, decimals)

    # The grid is derived from the RANGE, which is wrong for a value far below it:
    # on entries-per-station (range 3.4e7) the median 1.19e6 snapped to 2.0e6, a 67%
    # error. Rounding must stay cosmetic relative to the threshold's own magnitude,
    # so fall back to significant-figure rounding past a 10% shift.
    if x and abs(snapped - x) / abs(x) > 0.10:
        mag = math.floor(math.log10(abs(x)))
        return round(x, -(mag - 2))       # three significant figures
    return snapped


def derive_parameters(contract: dict, value_column: str, *, n_bins: int = 3,
                      method: str = "quantile", nice: bool = True) -> dict:
    """
    Propose template parameters from the contract instead of only rejecting bad ones.

      method="quantile" -> equal-frequency edges (each bin holds ~the same row count)
      method="quartile" -> q1 / q3 edges (a 25/50/25 split)

    `baseline` is the median: the value half the data sits either side of, which is
    what a diverging bar chart's neutral reference should be.
    """
    c = column(contract, value_column)
    if c is None:
        raise ContractViolation(contract.get("name"), [f"no column {value_column!r}"])
    if c["kind"] != "numeric":
        raise ContractViolation(contract.get("name"), [f"{value_column!r} is {c['kind']}, not numeric"])
    if c["all_null"]:
        raise ContractViolation(contract.get("name"), [f"{value_column!r} is 100% NULL"])

    s = c["stats"]
    rng = s["max"] - s["min"]

    if method == "quartile":
        raw = [s["q1"], s["q3"]][: max(1, n_bins - 1)]
    else:
        qs = [i / n_bins for i in range(1, n_bins)]
        known = {0.25: s["q1"], 0.5: s["median"], 0.75: s["q3"]}
        known.update({float(k): v for k, v in (s.get("deciles") or {}).items()})
        raw = []
        for q in qs:
            hit = next((v for k, v in known.items() if abs(k - q) < 1e-9), None)
            if hit is None:
                # Nearest recorded quantiles either side, linearly interpolated between
                # them -- still skew-aware, unlike interpolating across min..max.
                below = max((k for k in known if k <= q), default=None)
                above = min((k for k in known if k >= q), default=None)
                if below is None or above is None:
                    hit = s["min"] + (s["max"] - s["min"]) * q
                elif below == above:
                    hit = known[below]
                else:
                    t = (q - below) / (above - below)
                    hit = known[below] + (known[above] - known[below]) * t
            raw.append(hit)

    # Rounding is cosmetic and must never move an edge outside the data, which on a
    # heavily skewed column it otherwise does: entries-per-station (skew +5.2, range
    # 2.5e4..3.4e7) rounded a low quantile to 0.0, producing an empty first bin.
    # Fall back to the unrounded value whenever the rounded one leaves the range.
    def _safe(e):
        if not nice:
            return round(e, 4)
        r = _nice(e, rng)
        return r if s["min"] < r < s["max"] else round(e, 4)

    edges = sorted(set(_safe(e) for e in raw))

    # Ties: equal-frequency binning is impossible when a few values dominate. Players
    # per hometown city has 22 distinct values across 1,256 rows and a median of 1 --
    # no set of edges splits it evenly, and none should be proposed as if it could.
    warnings: list[str] = []
    ties_ratio = c["distinct"] / max(1, contract.get("row_count") or 1)
    if c["distinct"] < (n_bins * 2):
        warnings.append(
            f"only {c['distinct']} distinct value(s) for {n_bins} bins; "
            f"equal-frequency binning cannot separate them")
    elif ties_ratio < 0.05:
        warnings.append(
            f"{c['distinct']} distinct values across {contract.get('row_count')} rows "
            f"(ratio {ties_ratio:.3f}); heavy ties make equal-frequency bins unbalanced")
    if len(edges) < len(raw):
        warnings.append(f"rounding collapsed {len(raw)} edges to {len(edges)}; bins are not distinct")

    return {
        "value_column": value_column,
        "method": method,
        "n_bins": n_bins,
        "warnings": warnings,
        "edges": edges + [float("inf")],
        "edges_raw": [round(x, 4) for x in raw],
        "baseline": (lambda b: b if s["min"] < b < s["max"] else round(s["median"], 4))(
            _nice(s["median"], rng) if nice else round(s["median"], 4)),
        "baseline_raw": round(s["median"], 4),
        "labels": [f"Category {chr(65 + i)}" for i in range(len(edges) + 1)],
        "observed_range": [s["min"], s["max"]],
    }


# --------------------------------------------------------------------------- #
# PROPOSALS  --  derivation proposes; a human or a later step decides
# --------------------------------------------------------------------------- #
ACCEPT_CAVEAT = (
    "Derived from the distribution alone. Natural breaks -- zero, 100%, a policy "
    "threshold, a round unit -- beat equal-frequency balance for some charts, and "
    "nothing in the data reveals which. Review before use."
)


def propose_parameters(contract: dict, value_column: str, *, n_bins: int = 3,
                       method: str = "quantile", occupancy: list | None = None) -> dict:
    """
    Wrap derive_parameters as an explicit PROPOSAL carrying its reasoning.

    Never returns an applied parameter set. `status` stays "proposed" until
    accept_proposal() is called, so nothing downstream can mistake a derived
    default for a reviewed decision.
    """
    import datetime as _dt
    d = derive_parameters(contract, value_column, n_bins=n_bins, method=method)
    c = column(contract, value_column)
    s = c["stats"]

    reasoning = [
        f"{contract.get('row_count')} rows; {value_column!r} spans {s['min']} to {s['max']}.",
        f"method={method}: "
        + ("edges at the n-quantiles, so each bin holds roughly equal row counts."
           if method == "quantile" else
           "edges at q1 and q3, giving a 25/50/25 split."),
        f"raw edges {d['edges_raw']} rounded to {d['edges'][:-1]} at a precision the "
        f"{round(s['max'] - s['min'], 4)}-wide range justifies.",
        f"baseline {d['baseline']} is the median ({d['baseline_raw']}) -- the value half the "
        f"rows sit either side of.",
    ]
    if c["nulls"]:
        reasoning.append(f"{c['nulls']} NULL row(s) excluded from the statistics and not drawn.")
    warnings = list(d.get("warnings", []))

    if occupancy is not None:
        ideal = round(contract["row_count"] / n_bins)
        reasoning.append(f"resulting bin occupancy {occupancy} against an even split of ~{ideal} each.")
        # An empty bin is a legend entry with nothing in it. This survives the range
        # checks -- both edges can sit inside the data and still enclose no rows, as
        # happens on integer counts when quantiles land between adjacent integers
        # (players-per-city produced edges [1.0, 1.67] on values that are whole numbers).
        empty = [i for i, k in enumerate(occupancy) if k == 0]
        if empty:
            warnings.append(
                f"bin(s) {empty} contain no rows; the legend would show empty categories")
        elif max(occupancy) > 4 * max(1, min(occupancy)):
            warnings.append(
                f"bin occupancy {occupancy} is heavily unbalanced (widest:narrowest > 4:1)")

    for w in warnings:
        reasoning.append(f"WARNING: {w}")

    return {
        "status": PROPOSED,
        "proposed_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "value_column": value_column,
        "method": method,
        "n_bins": n_bins,
        "edges": [e for e in d["edges"] if math.isfinite(e)],
        "baseline": d["baseline"],
        "labels": d["labels"],
        "occupancy": occupancy,
        "warnings": warnings,
        "reliable": not warnings,
        "reasoning": reasoning,
        "caveat": ACCEPT_CAVEAT,
        "review": None,              # set when the proposal is selected
        "selected_by": None,
        "selected_by_type": None,
        "selected_at": None,
        "selection_reason": None,
        "selected_over_warnings": [],
        "confirmed_by": None,
        "confirmed_at": None,
        "confirmation_reason": None,
    }


class SelectionRefused(Exception):
    """
    Raised when a proposal may not be selected or confirmed by this actor.

    Distinct from ContractViolation: that means the data cannot drive the template,
    this means the ACTION is not permitted. Conflating them would let a caller catch
    one and silently swallow the other.
    """


# Backwards-compatible alias: this exception was AcceptanceRefused when the model
# still had a single "accepted" state.
AcceptanceRefused = SelectionRefused

HUMAN = "human"
AUTOMATION = "automation"
_ACTOR_TYPES = (HUMAN, AUTOMATION)

# --- Two orthogonal facts, deliberately not one word ------------------------ #
# `status` answers: has a value been chosen for this parameter?
# `review` answers: has a person endorsed that choice?
#
# The previous model had a single `accepted`, which collapsed both. Every surface
# built on it then had to re-derive "was this actually reviewed?" from
# accepted_by_type, and the gallery ended up patching the gap with a badge. The
# word "accepted" is gone entirely: there is no longer a value that an
# automation-only choice could be misread as.
PROPOSED = "proposed"
SELECTED = "selected"
REJECTED = "rejected"

UNREVIEWED = "unreviewed"   # chosen by automation, no person has looked
CONFIRMED = "confirmed"     # chosen by automation, a person endorsed it
AUTHORED = "authored"       # chosen by a person directly

_REVIEWED_STATES = (CONFIRMED, AUTHORED)


def is_reviewed(proposal: dict) -> bool:
    """True only when a person stands behind the value. Automation alone never does."""
    return (proposal.get("status") == SELECTED
            and proposal.get("review") in _REVIEWED_STATES)


def review_label(proposal: dict) -> str:
    """A phrase a surface can print without having to reason about provenance."""
    status = proposal.get("status")
    if status == PROPOSED:
        return "proposed, not yet chosen"
    if status == REJECTED:
        return "rejected"
    return {
        UNREVIEWED: "chosen by automation, not reviewed",
        CONFIRMED: "chosen by automation, confirmed by a person",
        AUTHORED: "chosen by a person",
    }.get(proposal.get("review"), "chosen, review state unknown")


def normalize_proposal(proposal: dict) -> dict:
    """
    Upgrade a proposal written under the old single-`accepted` model.

    An old `accepted` by automation becomes selected/unreviewed -- which is what it
    always meant, and what the old shape could not say.
    """
    if proposal.get("status") != "accepted":
        return dict(proposal)
    out = dict(proposal)
    actor = out.get("accepted_by_type")
    out["status"] = SELECTED
    out["review"] = AUTHORED if actor == HUMAN else UNREVIEWED
    out["selected_by"] = out.pop("accepted_by", None)
    out["selected_by_type"] = out.pop("accepted_by_type", None)
    out["selected_at"] = out.pop("accepted_at", None)
    out["selected_over_warnings"] = out.pop("accepted_over_warnings", [])
    reason = out.pop("acceptance_reason", None)
    out["selection_reason"] = reason
    out.setdefault("confirmed_by", None)
    out.setdefault("confirmed_at", None)
    out.setdefault("confirmation_reason", None)
    return out


def _now() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def select_parameters(proposal: dict, *, by: str, actor_type: str,
                      reason: str | None = None, override_unreliable: bool = False) -> dict:
    """
    Choose this proposal's values. Only a selected proposal should drive a render.

    Selecting is not reviewing. Automation selecting a reliable proposal yields
    review=UNREVIEWED, and nothing downstream may treat that as endorsed. A person
    selecting directly yields review=AUTHORED.

    Policy (unchanged from the previous model):
      * reliable proposal   -- either actor may select.
      * unreliable proposal -- automation may NEVER select, on any path. A person may,
                               but only with override_unreliable=True AND a reason,
                               both recorded on the proposal.
    """
    if actor_type not in _ACTOR_TYPES:
        raise SelectionRefused(
            f"actor_type must be one of {_ACTOR_TYPES}, got {actor_type!r}; "
            f"an unattributed selection is not a selection")
    if not by or not str(by).strip():
        raise SelectionRefused("`by` must identify who is selecting")
    if proposal.get("status") == SELECTED:
        raise SelectionRefused(
            f"already selected by {proposal.get('selected_by')!r} at {proposal.get('selected_at')}")

    unreliable = not proposal.get("reliable", False)
    if unreliable:
        warn = "; ".join(proposal.get("warnings") or []) or "flagged unreliable"
        if actor_type == AUTOMATION:
            raise SelectionRefused(
                f"automated selection is not available for an unreliable proposal "
                f"({warn}). A person must select it explicitly, with a reason.")
        if not override_unreliable:
            raise SelectionRefused(
                f"proposal is unreliable ({warn}); a person may select it only with "
                f"override_unreliable=True and a recorded reason")
        if not reason or not str(reason).strip():
            raise SelectionRefused(
                "overriding an unreliable proposal requires a recorded reason")

    out = dict(proposal)
    out["status"] = SELECTED
    out["review"] = AUTHORED if actor_type == HUMAN else UNREVIEWED
    out["selected_by"] = by
    out["selected_by_type"] = actor_type
    out["selected_at"] = _now()
    out["selection_reason"] = (reason.strip() if reason else None)
    out["selected_over_warnings"] = sorted(proposal.get("warnings") or []) if unreliable else []
    out["confirmed_by"] = None
    out["confirmed_at"] = None
    out["confirmation_reason"] = None
    return out


def confirm_selection(proposal: dict, *, by: str, reason: str | None = None) -> dict:
    """
    A person endorses a value automation chose. This is the only path from
    UNREVIEWED to a reviewed state, and only a person may walk it -- there is no
    actor_type argument because automation confirming its own choice is not review.
    """
    if not by or not str(by).strip():
        raise SelectionRefused("`by` must identify the person confirming")
    if proposal.get("status") != SELECTED:
        raise SelectionRefused(
            f"only a selected proposal can be confirmed; this one is {proposal.get('status')!r}")
    if proposal.get("review") == AUTHORED:
        raise SelectionRefused("a person already authored this selection; nothing to confirm")
    if proposal.get("review") == CONFIRMED:
        raise SelectionRefused(
            f"already confirmed by {proposal.get('confirmed_by')!r} at {proposal.get('confirmed_at')}")

    out = dict(proposal)
    out["review"] = CONFIRMED
    out["confirmed_by"] = by
    out["confirmed_at"] = _now()
    out["confirmation_reason"] = (reason.strip() if reason else None)
    return out


def reject_proposal(proposal: dict, *, by: str, actor_type: str, reason: str) -> dict:
    """Record an explicit rejection, so a declined proposal is not merely absent."""
    if not reason or not str(reason).strip():
        raise SelectionRefused("a rejection must record a reason")
    out = dict(proposal)
    out["status"] = REJECTED
    out["review"] = None
    out["selected_by"] = by
    out["selected_by_type"] = actor_type
    out["selected_at"] = _now()
    out["selection_reason"] = reason.strip()
    return out


def selected_parameters(contract: dict, value_column: str) -> dict | None:
    """The selected proposal for a column, or None. Renders must use only this."""
    for p in contract.get("suggested_parameters", []) or []:
        p = normalize_proposal(p)
        if p.get("value_column") == value_column and p.get("status") == SELECTED:
            return p
    return None


def reviewed_parameters(contract: dict, value_column: str) -> dict | None:
    """
    The selected proposal for a column, but only if a person stands behind it.
    Use this wherever "reviewed" is the bar; use selected_parameters() otherwise.
    """
    p = selected_parameters(contract, value_column)
    return p if p and is_reviewed(p) else None


def attach_proposal(contract: dict, proposal: dict) -> dict:
    contract.setdefault("suggested_parameters", []).append(proposal)
    return contract


# --------------------------------------------------------------------------- #
# STAGE D GATES
# --------------------------------------------------------------------------- #
def check_dataset(contract: dict, *, allow_all_null_columns: bool = False) -> None:
    """
    Precondition for hydration, where the template's required columns are not known
    in advance. Catches the two dataset-level failures that render as success:
    an empty result set (line_daily has 0 rows) and columns that exist but are
    entirely NULL (station_daily.exits / ridership_proxy / lines).
    """
    problems: list[str] = []
    if contract.get("row_count", 0) == 0:
        problems.append("dataset is empty (0 rows); the chart would render blank, not fail")
    if not allow_all_null_columns:
        dead = [c["name"] for c in contract["columns"] if c["all_null"]]
        if dead:
            problems.append(f"column(s) {dead} exist but are 100% NULL; anything drawn from them is blank")
    if problems:
        raise ContractViolation(contract.get("name"), problems)


def check_figure(fig, *, chart: str | None = None) -> None:
    """
    Post-render gate. A Figure with no traces, or whose every trace carries no
    points, is a successful render of nothing -- the exact shape of failure that
    has been passing as success in this pipeline.
    """
    problems: list[str] = []
    traces = list(getattr(fig, "data", []) or [])
    if not traces:
        problems.append("figure has no traces")
    else:
        def _len(tr):
            for attr in ("y", "x", "values", "z", "locations", "lat", "labels"):
                v = getattr(tr, attr, None)
                if v is not None:
                    try:
                        return len(v)
                    except TypeError:
                        return 1
            return 0
        if sum(_len(t) for t in traces) == 0:
            problems.append(f"all {len(traces)} trace(s) are empty; the render produced a blank chart")
    if problems:
        raise ContractViolation(chart, problems)


def band_labels(edges: Sequence[float]) -> list[str]:
    """
    Name each band by the values it holds.

    "Category A" is a placeholder the derivation uses because it knows nothing
    about the subject -- but it knows the numbers, and "under 11.7" is what a
    legend has to say for a reader to decode the chart at all. One implementation,
    so the legend and the settings panel can never quote different boundaries.
    """
    finite = [e for e in edges if math.isfinite(float(e))]

    def n(v):
        return f"{float(v):,.10g}"

    if not finite:
        return ["All values"]
    out = [f"Under {n(finite[0])}"]
    out += [f"{n(lo)} to {n(hi)}" for lo, hi in zip(finite, finite[1:])]
    out.append(f"{n(finite[-1])} and above")
    return out


def manual_proposal(contract: dict, value_column: str, *, edges: Sequence[float],
                    baseline: float | None = None, occupancy: list | None = None,
                    supersedes: dict | None = None) -> dict:
    """
    A proposal carrying values a PERSON chose, in the same shape as a derived one.

    When someone moves a boundary they are not editing the machine's proposal --
    they are making a different one. Keeping it as its own record is what lets the
    original stay visible underneath (`supersedes`) instead of being overwritten,
    and it is why `select_parameters(..., actor_type=HUMAN)` can mark the result
    AUTHORED rather than having to mutate something already selected.
    """
    import datetime as _dt

    c = column(contract, value_column)
    if c is None:
        raise ContractViolation(contract.get("name"), [f"no column {value_column!r}"])

    finite = [float(e) for e in edges if math.isfinite(float(e))]
    labels = [f"Category {chr(65 + i)}" for i in range(len(finite) + 1)]
    if baseline is None:
        baseline = (c.get("stats") or {}).get("median")

    warnings: list[str] = []
    if occupancy is not None:
        empty = [i for i, n in enumerate(occupancy) if n == 0]
        if empty:
            warnings.append(f"bin(s) {empty} contain no rows; the legend would show "
                            f"empty categories")

    reasoning = [f"Boundaries set by hand at {', '.join(str(e) for e in finite)}."]
    if occupancy is not None:
        ideal = round((contract.get("row_count") or 0) / max(1, len(finite) + 1))
        reasoning.append(f"resulting bin occupancy {occupancy} against an even split "
                         f"of ~{ideal} each.")
    if supersedes:
        reasoning.append(f"Replaces the derived proposal "
                         f"{[e for e in supersedes.get('edges', []) if math.isfinite(e)]}"
                         f", baseline {supersedes.get('baseline')}.")

    return {
        "status": PROPOSED,
        "proposed_at": _now(),
        "value_column": value_column,
        "method": "manual",
        "n_bins": len(finite) + 1,
        "edges": finite + [float("inf")],
        "baseline": baseline,
        "labels": labels,
        "occupancy": occupancy,
        "warnings": warnings,
        "reliable": not warnings,
        "reasoning": reasoning,
        "caveat": ACCEPT_CAVEAT,
        "supersedes": {k: supersedes.get(k) for k in ("edges", "baseline", "method")}
                      if supersedes else None,
        "review": None,
        "selected_by": None,
        "selected_by_type": None,
        "selected_at": None,
        "selection_reason": None,
        "selected_over_warnings": [],
        "confirmed_by": None,
        "confirmed_at": None,
        "confirmation_reason": None,
    }
