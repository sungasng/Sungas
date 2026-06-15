"""sungas.install.install_variance_workflow
=============================================

Idempotent installer for the **POS Closing Shift Variance** sequential
workflow (Wave D-1).

States (all docstatus=0 except Approved=1, Rejected=2):
  - Draft
  - Pending Plant Manager
  - Pending HOD Operations
  - Pending HOD Finance        (only reached when severity == 'critical')
  - Pending COO                (only reached if Sungas Close Policy
                                require_coo_on_critical = 1)
  - Approved
  - Rejected

Transitions (action / from -> to / role / condition):
  1. Submit for Approval / Draft -> Pending Plant Manager  /
        LPG POS User + LPG Plant Manager /
        cond: doc.variance_severity in ('block','critical')

  2. Approve / Pending Plant Manager -> Pending HOD Operations  /
        LPG Plant Manager  /  always

  3. Reject / Pending Plant Manager -> Rejected  /
        LPG Plant Manager  /  always

  4. Approve / Pending HOD Operations -> Approved  /
        LPG Head of Operations  /
        cond: doc.variance_severity == 'block'

  5. Escalate to Finance / Pending HOD Operations -> Pending HOD Finance  /
        LPG Head of Operations  /
        cond: doc.variance_severity == 'critical'

  6. Reject / Pending HOD Operations -> Rejected  /
        LPG Head of Operations  /  always

  7. Approve / Pending HOD Finance -> Approved  /
        LPG Head of Finance  /
        cond: not require_coo

  8. Escalate to COO / Pending HOD Finance -> Pending COO  /
        LPG Head of Finance  /
        cond: require_coo

  9. Reject / Pending HOD Finance -> Rejected  /
        LPG Head of Finance  /  always

  10. Approve / Pending COO -> Approved  /  System Manager  /  always
  11. Reject / Pending COO -> Rejected   /  System Manager  /  always

  12. Reopen / Rejected -> Draft  /  LPG POS User + LPG Plant Manager  /  always

Run with:
    bench --site <site> execute sungas.install.install_variance_workflow.install
"""
from __future__ import annotations

import frappe


WORKFLOW_NAME = "POS Closing Shift Variance"
DOCTYPE = "POS Closing Shift"

# (state_name, doc_status, style)
STATES = [
    ("Draft",                   "0", "Primary"),
    ("Pending Plant Manager",   "0", "Warning"),
    ("Pending HOD Operations",  "0", "Warning"),
    ("Pending HOD Finance",     "0", "Danger"),
    ("Pending COO",             "0", "Danger"),
    ("Approved",                "1", "Success"),
    ("Rejected",                "2", "Inverse"),
]

# Action master names that appear on the workflow buttons
ACTIONS = [
    "Submit for Approval",
    "Approve",
    "Escalate to Finance",
    "Escalate to COO",
    "Reject",
    "Reopen",
]

# Transitions: (action, state, next_state, allowed_roles_csv, condition)
# An empty condition means "always".
TRANSITIONS = [
    # 1. Cashier (or PM) sends a block/critical-variance draft for approval
    ("Submit for Approval", "Draft", "Pending Plant Manager",
     "LPG POS User,LPG Plant Manager,System Manager",
     "doc.variance_severity in ('block','critical')"),

    # 2 / 3. Plant Manager review
    ("Approve", "Pending Plant Manager", "Pending HOD Operations",
     "LPG Plant Manager,System Manager", ""),
    ("Reject", "Pending Plant Manager", "Rejected",
     "LPG Plant Manager,System Manager", ""),

    # 4 / 5 / 6. HOD Ops review
    ("Approve", "Pending HOD Operations", "Approved",
     "LPG Head of Operations,System Manager",
     "doc.variance_severity == 'block'"),
    ("Escalate to Finance", "Pending HOD Operations", "Pending HOD Finance",
     "LPG Head of Operations,System Manager",
     "doc.variance_severity == 'critical'"),
    ("Reject", "Pending HOD Operations", "Rejected",
     "LPG Head of Operations,System Manager", ""),

    # 7 / 8 / 9. HOD Finance review (critical only)
    ("Approve", "Pending HOD Finance", "Approved",
     "LPG Head of Finance,System Manager",
     "not frappe.get_single('Sungas Close Policy').get('require_coo_on_critical')"),
    ("Escalate to COO", "Pending HOD Finance", "Pending COO",
     "LPG Head of Finance,System Manager",
     "frappe.get_single('Sungas Close Policy').get('require_coo_on_critical') == 1"),
    ("Reject", "Pending HOD Finance", "Rejected",
     "LPG Head of Finance,System Manager", ""),

    # 10 / 11. COO review (only if require_coo_on_critical)
    ("Approve", "Pending COO", "Approved", "System Manager", ""),
    ("Reject", "Pending COO", "Rejected", "System Manager", ""),

    # 12. Reopen rejected shift back to draft for the cashier
    ("Reopen", "Rejected", "Draft",
     "LPG POS User,LPG Plant Manager,System Manager", ""),
]


def _ensure_workflow_state(state_name: str, style: str) -> None:
    if frappe.db.exists("Workflow State", state_name):
        return
    doc = frappe.get_doc({
        "doctype": "Workflow State",
        "workflow_state_name": state_name,
        "style": style,
    })
    doc.flags.ignore_permissions = True
    doc.insert(ignore_if_duplicate=True)


def _ensure_workflow_action(action_name: str) -> None:
    if frappe.db.exists("Workflow Action Master", action_name):
        return
    doc = frappe.get_doc({
        "doctype": "Workflow Action Master",
        "workflow_action_name": action_name,
    })
    doc.flags.ignore_permissions = True
    doc.insert(ignore_if_duplicate=True)


def _build_workflow_doc() -> dict:
    states = [
        {
            "state": name,
            "doc_status": doc_status,
            "allow_edit": "LPG POS User" if name == "Draft" else "System Manager",
            "update_field": "",
            "update_value": "",
        }
        for name, doc_status, _style in STATES
    ]
    transitions = [
        {
            "state": s,
            "action": a,
            "next_state": ns,
            "allowed": roles,
            "condition": cond,
            "allow_self_approval": 1,
        }
        for a, s, ns, roles, cond in TRANSITIONS
    ]
    return {
        "doctype": "Workflow",
        "workflow_name": WORKFLOW_NAME,
        "document_type": DOCTYPE,
        "is_active": 1,
        "send_email_alert": 0,
        "workflow_state_field": "workflow_state",
        "states": states,
        "transitions": transitions,
    }


def install():
    """Create / overwrite the Workflow and its prerequisite masters."""
    for name, _ds, style in STATES:
        _ensure_workflow_state(name, style)

    for action in ACTIONS:
        _ensure_workflow_action(action)

    payload = _build_workflow_doc()

    if frappe.db.exists("Workflow", WORKFLOW_NAME):
        wf = frappe.get_doc("Workflow", WORKFLOW_NAME)
        wf.update({
            "is_active": payload["is_active"],
            "send_email_alert": payload["send_email_alert"],
            "workflow_state_field": payload["workflow_state_field"],
            "document_type": payload["document_type"],
        })
        wf.set("states", payload["states"])
        wf.set("transitions", payload["transitions"])
        wf.flags.ignore_permissions = True
        wf.save()
        action = "updated"
    else:
        wf = frappe.get_doc(payload)
        wf.flags.ignore_permissions = True
        wf.insert(ignore_permissions=True)
        action = "created"

    frappe.db.commit()
    print(f"[sungas] Workflow '{WORKFLOW_NAME}' {action}: "
          f"{len(payload['states'])} states, {len(payload['transitions'])} transitions.")
