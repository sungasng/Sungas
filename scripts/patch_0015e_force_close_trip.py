"""Patch 0015e -- implement the 'Force Close Trip' HoO escape hatch.

User-blocked (2026-02-28): MR-SE-LS-SE-IOVC retest blocked because truck TBD
is still on trip LS-Aseese-SCL-2026-10-04-TBD in Dispatched state. The
'Truck Open Trip Guard' server script's error message advertises:
    'Use Force Close Trip (HoO only) if the truck cannot return.'
But that action was never actually implemented. Ships now:

  * Property Setter: expand DLS `state` options to include 'Closed'
  * 3 Custom Fields on DLS: force_closed_by, force_closed_at, force_close_reason
  * Governance API: sungas.api.governance.force_close_trip(ls, reason)
      - Role-gated to LPG Head of Operations + System Manager
      - Flips state -> 'Closed', stamps who/when/why, adds audit comment
      - Blocks if the trip has any Pending/In Transit drops the operator
        could still reconcile normally (prevents misuse)
  * Client Script: 'Force Close Trip' button on DLS, visible only in states
      Locked / Loading / Dispatched, visible only to HoO + System Manager
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "sungas" / "fixtures"


# ---------------------------------------------------------------------------
# 1. Property Setter -- expand DLS state options to include 'Closed'
#    Pre-existing options (inferred from code refs): Draft, Locked, Loading, Dispatched
# ---------------------------------------------------------------------------
PROP_SETTER_STATE = {
    "doc_type": "Daily Loading Schedule",
    "doctype": "Property Setter",
    "doctype_or_field": "DocField",
    "field_name": "state",
    "is_system_generated": 0,
    "module": None,
    "name": "Daily Loading Schedule-state-options",
    "property": "options",
    "property_type": "Text",
    "value": "\n".join(["Draft", "Locked", "Loading", "Dispatched", "Closed"]),
}


# ---------------------------------------------------------------------------
# 2. Custom Fields on DLS
# ---------------------------------------------------------------------------
def _cf(fieldname, fieldtype, label, insert_after, **kw):
    return {
        "allow_in_quick_entry": 0, "allow_on_submit": 0, "bold": 0,
        "collapsible": 0, "collapsible_depends_on": None, "columns": 0,
        "default": None, "depends_on": kw.get("depends_on"),
        "description": kw.get("description"), "docstatus": 0,
        "doctype": "Custom Field", "dt": "Daily Loading Schedule",
        "fetch_from": None, "fetch_if_empty": 0, "fieldname": fieldname,
        "fieldtype": fieldtype, "hidden": 0, "hide_border": 0, "hide_days": 0,
        "hide_seconds": 0, "ignore_user_permissions": 0, "ignore_xss_filter": 0,
        "in_global_search": 0, "in_list_view": 0, "in_preview": 0,
        "in_standard_filter": 0, "insert_after": insert_after,
        "is_system_generated": 0, "is_virtual": 0, "label": label,
        "length": 0, "mandatory_depends_on": None,
        "modified": "2026-02-28 00:00:00.000000", "module": None,
        "name": f"Daily Loading Schedule-{fieldname}", "no_copy": 1,
        "non_negative": 0, "options": kw.get("options"),
        "permlevel": 0, "placeholder": None, "precision": "",
        "print_hide": 0, "print_hide_if_no_value": 1, "print_width": None,
        "read_only": 1, "read_only_depends_on": None,
        "report_hide": 0, "reqd": 0, "search_index": 0,
        "show_dashboard": 0, "show_in_report_builder": 0, "sort_options": 0,
        "translatable": 0, "unique": 0, "width": None,
    }


DLS_FORCE_CLOSE_FIELDS = [
    _cf("force_closed_by", "Link", "Force-Closed By", "state",
        options="User", depends_on="eval:doc.state=='Closed'"),
    _cf("force_closed_at", "Datetime", "Force-Closed At", "force_closed_by",
        depends_on="eval:doc.state=='Closed'"),
    _cf("force_close_reason", "Small Text", "Force-Close Reason", "force_closed_at",
        depends_on="eval:doc.state=='Closed'",
        description="Captured when HoO closes a trip without full reconciliation. "
                    "Audit-visible on the DLS and in Report Builder."),
]


# ---------------------------------------------------------------------------
# 3. Client Script -- Force Close Trip button
# ---------------------------------------------------------------------------
DLS_FORCE_CLOSE_CLIENT_SCRIPT = {
    "doctype": "Client Script",
    "dt": "Daily Loading Schedule",
    "enabled": 1,
    "module": None,
    "name": "DLS Force Close Trip UI",
    "script": """// Patch 0015e -- Force Close Trip button on DLS.
