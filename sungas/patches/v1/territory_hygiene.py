"""Patch v1 — Territory hygiene cleanup (Pricing Phase 0).

Two idempotent fixes ahead of the Pricing Wave build:

1. Set `Nigeria` territory's `is_group = 1`. It has 6 child regions but is
   currently flagged is_group=0, which breaks the standard ERPNext Selling
   module's tree-aware permission and report logic.

2. Merge duplicate `Ebute` territory into the canonical `Ebutte`:
     * Re-point every dependent record (LPG Outlet Price Tier, Customer,
       Address, POS Profile, POS Opening Shift, POS Closing Shift, POS
       Invoice, Sales Invoice, Sales Order, Delivery Note, Quotation,
       Lead, Opportunity) from `Ebute` to `Ebutte`.
     * Delete the `Ebute` territory.

Idempotent: re-running after success is a no-op (the duplicate is
already gone). Logs every re-point so the audit trail is clear.

Manual invocation::

    bench --site <site> execute sungas.patches.v1.territory_hygiene.execute
"""

from __future__ import annotations

import frappe  # type: ignore


CANONICAL = "Ebutte"
DUPLICATE = "Ebute"


# Tables that reference Territory via a `territory` field. Add to this list
# only if a future doctype starts storing the territory by name.
TERRITORY_REFERENCES: list[tuple[str, str]] = [
    ("LPG Outlet Price Tier", "territory"),
    ("Customer", "territory"),
    ("Address", "territory"),
    ("POS Profile", "territory"),
    ("POS Opening Shift", "territory"),
    ("POS Closing Shift", "territory"),
    ("POS Invoice", "territory"),
    ("Sales Invoice", "territory"),
    ("Sales Order", "territory"),
    ("Delivery Note", "territory"),
    ("Quotation", "territory"),
    ("Lead", "territory"),
    ("Opportunity", "territory"),
]


def execute() -> dict[str, object]:
    log: dict[str, object] = {"is_group_fixed": False, "merged": {}, "duplicate_deleted": False}

    # 1) Nigeria.is_group = 1 if not already
    if frappe.db.exists("Territory", "Nigeria"):
        if not frappe.db.get_value("Territory", "Nigeria", "is_group"):
            frappe.db.set_value("Territory", "Nigeria", "is_group", 1, update_modified=False)
            log["is_group_fixed"] = True

    # 2) Merge Ebute -> Ebutte (if duplicate still exists)
    if frappe.db.exists("Territory", DUPLICATE):
        if not frappe.db.exists("Territory", CANONICAL):
            frappe.log_error(
                f"territory_hygiene: canonical '{CANONICAL}' missing — aborting merge.",
                "Sungas Territory Hygiene",
            )
            return {**log, "aborted": "canonical_missing"}

        for doctype, field in TERRITORY_REFERENCES:
            if not frappe.db.exists("DocType", doctype):
                continue
            try:
                n = frappe.db.count(doctype, {field: DUPLICATE})
                if n:
                    frappe.db.sql(
                        f"UPDATE `tab{doctype}` SET {field} = %(c)s WHERE {field} = %(d)s",
                        {"c": CANONICAL, "d": DUPLICATE},
                    )
                    log["merged"][doctype] = n
            except Exception as e:
                frappe.log_error(
                    f"territory_hygiene: re-point failed on {doctype}: {e}",
                    "Sungas Territory Hygiene",
                )

        # Delete the duplicate Territory doc
        try:
            frappe.delete_doc("Territory", DUPLICATE, ignore_permissions=True, force=True)
            log["duplicate_deleted"] = True
        except Exception as e:
            frappe.log_error(
                f"territory_hygiene: delete '{DUPLICATE}' failed: {e}",
                "Sungas Territory Hygiene",
            )

    # Rebuild nested-set so the tree integrity holds after the change
    try:
        from frappe.utils.nestedset import rebuild_tree
        rebuild_tree("Territory")
    except Exception as e:
        frappe.log_error(
            f"territory_hygiene: nested-set rebuild failed: {e}",
            "Sungas Territory Hygiene",
        )

    frappe.db.commit()
    frappe.logger().info(f"territory_hygiene: {log}")
    return log
