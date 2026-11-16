"""sungas.overrides.cashier_variance_lockout
=============================================

Guards POS Opening Shift creation: a cashier cannot open a new shift
while their most recent closing shift sits at block or critical variance
and has NOT yet been approved through the full workflow chain.

Wave B-11 (Feb 2026). Motivated by production incident 2026-02: cashier
Peace Effiong had a N250,000 shortage on POSA-CS-26-0000017 (critical
severity) and was able to open a fresh POS Opening Shift and keep
transacting while the variance was still under Plant Manager / Finance
review. Business risk: compounding shortages across successive shifts,
inability to hold cashier accountable in real-time.

Guard is at `before_insert` on POS Opening Shift. Bypassed for admin
roles (System Manager, LPG Head of Operations, Chief Operating Officer)
so those roles can rescue-open a shift when business context demands
(e.g. cashier reallocated to a different outlet mid-investigation).

Regression tests: /app/backend/tests/test_sungas_cashier_variance_lockout.py
"""

from __future__ import annotations

import frappe  # type: ignore
from frappe import _


HARD_SEVERITIES = ("block", "critical")

# Roles that can override the guard. Kept narrow -- LPG Plant Manager
# is intentionally OFF the bypass list because a PM opening for their
# own cashier subverts the control.
BYPASS_ROLES = (
    "System Manager",
    "LPG Head of Operations",
    "Chief Operating Officer",
)


def enforce_cashier_variance_lockout(doc, method=None) -> None:
    """before_insert hook: block if cashier has an unresolved hard variance.

    An "unresolved hard variance" is any POS Closing Shift for this
    cashier where:
        variance_severity IN ('block','critical')
        AND workflow_state != 'Approved'

    (Rejected shifts are still "unresolved" from an ops POV -- the
    cashier hasn't recounted or filed the variance investigation.)
    """
    # Bypass for admin roles -- they own the escalation channel.
    user_roles = frappe.get_roles(frappe.session.user)
    if any(r in BYPASS_ROLES for r in user_roles):
        return

    cashier_user = doc.get("user")
    if not cashier_user:
        # Opening shift without a cashier link (rare, but defer to
        # Frappe's built-in required-field validation elsewhere).
        return

    # Patch 0060: closes no longer wait for an approval (0052/0053), so the old
    # "closing shift not Approved" test locked every such cashier for good.
    # She is now held only until she has signed her statement on the open case.
    unresolved = frappe.db.get_all(
        "POS Variance Investigation",
        filters={
            "cashier": cashier_user,
            "docstatus": 0,
            "variance_severity": ["in", HARD_SEVERITIES],
            "cashier_signed_by": ["is", "not set"],
            "cashier_unavailable": 0,
        },
        fields=["name", "shift", "variance_severity", "variance_amount"],
        order_by="creation desc",
        limit=1,
    )

    if not unresolved:
        return

    case = unresolved[0]
    frappe.throw(
        _(
            "Your last shift close ({shift}) has a {severity} cash difference "
            "(NGN {amount:,.2f}) and you have not yet written your statement.<br><br>"
            "Open variance case <a href='/app/pos-variance-investigation/{name}'>{name}</a>, "
            "write what happened, press <b>Save</b>, then <b>Sign my statement</b>. "
            "You can open your till straight after. If you need help, tell your "
            "Plant Manager or the Head of Operations."
        ).format(
            shift=case.shift,
            severity=case.variance_severity,
            name=case.name,
            amount=abs(float(case.variance_amount or 0)),
        ),
        title=_("Sign your statement to open the till"),
    )
