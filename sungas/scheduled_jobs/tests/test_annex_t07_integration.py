"""Unit tests for Wave D-5: Annex T-07 integration hooks.

Pure-function tests for the gating predicates. Live doc-creation /
submission is left for an integration test on the Frappe Cloud bench.

Run::

    cd /app/forks/Sungas && python -m pytest sungas/scheduled_jobs/tests/test_annex_t07_integration.py -v
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path


if "frappe" not in sys.modules:
    stub = types.ModuleType("frappe")
    stub.utils = types.SimpleNamespace(
        now_datetime=lambda: "NOW",
        nowdate=lambda: "2026-01-01",
        get_datetime=lambda x: x,
        add_to_date=lambda *a, **k: None,
        get_url=lambda: "",
        flt=lambda x: float(x) if x is not None else 0.0,
    )
    stub.get_single = lambda *a, **k: types.SimpleNamespace(get=lambda key: None)
    stub.get_doc = lambda *a, **k: types.SimpleNamespace(name="AT07-X", insert=lambda **kw: types.SimpleNamespace(name="AT07-X"))
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

    def _throw(msg=None, title=None, **kw):
        raise Exception(f"frappe.throw: {msg}")

    stub.throw = _throw
    sys.modules["frappe"] = stub
    sys.modules["frappe.utils"] = stub.utils

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from sungas.overrides import annex_t07_integration as t07  # noqa: E402


class _FakeDoc(types.SimpleNamespace):
    def get(self, key, default=None):
        return getattr(self, key, default)


class AutoCreateGatingTests(unittest.TestCase):
    def test_skips_when_submitted(self) -> None:
        doc = _FakeDoc(name="CS1", docstatus=1, variance_severity="critical", annex_t07=None)
        # Should be a no-op (no Frappe set_value call).
        called: list = []
        original = t07.frappe.db.set_value
        t07.frappe.db.set_value = lambda *a, **k: called.append(a)
        try:
            t07.auto_create_t07(doc)
        finally:
            t07.frappe.db.set_value = original
        self.assertEqual(called, [])

    def test_skips_when_severity_warn(self) -> None:
        doc = _FakeDoc(name="CS2", docstatus=0, variance_severity="warn", annex_t07=None)
        called: list = []
        original = t07.frappe.db.set_value
        t07.frappe.db.set_value = lambda *a, **k: called.append(a)
        try:
            t07.auto_create_t07(doc)
        finally:
            t07.frappe.db.set_value = original
        self.assertEqual(called, [])

    def test_skips_when_already_linked(self) -> None:
        doc = _FakeDoc(
            name="CS3", docstatus=0,
            variance_severity="critical", annex_t07="AT07-26-00001",
        )
        called: list = []
        original = t07.frappe.db.set_value
        t07.frappe.db.set_value = lambda *a, **k: called.append(a)
        try:
            t07.auto_create_t07(doc)
        finally:
            t07.frappe.db.set_value = original
        self.assertEqual(called, [])

    def test_reuses_existing_orphan_worksheet(self) -> None:
        """If a worksheet for this shift already exists (orphan from prior
        save), reuse it instead of inserting a duplicate."""
        doc = _FakeDoc(name="CS4", docstatus=0, variance_severity="block", annex_t07=None)
        # Stub get_value to find an orphan.
        original_get = t07.frappe.db.get_value
        t07.frappe.db.get_value = lambda *a, **k: "AT07-ORPHAN"
        called: list = []
        original_set = t07.frappe.db.set_value
        t07.frappe.db.set_value = lambda *a, **k: called.append(a)
        try:
            t07.auto_create_t07(doc)
        finally:
            t07.frappe.db.get_value = original_get
            t07.frappe.db.set_value = original_set
        # Should have linked the existing orphan, not created a new one.
        self.assertEqual(len(called), 1)
        # Second positional arg is the shift name, third is the field, fourth is the value.
        self.assertEqual(called[0][3], "AT07-ORPHAN")


class RequireT07Tests(unittest.TestCase):
    def test_passes_when_soft_variance(self) -> None:
        doc = _FakeDoc(variance_severity="warn", annex_t07=None)
        # Soft severity: no T-07 required, must not throw.
        t07.require_t07_for_hard_variance(doc)  # raises if it throws

    def test_passes_when_no_variance(self) -> None:
        doc = _FakeDoc(variance_severity="", annex_t07=None)
        t07.require_t07_for_hard_variance(doc)

    def test_throws_when_hard_no_link(self) -> None:
        doc = _FakeDoc(variance_severity="critical", annex_t07=None)
        with self.assertRaises(Exception):
            t07.require_t07_for_hard_variance(doc)

    def test_throws_when_hard_link_but_not_submitted(self) -> None:
        doc = _FakeDoc(variance_severity="block", annex_t07="AT07-26-00001")
        original_get = t07.frappe.db.get_value
        t07.frappe.db.get_value = lambda *a, **k: 0  # docstatus = Draft
        try:
            with self.assertRaises(Exception):
                t07.require_t07_for_hard_variance(doc)
        finally:
            t07.frappe.db.get_value = original_get

    def test_passes_when_hard_and_t07_submitted(self) -> None:
        doc = _FakeDoc(variance_severity="critical", annex_t07="AT07-26-00001")
        original_get = t07.frappe.db.get_value
        t07.frappe.db.get_value = lambda *a, **k: 1  # docstatus = Submitted
        try:
            t07.require_t07_for_hard_variance(doc)
        finally:
            t07.frappe.db.get_value = original_get


if __name__ == "__main__":
    unittest.main()
