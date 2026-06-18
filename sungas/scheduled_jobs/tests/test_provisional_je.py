"""Unit tests for Wave D-4: Provisional Suspense JE on Draft and the
COO informational notification.

Pure-function tests for the gating predicates of the new hooks. Live JE
posting is intentionally NOT exercised here — it requires a Frappe site
with seeded accounts and would belong in an integration test on the
Frappe Cloud bench.

Run::

    cd /app/forks/Sungas && python -m pytest sungas/scheduled_jobs/tests/test_provisional_je.py -v
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path


if "frappe" not in sys.modules:
    stub = types.ModuleType("frappe")
    stub.utils = types.SimpleNamespace(
        add_to_date=lambda *a, **k: None,
        get_datetime=lambda x: x,
        now_datetime=lambda: "NOW",
        get_url=lambda: "",
        nowdate=lambda: "2026-01-01",
        flt=lambda x: float(x) if x is not None else 0.0,
    )
    stub.get_single = lambda *a, **k: types.SimpleNamespace(
        get=lambda key: None,
        cashier_recovery_account=None,
        overage_suspense_account=None,
    )
    stub.get_doc = lambda *a, **k: types.SimpleNamespace(insert=lambda **kw: None, submit=lambda: None)
    stub.log_error = lambda *a, **k: None
    stub.db = types.SimpleNamespace(
        sql=lambda *a, **k: [],
        get_value=lambda *a, **k: None,
        set_value=lambda *a, **k: None,
        commit=lambda: None,
        exists=lambda *a, **k: True,
        count=lambda *a, **k: 0,
        delete=lambda *a, **k: None,
    )
    stub.logger = lambda *a, **k: types.SimpleNamespace(info=lambda *a, **k: None)
    stub.get_traceback = lambda: ""
    stub.only_for = lambda *a, **k: None
    stub.whitelist = lambda *a, **k: (lambda fn: fn)
    stub.session = types.SimpleNamespace(user="tester@sungas.org")
    stub._ = lambda x: x
    stub.throw = lambda *a, **k: (_ for _ in ()).throw(Exception("frappe.throw"))
    stub.get_roles = lambda *a, **k: []
    sys.modules["frappe"] = stub
    sys.modules["frappe.utils"] = stub.utils

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from sungas.overrides import pos_closing_shift, coo_notification  # noqa: E402


class _FakeDoc(types.SimpleNamespace):
    """Tiny dict-like stand-in for a Frappe doc."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._set_calls: list[tuple[str, object]] = []

    def get(self, key, default=None):
        return getattr(self, key, default)

    def set(self, key, value):
        setattr(self, key, value)
        self._set_calls.append((key, value))


class ProvisionalGatingTests(unittest.TestCase):
    """Validate that post_provisional_journal early-exits on the right cases."""

    def test_skips_when_already_posted(self) -> None:
        doc = _FakeDoc(
            docstatus=0,
            variance_provisional_je="ACC-JV-XYZ",
            variance_severity="critical",
            workflow_state="Pending Plant Manager",
        )
        # If the function tried to post it would call frappe.get_doc; the
        # stub doesn't error, so we assert by side-effect: no set_value call.
        called: list = []
        original = pos_closing_shift.frappe.db.set_value
        pos_closing_shift.frappe.db.set_value = lambda *a, **k: called.append(a)
        try:
            pos_closing_shift.post_provisional_journal(doc)
        finally:
            pos_closing_shift.frappe.db.set_value = original
        self.assertEqual(called, [])

    def test_skips_when_submitted(self) -> None:
        doc = _FakeDoc(
            docstatus=1,
            variance_provisional_je=None,
            variance_severity="critical",
            workflow_state="Approved",
        )
        called: list = []
        original = pos_closing_shift.frappe.db.set_value
        pos_closing_shift.frappe.db.set_value = lambda *a, **k: called.append(a)
        try:
            pos_closing_shift.post_provisional_journal(doc)
        finally:
            pos_closing_shift.frappe.db.set_value = original
        self.assertEqual(called, [])

    def test_skips_when_severity_warn(self) -> None:
        doc = _FakeDoc(
            docstatus=0,
            variance_provisional_je=None,
            variance_severity="warn",
            workflow_state="Pending Plant Manager",
        )
        called: list = []
        original = pos_closing_shift.frappe.db.set_value
        pos_closing_shift.frappe.db.set_value = lambda *a, **k: called.append(a)
        try:
            pos_closing_shift.post_provisional_journal(doc)
        finally:
            pos_closing_shift.frappe.db.set_value = original
        self.assertEqual(called, [])

    def test_skips_when_workflow_not_pending(self) -> None:
        doc = _FakeDoc(
            docstatus=0,
            variance_provisional_je=None,
            variance_severity="critical",
            workflow_state="Draft",
        )
        called: list = []
        original = pos_closing_shift.frappe.db.set_value
        pos_closing_shift.frappe.db.set_value = lambda *a, **k: called.append(a)
        try:
            pos_closing_shift.post_provisional_journal(doc)
        finally:
            pos_closing_shift.frappe.db.set_value = original
        self.assertEqual(called, [])


