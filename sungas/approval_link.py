"""Patch 0033 -- one-tap approvals from WhatsApp (no login).

The WhatsApp link carries a random token (only its SHA-256 is stored). It is tied to one
approver, one document and the state it was sent for; it works once, expires after 24 h and
dies as soon as the document moves on. Opening the link (GET) only shows the page -- link
previews cannot approve. The action runs as the approver, so normal role checks apply.
"""
from __future__ import annotations

import hashlib
import secrets

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import add_to_date, escape_html, get_datetime, now_datetime

LINK_DT = "Sungas Approval Link"
MAGIC_DOCTYPES = {"LPG Price Change Request", "LPG Bulk Price Upload", "Purchase Order"}
TTL_HOURS = 24
PO_STAMPS = {"sungas_hoo_approved_by": ("hoo", "sungas_hoo_approved_on"),
             "sungas_hof_approved_by": ("hof", "sungas_hof_approved_on"),
             "sungas_coo_approved_by": ("coo", "sungas_coo_approved_on"),
             "sungas_cpl_approved_by": ("cpl", "sungas_cpl_approved_on")}


def _hash(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def make(user: str, doctype: str, name: str, state: str) -> str:
    """Create a link for one approver; returns the URL to put in the WhatsApp message."""
    token = secrets.token_urlsafe(32)
    frappe.get_doc({"doctype": LINK_DT, "token_hash": _hash(token), "user": user, "ref_doctype": doctype,
                    "ref_name": name, "state": state,
                    "expires_on": add_to_date(now_datetime(), hours=TTL_HOURS)}).insert(ignore_permissions=True)
    return frappe.utils.get_url(f"/approve?t={token}")


def link_for(user, doctype, name, state, actions=("Approve", "Reject")) -> str | None:
    if doctype in MAGIC_DOCTYPES and set(actions) <= {"Approve", "Reject"}:
        try:
            return make(user, doctype, name, state)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "sungas.approval_link.make")
    return None


def _still_pending(link, doc) -> bool:
    if link.ref_doctype == "Purchase Order":
        return doc.docstatus == 0 and not doc.get(link.state)
    return doc.get("workflow_state") == link.state


def check(token):
    """(link, doc, None) or (None, None, reason)."""
    name = frappe.db.get_value(LINK_DT, {"token_hash": _hash(token)}) if token else None
    if not name:
        return None, None, _("This approval link is not valid.")
    link = frappe.get_doc(LINK_DT, name)
    if link.used_on:
        return None, None, _("This link was already used ({0}).").format(link.used_action)
    if get_datetime(link.expires_on) < now_datetime():
        return None, None, _("This link has expired. Open the document in the ERP instead.")
    if not frappe.db.get_value("User", link.user, "enabled"):
        return None, None, _("This approver's account is disabled.")
    doc = frappe.get_doc(link.ref_doctype, link.ref_name)
    if not _still_pending(link, doc):
        return None, None, _("{0} {1} has already moved on - nothing left for you to do here.").format(
            link.ref_doctype, link.ref_name)
    return link, doc, None


def summary(doc) -> list[tuple[str, str]]:
    money = lambda v: f"NGN {float(v or 0):,.2f}"  # noqa: E731
    if doc.doctype == "Purchase Order":
        rows = [("Supplier", doc.supplier), ("Total", money(doc.grand_total)),
                ("Approval tier", doc.get("sungas_approval_tier") or "-"), ("Required by", str(doc.schedule_date or "-"))]
        rows += [(f"Item {i}", f"{it.item_code} x {it.qty:g} @ {money(it.rate)}") for i, it in enumerate(doc.items[:5], 1)]
        if len(doc.items) > 5:
            rows.append(("", f"... and {len(doc.items) - 5} more lines"))
        return rows
    if doc.doctype == "LPG Bulk Price Upload":
        rows = [("Description", doc.get("description") or "-"), ("Rows", str(doc.get("total_rows") or len(doc.rows))),
                ("Flagged (big change)", str(doc.get("flagged_rows") or 0)), ("Raised by", doc.owner)]
        rows += [(r.item_code, f"{r.customer_group} / {r.territory}: {money(r.current_rate)} -> {money(r.new_rate)}")
                 for r in doc.rows[:8]]
        if len(doc.rows) > 8:
            rows.append(("", f"... and {len(doc.rows) - 8} more rows"))
        return rows
    fields = [("Item", "item_code"), ("Customer group", "customer_group"), ("Territory", "territory"),
              ("Current rate", "current_rate"), ("New rate", "new_rate"), ("Change %", "pct_change"),
              ("Reason", "justification")]
    out = [(label, money(doc.get(f)) if f.endswith("rate") else str(doc.get(f)))
           for label, f in fields if doc.get(f) not in (None, "")]
    return out + [("Raised by", doc.owner)]


def page_context(token) -> dict:
    link, doc, reason = check(token)
    if reason:
        return {"ok": False, "reason": reason}
    return {"ok": True, "token": token, "title": f"{link.ref_doctype} {link.ref_name}", "state": link.state
            if link.ref_doctype != "Purchase Order" else "Waiting for your approval",
            "approver": frappe.db.get_value("User", link.user, "full_name") or link.user,
            "rows": [(escape_html(k), escape_html(v)) for k, v in summary(doc)],
            "desk_url": frappe.utils.get_url(f"/app/{frappe.scrub(link.ref_doctype).replace('_', '-')}/{link.ref_name}")}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=30, seconds=3600)
def act(t, action, note=None):
    if action not in ("Approve", "Reject"):
        frappe.throw(_("Unknown action."))
    if action == "Reject" and not (note or "").strip():
        frappe.throw(_("Please give a reason for rejecting."))
    link, doc, reason = check(t)
    if reason:
        frappe.throw(reason)
    guest = frappe.session.user
    frappe.set_user(link.user)
    try:
        if link.ref_doctype == "Purchase Order":
            _po(link, doc, action, note)
        else:
            from frappe.model.workflow import apply_workflow

            if note:
                doc.add_comment("Comment", f"{action} via WhatsApp: {note}")
            apply_workflow(doc, action)
        frappe.db.set_value(LINK_DT, link.name, {"used_on": now_datetime(), "used_action": action,
                                                 "used_ip": frappe.local.request_ip}, update_modified=False)
        frappe.db.commit()
    finally:
        frappe.set_user(guest)
    return {"ok": True, "message": _("{0} {1}: {2} recorded. Thank you.").format(link.ref_doctype, link.ref_name,
                                                                               "approval" if action == "Approve" else "rejection")}


def _po(link, doc, action, note):
    from sungas.overrides.purchase_order_matrix import _approve

    if action == "Approve":
        key, on_field = PO_STAMPS[link.state]
        _approve(doc.name, key, link.state, on_field)
        doc.add_comment("Comment", "Approved via WhatsApp link" + (f": {note}" if note else ""))
        return
    doc.add_comment("Comment", f"Rejected via WhatsApp link: {note}")
    from sungas.utils import whatsapp
    from sungas.utils.bell import ring

    who = frappe.db.get_value("User", link.user, "full_name") or link.user
    ring([doc.owner], f"Purchase Order {doc.name} rejected by {who}", f"<p>Reason: {escape_html(note)}</p>",
         "Purchase Order", doc.name)
    whatsapp.workflow_update("Purchase Order", doc.name, doc.owner, f"rejected by {who} ({note})")
