#!/usr/bin/env python3
"""
The caption gate, in both directions.

    python3 tests/test_caption_gate.py

A gate that only ever says no is not a gate, it is a wall. These cases pin both
behaviours: a template composing canonical placeholders must pass, and anything
asserting a subject must fail. The composite case is here because it was a real
false positive -- four of six Stage C runs were refused for emitting exactly the
placeholders they were asked for.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Scripts", "lib"))
from caption_gate import find_captions

MUST_PASS = [
    ('plain placeholder',        'fig.add_annotation(text="Chart title")'),
    ('bolded placeholder',       'fig.add_annotation(text="<b>Chart title</b>")'),
    ('composite, bare tags',     'fig.add_annotation(text="<b>Chart title</b><br>Units / measure description")'),
    ('composite, attr tags',     'fig.add_annotation(text="<b>Chart title</b><br>'
                                 '<span style=\'font-size:14px\'>Units / measure description</span>")'),
    ('source placeholder',       'fig.add_annotation(text="Source / credit")'),
    ('axis placeholder',         'fig.update_layout(xaxis_title="Axis label")'),
    ('structural words',         'fig.add_annotation(text="<b>Before</b>")'),
    ('category family',          'fig.add_annotation(text="Category A")'),
    ('empty / markup only',      'fig.add_annotation(text="<br>")'),
    ('numeric only',             'fig.add_annotation(text="+1.5%")'),
    ('hovertemplate token',      'go.Bar(hovertemplate="%{x}")'),
    ('arrow before placeholder', 'fig.add_annotation(text="\u2190 Axis label")'),
    ('arrow after placeholder',  'fig.add_annotation(text="Axis label \u2192")'),
    ('bulleted placeholder',     'fig.add_annotation(text="\u2022 Category A")'),
    ('column identifier',        'label_flag_column = "show_label"'),
    ('encoding, not caption',    'go.Choropleth(locationmode="USA-states")'),
]

MUST_FLAG = [
    ('subject in title',         'fig.add_annotation(text="Percent of SAT test takers")'),
    ('subject, bolded',          'fig.add_annotation(text="<b>Increase in Arrests</b>")'),
    ('subject inside composite', 'fig.add_annotation(text="<b>Chart title</b><br>'
                                 '<span style=\'font-size:14px\'>Arrests by state</span>")'),
    ('subject in attr tag',      'fig.add_annotation(text="<span style=\'color:red\'>Texas leads</span>")'),
    ('subject axis title',       'fig.update_layout(yaxis_title="Household income")'),
    ('named constant',           'POS_LABEL = "PROFIT"'),
    ('subject in dict',          'dict(text="Admissions rate at elite colleges")'),
    ('arrow cannot launder',     'fig.add_annotation(text="\u2190 POORER")'),
    ('arrow + subject',          'fig.add_annotation(text="Texas leads \u2192")'),
]


def main() -> int:
    bad = []
    for label, code in MUST_PASS:
        if find_captions(code):
            bad.append(f"FALSE POSITIVE — should pass: {label}")
    for label, code in MUST_FLAG:
        if not find_captions(code):
            bad.append(f"MISSED — should flag: {label}")
    for line in bad:
        print("  " + line)
    total = len(MUST_PASS) + len(MUST_FLAG)
    print(f"\n{total - len(bad)}/{total} passed"
          f"   ({len(MUST_PASS)} must-pass, {len(MUST_FLAG)} must-flag)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
