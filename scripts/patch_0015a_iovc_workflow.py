"""Patch 0015a -- Sungas Inter-Outlet Variance Approval workflow.

Adds a formal Frappe Workflow doctype on top of Patch 0015. States:
  Draft -> Under Investigation -> Pending HoF Approval (write-off only) -> Approved
                               -> Approved                              (non-write-off)
  Any state -> Rejected -> Draft (reopen)

Role gates mirror the server script already shipped in Patch 0015, so
the two layers reinforce each other. Workflow handles state orchestration
+ UI buttons; server script handles accounting side-effects + HoF stamp
enforcement.

Adds the `workflow_state` custom field so Frappe knows where to store state.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "sungas" / "fixtures"


# ---------------------------------------------------------------------------
# 1. New Workflow States
# ---------------------------------------------------------------------------
NEW_STATES = [
    {
        "doctype": "Workflow State",
        "icon": "",
        "name": "Under Investigation",
        "style": "Warning",
        "workflow_state_name": "Under Investigation",
    },
    {
        "doctype": "Workflow State",
        "icon": "",
        "name": "Pending HoF Approval",
        "style": "Danger",
        "workflow_state_name": "Pending HoF Approval",
    },
]


# ---------------------------------------------------------------------------
# 2. New Workflow Action Masters
# ---------------------------------------------------------------------------
NEW_ACTIONS = [
    {
        "doctype": "Workflow Action Master",
        "name": "Start Investigation",
        "workflow_action_name": "Start Investigation",
    },
    {
        "doctype": "Workflow Action Master",
        "name": "Request HoF Write-Off Approval",
        "workflow_action_name": "Request HoF Write-Off Approval",
    },
]


# ---------------------------------------------------------------------------
# 3. workflow_state custom field on IOVC
# ---------------------------------------------------------------------------
IOVC_WORKFLOW_STATE_FIELD = {
    "allow_in_quick_entry": 0, "allow_on_submit": 0, "bold": 0, "collapsible": 0,
    "collapsible_depends_on": None, "columns": 0, "default": None,
    "depends_on": None, "description": None, "docstatus": 0,
    "doctype": "Custom Field", "dt": "Inter-Outlet Variance Case",
    "fetch_from": None, "fetch_if_empty": 0, "fieldname": "workflow_state",
    "fieldtype": "Link", "hidden": 1, "hide_border": 0, "hide_days": 0,
    "hide_seconds": 0, "ignore_user_permissions": 0, "ignore_xss_filter": 0,
    "in_global_search": 0, "in_list_view": 0, "in_preview": 0,
    "in_standard_filter": 0, "insert_after": "title",
    "is_system_generated": 0, "is_virtual": 0,
    "label": "Workflow State", "length": 0, "mandatory_depends_on": None,
    "modified": "2026-02-28 00:00:00.000000", "module": None,
    "name": "Inter-Outlet Variance Case-workflow_state", "no_copy": 1,
    "non_negative": 0, "options": "Workflow State", "permlevel": 0,
    "placeholder": None, "precision": "", "print_hide": 1,
    "print_hide_if_no_value": 0, "print_width": None, "read_only": 1,
    "read_only_depends_on": None, "report_hide": 0, "reqd": 0,
    "search_index": 0, "show_dashboard": 0, "show_in_report_builder": 0,
    "sort_options": 0, "translatable": 0, "unique": 0, "width": None,
}


# ---------------------------------------------------------------------------
# 4. The Workflow itself
# ---------------------------------------------------------------------------
WF_NAME = "Sungas Inter-Outlet Variance Approval"


def _state(name, docstatus, allow_edit):
    return {
        "allow_edit": allow_edit, "avoid_status_override": 0,
        "doc_status": docstatus, "doctype": "Workflow Document State",
        "is_optional_state": 0, "message": None,
        "parent": WF_NAME, "parentfield": "states", "parenttype": "Workflow",
        "send_email": 1, "state": name,
        "update_field": "", "update_value": "", "workflow_builder_id": None,
    }


def _trans(state, action, next_state, allowed, condition="", allow_self=1, email=1):
    return {
        "action": action, "allow_self_approval": allow_self,
        "allowed": allowed, "condition": condition,
        "doctype": "Workflow Transition", "next_state": next_state,
        "parent": WF_NAME, "parentfield": "transitions", "parenttype": "Workflow",
        "send_email_to_creator": email, "state": state,
        "workflow_builder_id": None,
    }


IOVC_WORKFLOW = {
    "doctype": "Workflow",
    "document_type": "Inter-Outlet Variance Case",
    "is_active": 1,
    "name": WF_NAME,
    "workflow_name": WF_NAME,
    "override_status": 0,
    "send_email_alert": 1,
    "workflow_state_field": "workflow_state",
    "states": [
        _state("Draft", "0", "LPG Head of Operations"),
        _state("Under Investigation", "0", "LPG Head of Operations"),
        _state("Pending HoF Approval", "0", "LPG Head of Finance"),
        _state("Approved", "1", "LPG Head of Operations"),
        _state("Rejected", "0", "LPG Head of Operations"),
    ],
    "transitions": [
        # Draft -> Under Investigation (HoD Ops)
        _trans("Draft", "Start Investigation", "Under Investigation",
               "LPG Head of Operations"),
        _trans("Draft", "Start Investigation", "Under Investigation",
               "System Manager", email=0),

        # Under Investigation -> Approved (non-write-off resolutions)
        _trans("Under Investigation", "Approve", "Approved",
               "LPG Head of Operations",
               condition="doc.resolution and doc.resolution != 'Write-off as transit loss'"),
        _trans("Under Investigation", "Approve", "Approved",
               "System Manager",
               condition="doc.resolution and doc.resolution != 'Write-off as transit loss'",
               email=0),

        # Under Investigation -> Pending HoF Approval (write-off path)
        _trans("Under Investigation", "Request HoF Write-Off Approval",
               "Pending HoF Approval", "LPG Head of Operations",
               condition="doc.resolution == 'Write-off as transit loss'"),
        _trans("Under Investigation", "Request HoF Write-Off Approval",
               "Pending HoF Approval", "System Manager",
               condition="doc.resolution == 'Write-off as transit loss'",
               email=0),

        # Pending HoF Approval -> Approved (HoF only, needs HoF stamp from client script)
        _trans("Pending HoF Approval", "Approve", "Approved",
               "LPG Head of Finance",
               condition="doc.hod_finance_signed_by"),
        _trans("Pending HoF Approval", "Approve", "Approved",
               "System Manager", email=0),

        # Reject paths
        _trans("Under Investigation", "Reject", "Rejected",
               "LPG Head of Operations"),
        _trans("Pending HoF Approval", "Reject", "Rejected",
               "LPG Head of Finance"),

        # Reopen
        _trans("Rejected", "Reopen", "Draft", "LPG Head of Operations"),
    ],
}


def main() -> None:
    # 1. Workflow States
    ws_path = FIXTURES / "workflow_state.json"
    ws = json.loads(ws_path.read_text())
    existing = {s["name"] for s in ws}
    added_states = []
    for s in NEW_STATES:
        if s["name"] not in existing:
            ws.append(s)
            added_states.append(s["name"])
    ws_path.write_text(json.dumps(ws, indent=1) + "\n")
    print(f"[1/4] workflow_state.json -- +{len(added_states)} states ({added_states})")

    # 2. Workflow Action Masters
    wa_path = FIXTURES / "workflow_action_master.json"
    wa = json.loads(wa_path.read_text())
    existing = {a["name"] for a in wa}
    added_actions = []
    for a in NEW_ACTIONS:
        if a["name"] not in existing:
            wa.append(a)
            added_actions.append(a["name"])
    wa_path.write_text(json.dumps(wa, indent=1) + "\n")
    print(f"[2/4] workflow_action_master.json -- +{len(added_actions)} actions ({added_actions})")

    # 3. workflow_state Custom Field on IOVC
    cf_path = FIXTURES / "custom_field.json"
    cf = json.loads(cf_path.read_text())
    cf = [c for c in cf if c.get("name") != IOVC_WORKFLOW_STATE_FIELD["name"]]
    cf.append(IOVC_WORKFLOW_STATE_FIELD)
    cf_path.write_text(json.dumps(cf, indent=1) + "\n")
    print(f"[3/4] custom_field.json -- +workflow_state on IOVC")

    # 4. Workflow
    wf_path = FIXTURES / "workflow.json"
    wf = json.loads(wf_path.read_text())
    wf = [w for w in wf if w.get("name") != WF_NAME]
    wf.append(IOVC_WORKFLOW)
    wf_path.write_text(json.dumps(wf, indent=1) + "\n")
    print(f"[4/4] workflow.json -- +{WF_NAME}")

    print("[Patch 0015a] workflow fixtures updated OK")


if __name__ == "__main__":
    main()
