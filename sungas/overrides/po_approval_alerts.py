"""Patch 0032 -- tell each missing Purchase Order approver (bell, email, WhatsApp), once per PO and role."""
from __future__ import annotations

import frappe

STAMPS = {"sungas_hoo_approved_by": "hoo", "sungas_hof_approved_by": "hof",
          "sungas_coo_approved_by": "coo", "sungas_cpl_approved_by": "cpl"}


def notify_po_approvers(doc, method=None):
    """Purchase Order on_update (draft)."""
    if doc.docstatus != 0 or not doc.get("sungas_approval_tier") or frappe.flags.in_import:
        return
    from sungas.overrides.purchase_order_matrix import _policy, _required_stamps

    policy = _policy()
    if not policy.get("enabled"):
        return
    missing = [(f, label) for f, label in _required_stamps(doc.sungas_approval_tier, bool(doc.get("sungas_is_lpg")))
               if not doc.get(f)]
    if missing:
        frappe.enqueue("sungas.overrides.po_approval_alerts.send", queue="short", enqueue_after_commit=True,
                       po=doc.name, missing=missing, roles={f: policy["roles"][STAMPS[f]] for f, _ in missing})


def send(po, missing, roles):
    from sungas.utils import whatsapp
    from sungas.utils.bell import ring

    doc = frappe.get_doc("Purchase Order", po)
    link = whatsapp.doc_url("Purchase Order", po)
    for field, label in missing:
        subject = f"Approval needed - Purchase Order {po} ({label})"
        users = [u for u in frappe.get_all("Has Role", filters={"role": roles[field], "parenttype": "User"},
                                           pluck="parent", distinct=True)
                 if frappe.db.get_value("User", u, "enabled") and u not in ("Administrator", "lmd-bot@sungas.org")]
        users = [u for u in users if not frappe.db.exists("Notification Log", {"for_user": u, "subject": subject})]
        if not users:
            continue
        body = (f"<p>Purchase Order <b>{po}</b> ({doc.supplier}, NGN {doc.grand_total:,.2f}, Tier {doc.sungas_approval_tier}) "
                f"needs your approval as <b>{label}</b>.</p><p><a href=\"{link}\">Open purchase order</a></p>")
        ring(users, subject, body, "Purchase Order", po)
        try:
            frappe.sendmail(recipients=[frappe.db.get_value("User", u, "email") or u for u in users],
                            subject=f"[SCL] {subject}", message=body, now=False)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "sungas.po_approval_alerts email")
        from sungas.approval_link import make

        for u in users:
            if not whatsapp.phone_for(u):
                continue
            whatsapp.send([u], "sungas_approval_needed", {
                "approver_name": whatsapp.first_name(u), "doc_label": f"Purchase Order {po}",
                "summary": f"{doc.supplier}, NGN {doc.grand_total:,.0f}, Tier {doc.sungas_approval_tier}",
                "state": f"waiting for {label} - tap the link to approve or reject",
                "link": make(u, "Purchase Order", po, field)}, ref=f"PO:{po}:{field}")
