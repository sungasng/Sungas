"""Patch 0062 -- a cashier asks for a receipt to be cancelled (with a reason); finance approves or declines.

Cashiers no longer hold Cancel on POS Invoice. A receipt can be cancelled only while its shift is open
(before it is closed into the day's sales); after that it is a return, and the request expires.
"""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, get_url_to_form, now_datetime

CR = "Sungas Cancellation Request"
FINANCE = {"LPG Head of Finance", "Accounts Manager"}
FINANCE_STAFF = "Accounts User"  # finance staff, but Plant Managers also hold it and are excluded


def can_decide(user=None) -> bool:
    roles = set(frappe.get_roles(user))
    return bool(roles & (FINANCE | {"System Manager"})) or (FINANCE_STAFF in roles and "LPG Plant Manager" not in roles)


def _finance_users() -> list[str]:
    users = set(frappe.get_all("Has Role", filters={"role": ["in", list(FINANCE | {FINANCE_STAFF})], "parenttype": "User"},
                               pluck="parent"))
    return sorted(u for u in users if u not in ("Administrator", "lmd-bot@sungas.org")
                  and frappe.db.get_value("User", u, "enabled") and can_decide(u))


def _bell(users, subject, name):
    for u in users:
        frappe.get_doc({"doctype": "Notification Log", "for_user": u, "type": "Alert", "subject": subject,
                        "document_type": CR, "document_name": name}).insert(ignore_permissions=True)


def _closed_into_sales(inv) -> bool:
    return bool(inv.get("consolidated_invoice")) or inv.status == "Consolidated"


@frappe.whitelist(methods=["POST"])
def request(invoice: str, reason: str) -> dict:
    reason = (reason or "").strip()
    if len(reason) < 5:
        frappe.throw(_("Write the reason for cancelling this receipt."))
    if not frappe.db.exists("POS Invoice", invoice):
        frappe.throw(_("Receipt {0} not found.").format(invoice))
    inv = frappe.get_doc("POS Invoice", invoice)
    if inv.docstatus != 1:
        frappe.throw(_("Only a completed (submitted) receipt can be cancelled."))
    if inv.is_return:
        frappe.throw(_("{0} is a return, not a sale.").format(invoice))
    if _closed_into_sales(inv):
        frappe.throw(_("{0} is already closed into the day's sales. Ask the Plant Manager to record a return.").format(invoice))
    if frappe.db.exists(CR, {"pos_invoice": invoice, "status": "Pending"}):
        frappe.throw(_("A cancellation request for {0} is already waiting for Finance.").format(invoice))
    doc = frappe.get_doc({"doctype": CR, "pos_invoice": invoice, "pos_profile": inv.pos_profile,
                          "customer": inv.customer_name or inv.customer, "amount": inv.grand_total,
                          "requested_by": frappe.session.user, "reason": reason, "status": "Pending"})
    doc.insert(ignore_permissions=True)
    _bell(_finance_users(), f"Cancel receipt {invoice} (NGN {flt(inv.grand_total):,.2f}) at {inv.pos_profile}? {reason[:80]}",
          doc.name)
    return {"name": doc.name, "message": _("Request {0} sent to Finance. The receipt stays valid until they approve.").format(doc.name)}


@frappe.whitelist(methods=["POST"])
def decide(name: str, approve: int = 1, note: str = "") -> dict:
    if not can_decide():
        frappe.throw(_("Only Finance approves receipt cancellations."), frappe.PermissionError)
    doc = frappe.get_doc(CR, name)
    if doc.status != "Pending":
        frappe.throw(_("{0} is already {1}.").format(name, doc.status))
    if doc.requested_by == frappe.session.user:
        frappe.throw(_("You cannot decide on your own request."))
    approve = int(approve)
    if not approve and not (note or "").strip():
        frappe.throw(_("Write why the request is declined."))
    inv = frappe.get_doc("POS Invoice", doc.pos_invoice)
    status = "Declined"
    if approve:
        if _closed_into_sales(inv):
            status = "Expired"
            note = (note + " " if note else "") + "Receipt was already closed into the day's sales; record a return."
        elif inv.docstatus == 1:
            inv.flags.ignore_permissions = True
            inv.add_comment("Info", f"Cancelled on request {name} ({doc.reason}) approved by {frappe.session.user}.")
            inv.cancel()
            status = "Approved"
    doc.db_set({"status": status, "decided_by": frappe.session.user, "decided_on": now_datetime(),
                "decision_note": (note or "").strip()})
    _bell([doc.requested_by], f"Cancellation of {doc.pos_invoice}: {status}. {(note or '')[:80]}", name)
    msg = {"Approved": _("{0} is cancelled."), "Declined": _("Request declined; {0} stays valid."),
           "Expired": _("{0} was already closed into the day's sales; record a return instead.")}[status]
    return {"status": status, "message": msg.format(doc.pos_invoice), "link": get_url_to_form(CR, name)}
