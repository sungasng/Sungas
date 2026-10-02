"""sungas.overrides.pr_auto_draft_se
=====================================

Wave PR-2 (Patch 0011) -- Auto Draft SE spawn on Purchase Receipt submit.

Business flow (per user manual "Receiving LPG v1"):
    1. HO Inventory Officer drafts a PR with
       `set_warehouse = 'Goods in Transit from Suppliers - SCL'`.
    2. HoO approves (workflow), HoF/Accountant submits.
    3. On submit, this hook spawns a Draft Stock Entry
       (Material Transfer) from GIT-Suppliers -> the destination
       plant (custom field `final_destination_warehouse`).
    4. Plant team physically counts, then submits the SE. That
       triggers the existing "SE Sync PR Discharge Totals" and
       "Outlet SE Open Transit Loss Case" server scripts to update
       partial-discharge tracking + open variance cases on shortfall.

Idempotent: skips if a Draft/Submitted SE already back-references
this PR via `pr_reference_new`.

Safe: never throws -- on_submit failures would leave PR submitted
but request 500. All errors log_error'd and swallowed.
"""

from __future__ import annotations

import frappe  # type: ignore

GIT_SUPPLIERS_WAREHOUSE = "Goods in Transit from Suppliers - SCL"
DEFAULT_HOI_COST_CENTER = "70003 - Procurement - SCL"


def spawn_git_to_plant_se(doc, method=None) -> None:
    """on_submit hook for Purchase Receipt. Never throws.

    Always leaves a Comment on the PR describing what happened
    (spawned / skipped / errored) so users can self-diagnose from
    the PR's Activity tab without needing Error Log access.
    """
    try:
        if not _should_spawn(doc):
            _comment(doc, (
                "[Auto Draft SE] Skipped: PR did not match spawn rule "
                f"(set_warehouse={doc.get('set_warehouse')!r}, "
                f"final_destination_warehouse={doc.get('final_destination_warehouse')!r})."
            ))
            return

        # Idempotency: skip if we already spawned an SE for this PR
        existing = frappe.get_all(
            "Stock Entry",
            filters={"pr_reference_new": doc.name, "docstatus": ["<", 2]},
            pluck="name",
            limit=1,
        )
        if existing:
            _comment(doc, (
                f"[Auto Draft SE] Skipped: Stock Entry <b>{existing[0]}</b> "
                "already exists for this PR (idempotent)."
            ))
            return

        destination = doc.get("final_destination_warehouse")
        cost_center = _resolve_cost_center()

        se = frappe.new_doc("Stock Entry")
        se.stock_entry_type = "Material Transfer"
        se.purpose = "Material Transfer"
        se.company = doc.company
        se.from_warehouse = GIT_SUPPLIERS_WAREHOUSE
        se.to_warehouse = destination
        se.pr_reference = doc.name
        se.pr_reference_new = doc.name
        se.pr_hauler = doc.get("hauler")
        se.pr_truck_registration = doc.get("truck_registration")
        se.pr_waybill_number = doc.get("waybill_number")
        se.is_pr_discharge = 1
        se.posting_date = frappe.utils.today()
        se.set_posting_time = 0

        for row in (doc.items or []):
            # PurchaseReceiptItem has `rate` (+ `base_rate`), NOT `basic_rate`.
            # `basic_rate` is a Stock Entry Detail field. Resolve the price
            # defensively across all possible PR-side fieldnames.
            unit_rate = (
                row.get("rate")
                or row.get("base_rate")
                or row.get("net_rate")
                or 0
            )
            se.append("items", {
                "item_code": row.item_code,
                "qty": row.qty,
                "uom": row.uom or "Kg",
                "stock_uom": row.stock_uom or "Kg",
                "conversion_factor": row.conversion_factor or 1,
                "s_warehouse": GIT_SUPPLIERS_WAREHOUSE,
                "t_warehouse": destination,
                "basic_rate": unit_rate,
                "cost_center": cost_center,
            })

        se.insert(ignore_permissions=True)

        _comment(doc, (
            f"[Auto Draft SE] Spawned Draft Stock Entry <b>{se.name}</b> "
            f"(GIT-Suppliers &rarr; {destination}) for plant team to receive. "
            f"Cost center: {cost_center}."
        ))

        # Notify destination plant manager
        _notify_destination_plant_manager(doc, se, destination)

    except Exception:
        err = frappe.get_traceback()
        frappe.log_error(
            title="pr_auto_draft_se.spawn_git_to_plant_se failed",
            message=err,
        )
        try:
            _comment(doc, (
                "[Auto Draft SE] <b>FAILED</b> to spawn Stock Entry. "
                "See Error Log for traceback. Message: "
                f"<code>{frappe.utils.strip_html(str(err)[-500:])}</code>"
            ))
        except Exception:
            pass


