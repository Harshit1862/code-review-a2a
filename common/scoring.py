"""Severity helpers shared by the reviewer agents.

The score itself comes from the LLM (see common.schemas.LLMReview.score) -- these are
just the ordering/counting helpers used to sort and summarize its findings.
"""

from typing import Dict, Iterable

from common.schemas import Finding

SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]


def severity_counts(findings: Iterable[Finding]) -> Dict[str, int]:
    counts = {sev: 0 for sev in SEVERITY_ORDER}
    for f in findings:
        counts[f.severity] += 1
    return counts
