"""Bounded, ordered and credential-redacted material for AI explanations.

Device verification continues to use ConfigVerifier; this is text evidence only.
"""
from difflib import unified_diff
from core.redaction import redact_sensitive


def display_diff_excerpt(before: str, after: str) -> dict:
    a, b = redact_sensitive(before or ''), redact_sensitive(after or '')
    different = a != b
    # Bound the matcher independently of the number of emitted rows.
    left = a[:12000].splitlines()[:600]
    right = b[:12000].splitlines()[:600]
    truncated = len(a) > 12000 or len(b) > 12000 or a.count('\n') >= 600 or b.count('\n') >= 600
    rows = []
    size = 0
    for line in unified_diff(left, right, fromfile='A', tofile='B', n=2, lineterm=''):
        if len(rows) >= 120 or size + len(line) > 14000:
            truncated = True
            break
        rows.append(line)
        size += len(line)
    return {'text': '\n'.join(rows), 'truncated': truncated, 'different': different,
            'scope': 'redacted_ordered_text_only', 'line_limit_per_side': 600}