// Visible only to LPG Head of Operations + System Manager, and only when
// the trip is still open (Locked / Loading / Dispatched). Prompts for a
// mandatory reason, then calls the whitelisted governance endpoint to
// stamp state=Closed + audit trail.
frappe.ui.form.on('Daily Loading Schedule', {
    refresh(frm) {
        if (!frm.doc || frm.doc.docstatus === 2) return;
        const open_states = ['Locked', 'Loading', 'Dispatched'];
        if (!open_states.includes(frm.doc.state)) return;

        const roles = frappe.user_roles || [];
        if (!roles.includes('LPG Head of Operations') && !roles.includes('System Manager')) {
            return;
        }

        frm.add_custom_button(__('Force Close Trip'), () => {
            frappe.prompt([
                {
                    fieldtype: 'Small Text',
                    fieldname: 'reason',
                    label: __('Reason for Force-Close'),
                    reqd: 1,
                    description: __(
                        'Why can\\'t this trip be reconciled normally? ' +
                        '(e.g. truck broke down, driver unreachable, residual LPG written off). ' +
                        'This is stamped on the DLS and visible in the audit log.'
                    )
                }
            ], (values) => {
                frappe.confirm(
                    __('Force-close trip {0}? Truck {1} will be freed for a new schedule. ' +
                       'The reason will be stamped on the DLS.',
                       [frm.doc.name, frm.doc.truck_no]),
                    () => {
                        frappe.call({
                            method: 'sungas.api.governance.force_close_trip',
                            args: { ls: frm.doc.name, reason: values.reason },
                            freeze: true,
                            freeze_message: __('Force-closing trip...')
                        }).then((r) => {
                            if (r && r.message && r.message.ok) {
                                frappe.show_alert({
                                    message: __('Trip force-closed. Truck {0} is now free.', [frm.doc.truck_no]),
                                    indicator: 'orange'
                                });
                                frm.reload_doc();
                            }
                        });
                    }
                );
            }, __('Force Close Trip'), __('Submit Reason'));
        }, __('Actions')).removeClass('btn-default').addClass('btn-warning');
    }
});
""",
    "view": "Form",
}


def main():
    # 1. Property Setter
    ps_path = FIXTURES / "property_setter.json"
    ps = json.loads(ps_path.read_text())
    ps = [p for p in ps if p.get("name") != PROP_SETTER_STATE["name"]]
    ps.append(PROP_SETTER_STATE)
    ps_path.write_text(json.dumps(ps, indent=1) + "\n")
    print(f"[1/3] property_setter.json -- +DLS state options (Draft/Locked/Loading/Dispatched/Closed)")

    # 2. Custom Fields
    cf_path = FIXTURES / "custom_field.json"
    cf = json.loads(cf_path.read_text())
    new_names = {f["name"] for f in DLS_FORCE_CLOSE_FIELDS}
    cf = [c for c in cf if c.get("name") not in new_names]
    cf.extend(DLS_FORCE_CLOSE_FIELDS)
    cf_path.write_text(json.dumps(cf, indent=1) + "\n")
    print(f"[2/3] custom_field.json -- +{len(DLS_FORCE_CLOSE_FIELDS)} DLS fields (force_closed_by/at/reason)")

    # 3. Client Script
    cs_path = FIXTURES / "client_script.json"
    cs = json.loads(cs_path.read_text())
    cs = [c for c in cs if c.get("name") != DLS_FORCE_CLOSE_CLIENT_SCRIPT["name"]]
    cs.append(DLS_FORCE_CLOSE_CLIENT_SCRIPT)
    cs_path.write_text(json.dumps(cs, indent=1) + "\n")
    print(f"[3/3] client_script.json -- +DLS Force Close Trip UI")

    print("[Patch 0015e] fixtures updated OK")


if __name__ == "__main__":
    main()
