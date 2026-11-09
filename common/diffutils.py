"""Helpers for unified diffs."""

import re
from typing import List

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def added_lines(patch: str) -> List[int]:
    """Return line numbers (in the new file) that were added or modified by the patch."""
    if not patch:
        return []
    lines: List[int] = []
    new_line = 0
    in_hunk = False
    for raw in patch.splitlines():
        match = _HUNK.match(raw)
        if match:
            new_line = int(match.group(1))
            in_hunk = True
            continue
        if not in_hunk or raw.startswith("\\"):
            continue  # header lines, or "\ No newline at end of file"
        if raw.startswith("+") and not raw.startswith("+++"):
            lines.append(new_line)
            new_line += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            continue  # removed line: does not exist in the new file
        else:
            new_line += 1  # context line
    return lines
