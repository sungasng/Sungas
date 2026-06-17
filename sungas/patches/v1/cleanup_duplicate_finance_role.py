"""Patch v1 — Duplicate `Head of Finance` role cleanup (ROADMAP B-5).

Context:
    The site carries two functionally identical roles:

        * Head of Finance          (legacy / non-LPG)  → 1 user
        * LPG Head of Finance      (canonical)         → 3 users

    The non-LPG role exists only because of an early naming inconsistency.
    All POS Closing Shift workflow transitions, fixtures, custom permissions
    and the new Wave D-2 escalation chain target the LPG variant. We
    therefore migrate the single straggler over to `LPG Head of Finance`
    and delete the duplicate role to remove permission ambiguity.

Run order:
    Hooked via ``sungas/patches.txt`` so it runs exactly once per site at
    next ``bench migrate``. Idempotent: safe to re-execute.

Manual invocation::

    bench --site <site> execute sungas.patches.v1.cleanup_duplicate_finance_role.execute
"""

from __future__ import annotations

import frappe  # type: ignore


LEGACY_ROLE = "Head of Finance"
CANONICAL_ROLE = "LPG Head of Finance"


def execute() -> dict[str, object]:
    """Migrate users off the legacy role and delete it. Idempotent."""
    if not frappe.db.exists("Role", LEGACY_ROLE):
        return {"status": "skipped", "reason": f"role '{LEGACY_ROLE}' not present"}

    if not frappe.db.exists("Role", CANONICAL_ROLE):
        # Don't touch anything if the canonical role is missing — installer bug.
        frappe.log_error(
            f"Cannot cleanup: canonical role '{CANONICAL_ROLE}' missing.",
            "Sungas duplicate role cleanup",
        )
        return {"status": "aborted", "reason": f"canonical role '{CANONICAL_ROLE}' missing"}

    affected_users = frappe.db.sql_list(
        """
        SELECT DISTINCT parent
        FROM `tabHas Role`
        WHERE role = %(role)s
          AND parent NOT IN ('Administrator', 'Guest')
        """,
        {"role": LEGACY_ROLE},
    )

    migrated: list[str] = []
    already_had_canonical: list[str] = []

    for user in affected_users:
        existing = frappe.db.exists(
            "Has Role",
            {"parent": user, "role": CANONICAL_ROLE, "parenttype": "User"},
        )
        if existing:
            already_had_canonical.append(user)
        else:
            # Add canonical role row.
            frappe.get_doc({
                "doctype": "Has Role",
                "parent": user,
                "parenttype": "User",
                "parentfield": "roles",
                "role": CANONICAL_ROLE,
            }).insert(ignore_permissions=True)
            migrated.append(user)

        # Remove legacy role row from this user.
        frappe.db.delete(
            "Has Role",
            {"parent": user, "role": LEGACY_ROLE, "parenttype": "User"},
        )

    # Delete the legacy role itself once no user references it.
    remaining = frappe.db.count("Has Role", {"role": LEGACY_ROLE})
    deleted_role = False
    if remaining == 0:
        frappe.delete_doc("Role", LEGACY_ROLE, ignore_permissions=True, force=True)
        deleted_role = True

    frappe.db.commit()

    result = {
        "status": "ok",
        "users_migrated": migrated,
        "users_already_had_canonical": already_had_canonical,
        "legacy_role_deleted": deleted_role,
        "remaining_references": remaining,
    }
    frappe.logger().info(f"cleanup_duplicate_finance_role: {result}")
    return result
