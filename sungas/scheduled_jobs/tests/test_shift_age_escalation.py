"""Unit tests for the Wave D-2 escalation tier resolver.

Pure-function tests; no Frappe context required::

    cd /app/forks/Sungas && python -m pytest sungas/scheduled_jobs/tests/test_shift_age_escalation.py -v
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path


# Inject a minimal `frappe` stub so the module imports without a live site.
if "frappe" not in sys.modules:
    stub = types.ModuleType("frappe")
    stub.utils = types.SimpleNamespace(
        add_to_date=lambda *a, **k: None,
        get_datetime=lambda x: x,
        now_datetime=lambda: None,
        get_url=lambda: "",
    )
    stub.get_single = lambda *a, **k: None
    stub.log_error = lambda *a, **k: None
    stub.db = types.SimpleNamespace(
        sql=lambda *a, **k: [],
        get_value=lambda *a, **k: None,
        set_value=lambda *a, **k: None,
        commit=lambda: None,
    )
    stub.logger = lambda *a, **k: types.SimpleNamespace(info=lambda *a, **k: None)
    stub.get_traceback = lambda: ""
    stub.only_for = lambda *a, **k: None
    stub.whitelist = lambda *a, **k: (lambda fn: fn)
    sys.modules["frappe"] = stub
    # also stub frappe.utils submodule import path
    sys.modules["frappe.utils"] = stub.utils

# Ensure the sungas package is on path when running standalone pytest.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from sungas.scheduled_jobs.shift_age_escalation import _level_due  # noqa: E402


class LevelDueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tiers = [24, 48, 168]

    def test_below_l1_returns_zero(self) -> None:
        self.assertEqual(_level_due(23.9, self.tiers), 0)

    def test_exactly_l1_returns_24(self) -> None:
        self.assertEqual(_level_due(24.0, self.tiers), 24)

    def test_between_l1_and_l2_returns_24(self) -> None:
        self.assertEqual(_level_due(47.5, self.tiers), 24)

    def test_exactly_l2_returns_48(self) -> None:
        self.assertEqual(_level_due(48.0, self.tiers), 48)

    def test_between_l2_and_l3_returns_48(self) -> None:
        self.assertEqual(_level_due(167.9, self.tiers), 48)

    def test_exactly_l3_returns_168(self) -> None:
        self.assertEqual(_level_due(168.0, self.tiers), 168)

    def test_far_above_l3_returns_168(self) -> None:
        self.assertEqual(_level_due(720.0, self.tiers), 168)

    def test_dedup_when_admin_collapses_tiers(self) -> None:
        # Admin sets L1=L2=24 (effectively disables L2 chain).
        self.assertEqual(_level_due(24.0, [24, 168]), 24)
        self.assertEqual(_level_due(168.0, [24, 168]), 168)


if __name__ == "__main__":
    unittest.main()
