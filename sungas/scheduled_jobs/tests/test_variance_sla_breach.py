"""Unit tests for Wave D-3 variance SLA breach tier resolution and
state-tracker behaviour. Pure-function tests; no live Frappe context.

Run::

    cd /app/forks/Sungas && python -m pytest sungas/scheduled_jobs/tests/test_variance_sla_breach.py -v
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path


# Inject minimal frappe stub if not already present.
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
    sys.modules["frappe.utils"] = stub.utils

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from sungas.scheduled_jobs.variance_sla_breach import PENDING_STATE_ROLE  # noqa: E402
from sungas.overrides import variance_sla  # noqa: E402


class StateRoleMapTests(unittest.TestCase):
    def test_all_pending_states_mapped(self) -> None:
        # The 4 Pending states defined in install_variance_workflow.py must each
        # resolve to an LPG-prefixed role.
        expected = {
            "Pending Plant Manager",
            "Pending HOD Operations",
            "Pending HOD Finance",
            "Pending COO",
        }
        self.assertEqual(set(PENDING_STATE_ROLE.keys()), expected)
        for role in PENDING_STATE_ROLE.values():
            self.assertTrue(role.startswith("LPG "), f"Non-LPG role: {role}")


class TrackStateEntryTests(unittest.TestCase):
    def _make_doc(self, new_state: str, old_state: str | None = None):
        before = types.SimpleNamespace(get=lambda key: {"workflow_state": old_state}.get(key))
        calls: list[tuple[str, object]] = []

        def db_set(field, value, update_modified=False):
            calls.append((field, value))

        doc = types.SimpleNamespace(
            get=lambda key: {"workflow_state": new_state}.get(key),
            get_doc_before_save=lambda: before if old_state is not None else None,
            db_set=db_set,
            _calls=calls,
        )
        return doc

    def test_enter_pending_state_stamps_timer(self) -> None:
        doc = self._make_doc("Pending Plant Manager", old_state="Draft")
        variance_sla.track_state_entry(doc)
        fields = {f for f, _ in doc._calls}
        self.assertEqual(
            fields,
            {"variance_state_entered_at", "variance_sla_escalated_at", "variance_sla_escalation_level"},
        )

    def test_same_state_save_is_noop(self) -> None:
        doc = self._make_doc("Pending Plant Manager", old_state="Pending Plant Manager")
        variance_sla.track_state_entry(doc)
        self.assertEqual(doc._calls, [])

    def test_leaving_pending_clears_timer(self) -> None:
        doc = self._make_doc("Approved", old_state="Pending HOD Finance")
        variance_sla.track_state_entry(doc)
        # Only the variance_state_entered_at clear should fire.
        self.assertEqual([c[0] for c in doc._calls], ["variance_state_entered_at"])
        self.assertIsNone(doc._calls[0][1])

    def test_empty_workflow_state_is_noop(self) -> None:
        doc = self._make_doc("", old_state="Draft")
        variance_sla.track_state_entry(doc)
        self.assertEqual(doc._calls, [])


if __name__ == "__main__":
    unittest.main()
