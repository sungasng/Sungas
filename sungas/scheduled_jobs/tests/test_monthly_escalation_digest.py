"""Unit tests for B-11 Monthly Escalation Digest.

Pure-function tests for the period-calculator and renderer. Live DB
queries are exercised manually via dry_run on the Frappe Cloud bench.

Run::

    cd /app/forks/Sungas && python -m pytest sungas/scheduled_jobs/tests/test_monthly_escalation_digest.py -v
"""

from __future__ import annotations

import sys
import types
import unittest
from datetime import date, datetime
from pathlib import Path


if "frappe" not in sys.modules:
    stub = types.ModuleType("frappe")
    stub.utils = types.SimpleNamespace(
        now_datetime=lambda: datetime(2026, 3, 1, 9, 0, 0),
        nowdate=lambda: "2026-03-01",
        get_url=lambda: "https://example.com",
        add_to_date=lambda *a, **k: None,
        get_datetime=lambda x: x,
        flt=lambda x: float(x) if x is not None else 0.0,
    )
    stub.log_error = lambda *a, **k: None
    stub.db = types.SimpleNamespace(
        sql=lambda *a, **k: [],
        get_value=lambda *a, **k: None,
        set_value=lambda *a, **k: None,
        commit=lambda: None,
        count=lambda *a, **k: 0,
    )
    stub.logger = lambda *a, **k: types.SimpleNamespace(info=lambda *a, **k: None)
    stub.get_traceback = lambda: ""
    stub.only_for = lambda *a, **k: None
    stub.whitelist = lambda *a, **k: (lambda fn: fn)
    stub.session = types.SimpleNamespace(user="tester@sungas.org")
    stub._ = lambda x: x
    sys.modules["frappe"] = stub
    sys.modules["frappe.utils"] = stub.utils

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from sungas.scheduled_jobs import monthly_escalation_digest as digest  # noqa: E402


def _set_now(dt: datetime) -> None:
    """Patch the digest module's bound `now_datetime` (it was imported by name)."""
    digest.now_datetime = lambda: dt


class PreviousMonthTests(unittest.TestCase):
    def test_first_of_march_returns_february(self) -> None:
        _set_now(datetime(2026, 3, 1, 9, 0, 0))
        start, end = digest._previous_calendar_month()
        self.assertEqual(start, date(2026, 2, 1))
        self.assertEqual(end, date(2026, 2, 28))

    def test_first_of_january_returns_december(self) -> None:
        _set_now(datetime(2026, 1, 1, 9, 0, 0))
        start, end = digest._previous_calendar_month()
        self.assertEqual(start, date(2025, 12, 1))
        self.assertEqual(end, date(2025, 12, 31))


class TableRendererTests(unittest.TestCase):
    def test_open_shift_table_with_rows(self) -> None:
        rows = [
            {"pos_profile": "POS - Ikeja", "tier": 24, "n": 3},
            {"pos_profile": "POS - Ikeja", "tier": 48, "n": 1},
            {"pos_profile": "POS - Itele", "tier": 168, "n": 1},
        ]
        html = digest._open_shift_table(rows)
        self.assertIn("POS - Ikeja", html)
        self.assertIn("POS - Itele", html)
        # Numbers should appear in the rendered cells.
        self.assertIn(">3<", html)
        self.assertIn(">1<", html)

    def test_open_shift_table_empty(self) -> None:
        html = digest._open_shift_table([])
        self.assertIn("No open-shift age escalations", html)

    def test_top_offenders_caps_at_5(self) -> None:
        rows = [{"pos_profile": f"Outlet {i}", "tier": 24, "n": i + 1} for i in range(10)]
        html = digest._top_offenders_table(rows, [])
        # The 5 highest-count outlets should be rendered.
        for i in range(5, 10):
            self.assertIn(f"Outlet {i}", html)
        # Outlet 0 (count=1) should not appear.
        self.assertNotIn("Outlet 0<", html)

    def test_variance_table_empty(self) -> None:
        html = digest._variance_table([])
        self.assertIn("No variance SLA breaches", html)


class SubjectRenderTests(unittest.TestCase):
    def test_subject_contains_month_label(self) -> None:
        start = date(2026, 2, 1)
        end = date(2026, 2, 28)
        subject, html = digest._render(
            period_start=start,
            period_end=end,
            open_shift_rows=[],
            variance_rows=[],
            backlog={"stale_open_shifts": 0, "pending_variances": 0},
        )
        self.assertIn("February 2026", subject)
        self.assertIn("Monthly Escalation Digest", html)
        # Backlog snapshot should render zeros.
        self.assertIn(">0<", html)


if __name__ == "__main__":
    unittest.main()
