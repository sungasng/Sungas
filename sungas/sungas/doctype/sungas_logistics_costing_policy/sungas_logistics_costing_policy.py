"""Sungas Logistics Costing Policy -- single doctype (Patch 0016).

IAS 2 trip cost pool configuration: clearing / accrual / unproductive /
variance accounts, default standard haulage rate, HQ Operations cost centre.
"""
import frappe
from frappe.model.document import Document

REQUIRED_ACCOUNTS = (
    "logistics_clearing_account",
    "unproductive_haulage_account",
    "haulage_variance_account",
    "freight_accrued_account",
)


class SungasLogisticsCostingPolicy(Document):
    def validate(self):
        if not self.policy_enabled:
            return
        missing = [f for f in REQUIRED_ACCOUNTS if not self.get(f)]
        if missing:
            frappe.throw(
                "Set every account before enabling the policy. Missing: "
                + ", ".join(self.meta.get_label(f) for f in missing)
            )
