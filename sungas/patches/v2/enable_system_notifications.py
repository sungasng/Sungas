"""Patch 0018 -- every enabled email Notification rule also rings the bell."""
import frappe


def execute():
    for name in frappe.get_all(
        "Notification", filters={"enabled": 1, "channel": "Email", "send_system_notification": 0}, pluck="name"
    ):
        frappe.db.set_value("Notification", name, "send_system_notification", 1, update_modified=False)
