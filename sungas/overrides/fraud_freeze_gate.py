"""sungas.overrides.fraud_freeze_gate
======================================

Wave F-1 -- Fraud Freeze: block non-cash settlement at frozen outlets.

When an outlet is flagged as "frozen" by the fraud / internal-audit
team (custom flag `posa_is_frozen` on POS Profile), any Sales Invoice
or POS Invoice from that outlet may only be settled in CASH. This
prevents fraudulent bank/POS/transfer settlements from clearing while
an investigation is in progress -- cash reconciliation is easier to
audit against physical drawer counts.

Behaviour:
    - Fires at `before_submit` on Sales Invoice and POS Invoice.
    - Detects the outlet via `pos_profile` on the doc.
    - If the POS Profile has `posa_is_frozen = 1`, every row in the
      `payments` child table must have `type == 'Cash'`. Any non-cash
      row (Bank, POS terminal, Transfer, Wallet, Cheque, ...) triggers
      a throw.
    - If the custom field is not present (fixture not yet installed),
      no-op silently -- this keeps the guard forward-compatible.

Bypass:
    - System Manager can override (incident response, cleanup).
"""

from __future__ import annotations

import frappe  # type: ignore
from frappe import _


BYPASS_ROLES = ("System Manager",)


def block_bank_payments_when_outlet_frozen(doc, method=None) -> None:
    """before_submit hook: enforce cash-only at frozen outlets."""
    pos_profile = doc.get("pos_profile")
    if not pos_profile:
        return

    # Forward-compat: if the freeze flag field isn't installed yet, skip.
    meta = frappe.get_meta("POS Profile")
    if not meta.has_field("posa_is_frozen"):
        return

    is_frozen = frappe.db.get_value("POS Profile", pos_profile, "posa_is_frozen")
    if not int(is_frozen or 0):
        return

    user_roles = set(frappe.get_roles(frappe.session.user))
    if user_roles.intersection(BYPASS_ROLES):
        return

    non_cash_rows = [
        p for p in (doc.get("payments") or [])
        if (p.get("type") or "").strip().lower() != "cash"
        and float(p.get("amount") or 0) > 0
    ]
    if not non_cash_rows:
        return

    modes = ", ".join(sorted({p.get("mode_of_payment") or "(unknown)" for p in non_cash_rows}))
    frappe.throw(
        _(
            "Outlet <b>{outlet}</b> is currently FROZEN pending fraud "
            "investigation. Only <b>Cash</b> settlements are permitted. "
            "The following non-cash payment modes were used and must be "
            "removed before submission: {modes}.<br><br>"
            "Contact the Head of Operations to lift the freeze."
        ).format(outlet=pos_profile, modes=modes),
        title=_("Outlet Frozen -- Cash Only"),
    )
