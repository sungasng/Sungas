"""sungas.overrides.returns_approval_gate
==========================================

Wave R-1 -- Returns Manager Approval Gate.

Requires a supervisor-tier role to submit any return document
(Sales Invoice with `is_return=1` or POS Invoice with `is_return=1`).
Ordinary cashiers can DRAFT a return but the submission must be done
by (or on behalf of) an approver.

Motivation: prevents a cashier from unilaterally clearing a suspicious
cash shortfall by ringing up an offsetting "return" against a real
customer sale. Every credit note now leaves a manager-owner audit
trail.

Bypass hierarchy (any one role is sufficient):
    - System Manager                 (super-admin, incident response)
    - Chief Operating Officer        (executive override)
    - LPG Head of Operations         (ops leadership)
    - LPG Plant Manager              (outlet supervisor)
    - Sales Manager                  (non-LPG sales channel)
    - Accounts Manager               (finance-driven credit notes)

Hooked at `before_submit` on Sales Invoice and POS Invoice
via hooks.py doc_events.
"""

from __future__ import annotations

import frappe  # type: ignore
from frappe import _


APPROVER_ROLES = (
    "System Manager",
    "Chief Operating Officer",
    "LPG Head of Operations",
    "LPG Plant Manager",
    "Sales Manager",
    "Accounts Manager",
)


def require_manager_for_return(doc, method=None) -> None:
    """before_submit hook: block return submission by non-approvers."""
    if not int(doc.get("is_return") or 0):
        return

    user_roles = set(frappe.get_roles(frappe.session.user))
    if user_roles.intersection(APPROVER_ROLES):
        return

    frappe.throw(
        _(
            "Returns must be submitted by a manager. Your current roles "
            "do not include any of the approved returns-approver roles "
            "({roles}). Please save this document as a Draft and hand it "
            "to your Plant Manager or Sales Manager for submission."
        ).format(roles=", ".join(APPROVER_ROLES)),
        title=_("Returns Approval Required"),
    )
