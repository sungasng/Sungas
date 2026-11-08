"""Patch 0018 -- bell helpers for the LMD WhatsApp companion."""
from __future__ import annotations

import frappe


@frappe.whitelist(methods=["POST"])
def mark_document_read(doctype: str, name: str) -> dict:
    """Mark every unread bell alert for this document as read (all users).

    Called by LMD after someone acts from a WhatsApp magic link so the same
    item does not keep nagging in the ERPNext bell.
    """
    frappe.only_for("System Manager")
    logs = frappe.get_all(
        "Notification Log",
        filters={"document_type": doctype, "document_name": name, "read": 0},
        pluck="name",
    )
    for log in logs:
        frappe.db.set_value("Notification Log", log, "read", 1, update_modified=False)
    return {"ok": True, "marked": len(logs)}
