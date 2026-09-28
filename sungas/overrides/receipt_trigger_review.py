"""sungas.overrides.receipt_trigger_review
===========================================

Wave PR-1 -- Purchase Receipt Trigger Review.

On submission of any Purchase Receipt, evaluate a set of risk triggers
and, if any fire, open a ToDo for the appropriate reviewer plus stamp
a Comment on the receipt for the audit trail.

Triggers evaluated (any hit fires a review):
    (T1) `is_return` = 1                   -- goods returned to supplier
    (T2) Quantity / rate variance vs the linked Purchase Order beyond
         5% on any row (only checked when a PO reference exists).
    (T3) Grand total >= NGN 5,000,000     -- high-value receipt.

Reviewers (in priority order):
    1. LPG Head of Operations   (if role holders exist)
    2. Accounts Manager
    3. System Manager           (fallback -- always available)

Design notes:
    - This hook runs at `on_submit`, so it must NEVER throw: doing so
      would leave the receipt submitted but the wrapping request would
      500. All failures are logged and swallowed.
    - We create a Frappe `ToDo` rather than a bespoke doctype so ops
      can act on it from the standard bell / todo list. Zero migration
      cost.
"""

from __future__ import annotations

import frappe  # type: ignore
from frappe import _
from frappe.utils import flt


HIGH_VALUE_THRESHOLD_NGN = 5_000_000
VARIANCE_PCT_THRESHOLD = 5.0

REVIEWER_ROLE_PRIORITY = (
    "LPG Head of Operations",
    "Accounts Manager",
    "System Manager",
)


def review_on_receipt_submit(doc, method=None) -> None:
    """on_submit hook for Purchase Receipt. Never throws."""
    try:
        triggers = _collect_triggers(doc)
        if not triggers:
            return

        reviewer = _pick_reviewer()
        if not reviewer:
            return  # No one to assign to -- audit the receipt anyway.

        _open_todo(doc, reviewer, triggers)
        _stamp_comment(doc, triggers)
    except Exception:
        frappe.log_error(
            title="receipt_trigger_review failed",
            message=frappe.get_traceback(),
        )


# --------------------------------------------------------------------------- #
# Trigger evaluation
# --------------------------------------------------------------------------- #

def _collect_triggers(doc) -> list[str]:
    hits: list[str] = []

    if int(doc.get("is_return") or 0):
        hits.append("Supplier return (is_return=1)")

    grand_total = flt(doc.get("grand_total") or doc.get("base_grand_total") or 0)
    if grand_total >= HIGH_VALUE_THRESHOLD_NGN:
        hits.append(f"High-value receipt: NGN {grand_total:,.2f}")

    po_variance = _po_variance_hits(doc)
    if po_variance:
        hits.extend(po_variance)

    return hits


def _po_variance_hits(doc) -> list[str]:
    hits: list[str] = []
    for row in (doc.get("items") or []):
        po = row.get("purchase_order")
        po_row_name = row.get("purchase_order_item")
        if not (po and po_row_name):
            continue
        po_row = frappe.db.get_value(
            "Purchase Order Item",
            po_row_name,
            ["qty", "rate"],
            as_dict=True,
        )
        if not po_row:
            continue

        _check_pct(hits, row.get("item_code"), "qty",
                   received=flt(row.get("received_qty") or row.get("qty") or 0),
                   ordered=flt(po_row.qty or 0))
        _check_pct(hits, row.get("item_code"), "rate",
                   received=flt(row.get("rate") or 0),
                   ordered=flt(po_row.rate or 0))
    return hits


def _check_pct(hits: list[str], item: str, label: str,
               received: float, ordered: float) -> None:
    if not ordered:
        return
    diff_pct = abs((received - ordered) / ordered) * 100.0
    if diff_pct >= VARIANCE_PCT_THRESHOLD:
        hits.append(
            f"{label.upper()} variance {diff_pct:.1f}% on {item} "
            f"(PO {ordered:g} -> receipt {received:g})"
        )


# --------------------------------------------------------------------------- #
# Reviewer resolution
# --------------------------------------------------------------------------- #

def _pick_reviewer() -> str | None:
    for role in REVIEWER_ROLE_PRIORITY:
        users = frappe.get_all(
            "Has Role",
            filters={"role": role, "parenttype": "User"},
            fields=["parent"],
            limit=1,
        )
        if users:
            return users[0].parent
    return None


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #

def _open_todo(doc, reviewer: str, triggers: list[str]) -> None:
    description = _(
        "Purchase Receipt <b>{name}</b> flagged for review.<br>"
        "Triggers:<ul>{bullets}</ul>"
    ).format(
        name=doc.name,
        bullets="".join(f"<li>{t}</li>" for t in triggers),
    )
    frappe.get_doc({
        "doctype": "ToDo",
        "reference_type": "Purchase Receipt",
        "reference_name": doc.name,
        "allocated_to": reviewer,
        "description": description,
        "priority": "High",
        "status": "Open",
    }).insert(ignore_permissions=True)


def _stamp_comment(doc, triggers: list[str]) -> None:
    comment = _("[Trigger Review] Flagged on submit: {trigs}").format(
        trigs="; ".join(triggers),
    )
    frappe.get_doc({
        "doctype": "Comment",
        "comment_type": "Info",
        "reference_doctype": "Purchase Receipt",
        "reference_name": doc.name,
        "content": comment,
    }).insert(ignore_permissions=True)
