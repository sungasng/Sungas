"""Patch v2 — Rename `Annex T-07 Worksheet` -> `POS Variance Investigation`.

Runs on `bench migrate`. Steps (idempotent, safe to re-run):

  1. Rename doctype `Annex T-07 Worksheet` -> `POS Variance Investigation`
     using Frappe's built-in `rename_doc()`. Existing docs
     (e.g. AT07-26-00058) are preserved -- they keep their old
     autoname but now live under the new URL.
  2. Rename custom field `annex_t07` -> `pos_variance_investigation`
     on POS Closing Shift, and update its options string to reference
     the new doctype name.
  3. Drop the `Annex T-07 Denomination Row` child doctype (denomination
     counts have been dropped from the schema -- payment mix now
     mixes cash + card + POS transfer + bank transfer, denominations
     were a legacy paper-form artifact).
  4. Rename print format `annex_t_07_audit_archive` ->
     `pos_variance_investigation_audit_archive` and re-point its
     `doc_type` to the new doctype.
  5. Delete orphan blank draft investigations (those with no shift
     linked -- created earlier when manual "New" clicks bypassed the
     auto-create path).

Manual invocation::

    bench --site <site> execute sungas.patches.v2.rename_annex_t07_to_pos_variance_investigation.execute
"""

from __future__ import annotations

import frappe  # type: ignore
from frappe.model.rename_doc import rename_doc


OLD_DOCTYPE = "Annex T-07 Worksheet"
NEW_DOCTYPE = "POS Variance Investigation"
OLD_CHILD_DOCTYPE = "Annex T-07 Denomination Row"
OLD_LINK_FIELD = "annex_t07"
NEW_LINK_FIELD = "pos_variance_investigation"
OLD_PRINT_FORMAT = "annex_t_07_audit_archive"
NEW_PRINT_FORMAT = "pos_variance_investigation_audit_archive"


def execute() -> dict[str, object]:
    result: dict[str, object] = {"steps": []}

    # -------- 1. Rename the doctype -----------------------------------
    if frappe.db.exists("DocType", OLD_DOCTYPE) and not frappe.db.exists(
        "DocType", NEW_DOCTYPE
    ):
        try:
            rename_doc(
                "DocType", OLD_DOCTYPE, NEW_DOCTYPE,
                force=True, merge=False, ignore_permissions=True,
            )
            result["steps"].append(f"renamed doctype {OLD_DOCTYPE} -> {NEW_DOCTYPE}")
        except Exception as exc:
            frappe.log_error(
                title="Sungas rename patch",
                message=f"doctype rename failed: {exc}\n{frappe.get_traceback()}",
            )
            result["steps"].append(f"doctype rename ERRORED: {exc}")
            return result
    elif frappe.db.exists("DocType", NEW_DOCTYPE):
        result["steps"].append("doctype already renamed")
    else:
        result["steps"].append("legacy doctype not present; nothing to rename")

    # -------- 2. Rename the custom field on POS Closing Shift ---------
    old_cf_name = f"POS Closing Shift-{OLD_LINK_FIELD}"
    new_cf_name = f"POS Closing Shift-{NEW_LINK_FIELD}"
    if frappe.db.exists("Custom Field", old_cf_name):
        # Update fieldname + options + label + name.
        frappe.db.set_value(
            "Custom Field", old_cf_name,
            {
                "fieldname": NEW_LINK_FIELD,
                "label": "POS Variance Investigation",
                "options": NEW_DOCTYPE,
            },
            update_modified=False,
        )
        # Also rename the Custom Field doc itself so future fixture syncs
        # find it by the new name.
        rename_doc(
            "Custom Field", old_cf_name, new_cf_name,
            force=True, merge=False, ignore_permissions=True,
        )
        # Rename the physical column on tabPOS Closing Shift.
        try:
            frappe.db.sql(
                f"""ALTER TABLE `tabPOS Closing Shift`
                    CHANGE COLUMN `{OLD_LINK_FIELD}` `{NEW_LINK_FIELD}` VARCHAR(140)"""
            )
            result["steps"].append(
                f"renamed column {OLD_LINK_FIELD} -> {NEW_LINK_FIELD}"
            )
        except Exception as exc:
            # Column may already have been renamed on a previous run.
            result["steps"].append(f"column rename skipped: {exc}")
        result["steps"].append(f"renamed custom field {old_cf_name} -> {new_cf_name}")
    elif frappe.db.exists("Custom Field", new_cf_name):
        result["steps"].append("custom field already renamed")
    else:
        result["steps"].append("legacy custom field not present")

    # -------- 3. Drop the denomination child doctype ------------------
    if frappe.db.exists("DocType", OLD_CHILD_DOCTYPE):
        # Delete any residual rows (parent doctype no longer has the
        # `denominations` table field, so these are already orphans).
        try:
            frappe.db.sql(f"DROP TABLE IF EXISTS `tab{OLD_CHILD_DOCTYPE}`")
        except Exception as exc:
            result["steps"].append(f"drop child table skipped: {exc}")
        frappe.delete_doc(
            "DocType", OLD_CHILD_DOCTYPE,
            force=True, ignore_permissions=True,
        )
        result["steps"].append(f"deleted doctype {OLD_CHILD_DOCTYPE}")
    else:
        result["steps"].append("child doctype not present; nothing to drop")

    # -------- 4. Rename the print format ------------------------------
    if frappe.db.exists("Print Format", OLD_PRINT_FORMAT) and not frappe.db.exists(
        "Print Format", NEW_PRINT_FORMAT
    ):
        rename_doc(
            "Print Format", OLD_PRINT_FORMAT, NEW_PRINT_FORMAT,
            force=True, merge=False, ignore_permissions=True,
        )
        # Re-point doc_type to the new doctype name.
        frappe.db.set_value(
            "Print Format", NEW_PRINT_FORMAT,
            "doc_type", NEW_DOCTYPE,
            update_modified=False,
        )
        result["steps"].append(
            f"renamed print format {OLD_PRINT_FORMAT} -> {NEW_PRINT_FORMAT}"
        )
    elif frappe.db.exists("Print Format", NEW_PRINT_FORMAT):
        result["steps"].append("print format already renamed")
    else:
        result["steps"].append("legacy print format not present")

    # -------- 5. Delete orphan blank draft investigations -------------
    # These are drafts with no shift link (Finance manually clicked New,
    # didn't save the shift picker, walked away). Safe to drop.
    if frappe.db.exists("DocType", NEW_DOCTYPE):
        orphans = frappe.get_all(
            NEW_DOCTYPE,
            filters={"docstatus": 0, "shift": ["in", ["", None]]},
            pluck="name",
        )
        for name in orphans:
            frappe.delete_doc(
                NEW_DOCTYPE, name,
                force=True, ignore_permissions=True,
            )
        result["steps"].append(f"deleted {len(orphans)} orphan blank drafts")

    frappe.db.commit()
    frappe.logger().info(
        f"rename_annex_t07_to_pos_variance_investigation: {result}"
    )
    return result