def _comment(doc, html: str) -> None:
    """Idempotent audit comment on the PR. Swallows errors."""
    try:
        frappe.get_doc({
            "doctype": "Comment",
            "comment_type": "Info",
            "reference_doctype": "Purchase Receipt",
            "reference_name": doc.name,
            "content": html,
        }).insert(ignore_permissions=True)
    except Exception:
        pass


def _should_spawn(doc) -> bool:
    """Only spawn for PRs routed through GIT-Suppliers with a destination set."""
    if not doc.get("final_destination_warehouse"):
        return False
    if doc.get("final_destination_warehouse") == GIT_SUPPLIERS_WAREHOUSE:
        return False
    # PR must have items
    if not (doc.items or []):
        return False
    return True


def _resolve_cost_center() -> str:
    """Pull the HO Procurement cost center from Sungas Procurement Policy;
    fall back to the hard-coded default so hooks never break."""
    try:
        policy = frappe.get_single("Sungas Procurement Policy")
        cc = policy.get("hoi_cost_center")
        if cc:
            return cc
    except Exception:
        pass
    return DEFAULT_HOI_COST_CENTER


def _notify_destination_plant_manager(pr_doc, se_doc, destination_warehouse: str) -> None:
    """Best-effort in-app notification + ToDo for the plant manager
    of the destination warehouse. Never throws."""
    try:
        wh = frappe.get_doc("Warehouse", destination_warehouse)
        recipients = []
        for candidate in (wh.get("outlet_plant_manager"), wh.get("outlet_secondary_manager")):
            if candidate and "@" in candidate and candidate not in recipients:
                recipients.append(candidate)

        if not recipients:
            return

        subject = (
            f"Incoming LPG receipt: PR {pr_doc.name} destined for {destination_warehouse}"
        )
        message = (
            f"<p>A Purchase Receipt has been submitted at Head Office and is heading to "
            f"<b>{destination_warehouse}</b>.</p>"
            f"<ul>"
            f"<li><b>PR:</b> {pr_doc.name}</li>"
            f"<li><b>Waybill:</b> {pr_doc.get('waybill_number') or '-'}</li>"
            f"<li><b>Hauler:</b> {pr_doc.get('hauler') or '-'}</li>"
            f"<li><b>Truck:</b> {pr_doc.get('truck_registration') or '-'}</li>"
            f"<li><b>Waybill Qty:</b> {pr_doc.get('total_qty') or 0} kg</li>"
            f"<li><b>Draft Stock Entry:</b> {se_doc.name} "
            f"(please physically count on arrival, then submit)</li>"
            f"</ul>"
        )

        for user in recipients:
            frappe.get_doc({
                "doctype": "ToDo",
                "reference_type": "Stock Entry",
                "reference_name": se_doc.name,
                "allocated_to": user,
                "description": message,
                "priority": "Medium",
                "status": "Open",
            }).insert(ignore_permissions=True)

        # Best-effort email as well (non-blocking)
        try:
            frappe.sendmail(
                recipients=recipients,
                subject=subject,
                message=message,
                reference_doctype="Stock Entry",
                reference_name=se_doc.name,
                now=False,
            )
        except Exception:
            frappe.log_error(
                title="pr_auto_draft_se.notify email failed",
                message=frappe.get_traceback(),
            )

    except Exception:
        frappe.log_error(
            title="pr_auto_draft_se._notify_destination_plant_manager failed",
            message=frappe.get_traceback(),
        )
