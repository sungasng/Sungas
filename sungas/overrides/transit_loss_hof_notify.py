"""sungas.overrides.transit_loss_hof_notify
============================================

Patch 0013 (A) -- when a Transit Loss Variance Case gets its
`resolution` set to 'Written Off' AND the HoF stamp is still empty,
fire a ToDo + email to every user with the LPG Head of Finance role
so the write-off doesn't rot in Draft.

Idempotent per-case: once a ToDo exists for this case + HoF user +
status Open, we don't create another one. The `on_update` hook runs
on every save but only acts on the transition into 'Written Off'
with no prior ToDo.

Never throws.
"""

from __future__ import annotations

import frappe  # type: ignore

HOF_ROLE = "LPG Head of Finance"


def notify_hof_on_writeoff_pending(doc, method=None) -> None:
    """on_update hook for Transit Loss Variance Case. Never throws."""
    try:
        if doc.docstatus != 0:
            return
        if doc.get("resolution") != "Written Off":
            return
        if doc.get("hod_finance_signed_by"):
            return

        hof_users = _collect_hof_users()
        if not hof_users:
            frappe.log_error(
                title="Transit Loss HoF Gate: no HoF user to notify",
                message=(
                    f"Transit Loss Variance Case {doc.name} is awaiting write-off "
                    f"approval but no user carries the {HOF_ROLE} role. "
                    "Assign the role to the HoF user to clear the gate."
                ),
            )
            return

        subject = (
            f"Transit Loss write-off pending your approval: {doc.name} "
            f"(\u20a6{(doc.get('shortfall_value') or 0):,.2f})"
        )
        case_url = f"/app/transit-loss-variance-case/{doc.name}"
        message = (
            f"<p>Transit Loss Variance Case <a href='{case_url}'>{doc.name}</a> "
            f"is proposed to be <b>written off</b> and requires your sign-off "
            f"as Head of Finance before it can be submitted.</p>"
            f"<ul>"
            f"<li><b>Shortfall:</b> {doc.get('qty_shortfall') or 0} kg "
            f"(\u20a6{(doc.get('shortfall_value') or 0):,.2f})</li>"
            f"<li><b>Destination:</b> {doc.get('destination_warehouse') or '-'}</li>"
            f"<li><b>PR:</b> {doc.get('purchase_receipt') or '-'}</li>"
            f"<li><b>Hauler:</b> {doc.get('hauler') or '-'}</li>"
            f"</ul>"
            f"<p>Open the case and click <b>Approvals &rarr; Approve Write-Off as HoF</b>.</p>"
        )

        for user in hof_users:
            # Idempotent: skip if an Open ToDo already exists for this user+case
            if frappe.db.exists(
                "ToDo",
                {
                    "reference_type": "Transit Loss Variance Case",
                    "reference_name": doc.name,
                    "allocated_to": user,
                    "status": "Open",
                },
            ):
                continue

            frappe.get_doc({
                "doctype": "ToDo",
                "reference_type": "Transit Loss Variance Case",
                "reference_name": doc.name,
                "allocated_to": user,
                "description": message,
                "priority": "High",
                "status": "Open",
            }).insert(ignore_permissions=True)

        try:
            frappe.sendmail(
                recipients=hof_users,
                subject=subject,
                message=message,
                reference_doctype="Transit Loss Variance Case",
                reference_name=doc.name,
                now=False,
            )
        except Exception:
            frappe.log_error(
                title="Transit Loss HoF notify email failed",
                message=frappe.get_traceback(),
            )

    except Exception:
        frappe.log_error(
            title="transit_loss_hof_notify failed",
            message=frappe.get_traceback(),
        )


def _collect_hof_users() -> list[str]:
    rows = frappe.get_all(
        "Has Role",
        filters={"role": HOF_ROLE, "parenttype": "User"},
        fields=["parent"],
    )
    users = []
    for r in rows:
        u = r.parent
        if u and "@" in u and u != "Administrator" and u not in users:
            if frappe.db.get_value("User", u, "enabled"):
                users.append(u)
    return users
