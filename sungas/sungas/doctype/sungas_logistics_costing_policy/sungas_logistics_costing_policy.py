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
        seen = set()
        for row in self.get("route_rates") or []:
            if row.from_outlet == row.to_outlet:
                frappe.throw(f"Route Rates row {row.idx}: From and To outlet must differ.")
            if (row.rate_per_kg or 0) < 0:
                frappe.throw(f"Route Rates row {row.idx}: rate cannot be negative.")
            key = (row.from_outlet, row.to_outlet)
            if key in seen:
                frappe.throw(f"Route Rates row {row.idx}: duplicate route {row.from_outlet} -> {row.to_outlet}.")
            seen.add(key)
        if not self.policy_enabled:
            return
        missing = [f for f in REQUIRED_ACCOUNTS if not self.get(f)]
        if missing:
            frappe.throw(
                "Set every account before enabling the policy. Missing: "
                + ", ".join(self.meta.get_label(f) for f in missing)
            )