class CancelGatingTests(unittest.TestCase):
    def test_skips_when_not_rejected(self) -> None:
        doc = _FakeDoc(workflow_state="Approved", variance_provisional_je="ACC-JV-XYZ")
        # Should be a no-op (no exceptions).
        pos_closing_shift.cancel_provisional_journal(doc)

    def test_skips_when_no_provisional(self) -> None:
        doc = _FakeDoc(workflow_state="Rejected", variance_provisional_je=None)
        pos_closing_shift.cancel_provisional_journal(doc)


class CooNotificationGatingTests(unittest.TestCase):
    def test_skips_when_state_not_approved(self) -> None:
        doc = _FakeDoc(
            workflow_state="Pending HOD Finance",
            variance_severity="critical",
            coo_notified_at=None,
        )
        called: list = []
        original = coo_notification.frappe.db.set_value
        coo_notification.frappe.db.set_value = lambda *a, **k: called.append(a)
        try:
            coo_notification.notify_coo_on_critical_approval(doc)
        finally:
            coo_notification.frappe.db.set_value = original
        self.assertEqual(called, [])

    def test_skips_when_severity_not_critical(self) -> None:
        doc = _FakeDoc(
            workflow_state="Approved",
            variance_severity="block",
            coo_notified_at=None,
        )
        called: list = []
        original = coo_notification.frappe.db.set_value
        coo_notification.frappe.db.set_value = lambda *a, **k: called.append(a)
        try:
            coo_notification.notify_coo_on_critical_approval(doc)
        finally:
            coo_notification.frappe.db.set_value = original
        self.assertEqual(called, [])

    def test_skips_when_already_notified(self) -> None:
        doc = _FakeDoc(
            workflow_state="Approved",
            variance_severity="critical",
            coo_notified_at="2026-01-01",
        )
        called: list = []
        original = coo_notification.frappe.db.set_value
        coo_notification.frappe.db.set_value = lambda *a, **k: called.append(a)
        try:
            coo_notification.notify_coo_on_critical_approval(doc)
        finally:
            coo_notification.frappe.db.set_value = original
        self.assertEqual(called, [])

    def test_skips_when_old_state_already_approved(self) -> None:
        """Cosmetic re-save of a previously-Approved doc must not re-fire."""
        doc = _FakeDoc(
            workflow_state="Approved",
            variance_severity="critical",
            coo_notified_at=None,
            pos_profile="Outlet A",
            name="POSA-CS-TEST",
            variance_amount=-78240.0,
            variance_approved_by="hod@sungas.org",
            user="cashier@sungas.org",
        )
        # Simulate doc_before_save also being "Approved".
        before = types.SimpleNamespace(get=lambda key: "Approved" if key == "workflow_state" else None)
        doc.get_doc_before_save = lambda: before

        called: list = []
        original = coo_notification.frappe.db.set_value
        coo_notification.frappe.db.set_value = lambda *a, **k: called.append(a)
        try:
            coo_notification.notify_coo_on_critical_approval(doc)
        finally:
            coo_notification.frappe.db.set_value = original
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
