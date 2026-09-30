"""sungas.patches.v1.ensure_pr_workflow_active
================================================

Patch 0011b -- Idempotent after_migrate: guarantee `Sungas Purchase
Receipt Approval` is the single active workflow on Purchase Receipt.

Why this is needed:
    * Frappe fixture loading upserts the workflow document by name,
      but if the DB copy is `is_active=1` with the OLD state chain,
      and the fixture arrives with the SAME name + `is_active=1`,
      Frappe's Workflow.validate() sometimes short-circuits child-
      table diffing. Result: parent doc updated, but state/transition
      children can end up stale.
    * Additionally, if a *different* PR workflow (e.g. an earlier
      abandoned name) is still `is_active=1`, our fixture would fail
      Workflow validation with "another workflow is active on this
      document type" and get silently dropped.

This patch runs on every migrate and forces:
    1. Any workflow on Purchase Receipt whose name != our canonical
       name is deactivated.
    2. Our workflow's `is_active` flag is set to 1.
    3. Frappe's workflow state cache is invalidated so the Desk sees
       the freshly loaded states immediately.

Idempotent. Never throws (log_error on failure).
"""

from __future__ import annotations

import frappe  # type: ignore

CANONICAL_PR_WORKFLOW = "Sungas Purchase Receipt Approval"


def execute() -> None:
    try:
        # Step 1: deactivate any other PR workflows.
        others = frappe.get_all(
            "Workflow",
            filters={
                "document_type": "Purchase Receipt",
                "is_active": 1,
                "name": ["!=", CANONICAL_PR_WORKFLOW],
            },
            pluck="name",
        )
        for wf_name in others:
            frappe.db.set_value("Workflow", wf_name, "is_active", 0)
            frappe.logger().info(
                f"[ensure_pr_workflow_active] Deactivated conflicting PR workflow: {wf_name}"
            )

        # Step 2: activate our canonical workflow (only if it exists).
        if frappe.db.exists("Workflow", CANONICAL_PR_WORKFLOW):
            current = frappe.db.get_value(
                "Workflow", CANONICAL_PR_WORKFLOW, "is_active"
            )
            if not current:
                frappe.db.set_value(
                    "Workflow", CANONICAL_PR_WORKFLOW, "is_active", 1
                )
                frappe.logger().info(
                    f"[ensure_pr_workflow_active] Activated {CANONICAL_PR_WORKFLOW}"
                )
        else:
            frappe.log_error(
                title="ensure_pr_workflow_active: canonical workflow missing",
                message=(
                    f"Fixture did not load {CANONICAL_PR_WORKFLOW} into DB. "
                    "Check migrate output for JSON errors."
                ),
            )
            return

        # Step 3: invalidate workflow state cache so Desk picks up new states.
        try:
            frappe.clear_cache(doctype="Purchase Receipt")
        except Exception:
            pass

        frappe.db.commit()  # noqa: DAR000

    except Exception:
        frappe.log_error(
            title="ensure_pr_workflow_active failed",
            message=frappe.get_traceback(),
        )
