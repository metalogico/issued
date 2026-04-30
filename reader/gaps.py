"""Issue-number gap detection for ongoing series (integer issues only)."""

from __future__ import annotations


def issue_gaps(issue_numbers: list[int]) -> dict:
    """Return missing integers in the inclusive range [min, max] of distinct issues.

    issue_numbers may contain duplicates; they are treated as a set for gap logic.
    Comics with NULL issue_number are not passed here; use has_null_issue_numbers separately.

    Returns:
        missing: sorted list of gaps (empty if contiguous or fewer than 2 distinct values span)
        has_numbered_issues: True if at least one non-null issue was considered
    """
    distinct = {n for n in issue_numbers if n is not None}
    if not distinct:
        return {"missing": [], "has_numbered_issues": False}
    lo, hi = min(distinct), max(distinct)
    missing = [n for n in range(lo, hi + 1) if n not in distinct]
    return {"missing": missing, "has_numbered_issues": True}
