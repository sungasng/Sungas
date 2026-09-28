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

    # One indexed query. `docstatus` filter deliberately omitted so
    # even Draft workflow-state shifts count as unresolved.
    unresolved = frappe.db.get_all(
        "POS Closing Shift",
        filters={
            "user": cashier_user,
            "variance_severity": ["in", HARD_SEVERITIES],
            "workflow_state": ["!=", "Approved"],
        },
        fields=["name", "workflow_state", "variance_severity",
                "variance_amount", "period_end_date"],
        order_by="period_end_date desc",
        limit=1,
    )

    if not unresolved:
        return

    prior = unresolved[0]
    frappe.throw(
        _(
            "Cannot open a new POS shift while your previous shift has an "
            "unresolved {severity} variance.<br><br>"
            "Shift <a href='/app/pos-closing-shift/{name}'>{name}</a> "
            "(NGN {amount:,.2f}) is currently in "
            "<b>{state}</b> and must be Approved before you can open a "
            "new shift. Please escalate to your Plant Manager or the "
            "Head of Operations."
        ).format(
            severity=prior.variance_severity,
            name=prior.name,
            amount=float(prior.variance_amount or 0),
            state=prior.workflow_state or "Draft",
        ),
        title=_("Cashier Locked -- Unresolved Variance"),
    )
