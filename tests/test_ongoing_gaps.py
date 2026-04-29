"""Tests for issue gap detection (ongoing series)."""

import importlib.util
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("reader_gaps", _ROOT / "reader" / "gaps.py")
assert _spec and _spec.loader
_gaps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gaps)
issue_gaps = _gaps.issue_gaps


class TestIssueGaps(unittest.TestCase):
    def test_issue_gaps_empty(self):
        self.assertEqual(issue_gaps([]), {"missing": [], "has_numbered_issues": False})

    def test_issue_gaps_contiguous(self):
        self.assertEqual(issue_gaps([1, 2, 3]), {"missing": [], "has_numbered_issues": True})

    def test_issue_gaps_example_gaps(self):
        self.assertEqual(issue_gaps([1, 2, 3, 4, 7]), {"missing": [5, 6], "has_numbered_issues": True})

    def test_issue_gaps_duplicates(self):
        self.assertEqual(issue_gaps([1, 1, 2])["missing"], [])

    def test_issue_gaps_single(self):
        self.assertEqual(issue_gaps([5])["missing"], [])


if __name__ == "__main__":
    unittest.main()
