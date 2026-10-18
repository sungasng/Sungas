"""Patch 0016 -- IAS 2 Logistics Cost Capitalisation (Trip Cost Pool).

Ships fixtures for:
  * DLS 'Haulage Costing (IAS 2)' section: mode / hauler / standard rate +
    read-only settlement summary (kg split, costs, cause, JE, who/when)
  * `sungas_loading_schedule` trip link on Purchase Invoice, Payment Entry,
    Employee Advance, Expense Claim, Journal Entry (hauler advances, driver
    advances, expense claims, prepaid drawdowns all traceable to the trip)
  * Warehouse `sungas_operations_cost_center` (cause-based cost centres)
  * Client Script 'DLS Haulage Costing UI' (Settle Trip Costs dialog)
  * IOVC Resolve: Return-to-Source / Redelivery SEs inherit the trip's
    loading_schedule so returned kg are counted on the right trip
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "sungas" / "fixtures"
LOCKED = "eval:doc.state=='Dispatched'||doc.state=='Closed'||doc.haulage_settled_on"


def cf(dt, fieldname, fieldtype, label, insert_after, **kw):
    return {
        "allow_in_quick_entry": 0, "allow_on_submit": kw.get("allow_on_submit", 0), "bold": 0,
        "collapsible": kw.get("collapsible", 0), "collapsible_depends_on": None, "columns": 0,
        "default": kw.get("default"), "depends_on": kw.get("depends_on"),
        "description": kw.get("description"), "docstatus": 0,
        "doctype": "Custom Field", "dt": dt,
        "fetch_from": None, "fetch_if_empty": 0, "fieldname": fieldname,
        "fieldtype": fieldtype, "hidden": 0, "hide_border": 0, "hide_days": 0,
        "hide_seconds": 0, "ignore_user_permissions": 0, "ignore_xss_filter": 0,
        "in_global_search": 0, "in_list_view": 0, "in_preview": 0,
        "in_standard_filter": kw.get("in_standard_filter", 0), "insert_after": insert_after,
        "is_system_generated": 0, "is_virtual": 0, "label": label,
        "length": 0, "mandatory_depends_on": kw.get("mandatory_depends_on"),
        "modified": "2026-06-01 00:00:00.000000", "module": None,
        "name": f"{dt}-{fieldname}", "no_copy": kw.get("no_copy", 1),
        "non_negative": 0, "options": kw.get("options"),
        "permlevel": 0, "placeholder": None, "precision": "",
        "print_hide": 0, "print_hide_if_no_value": 1, "print_width": None,
        "read_only": kw.get("read_only", 0), "read_only_depends_on": kw.get("read_only_depends_on"),
        "report_hide": 0, "reqd": 0, "search_index": kw.get("search_index", 0),
        "show_dashboard": 0, "show_in_report_builder": 0, "sort_options": 0,
        "translatable": 0, "unique": 0, "width": None,
    }


def dls(fieldname, fieldtype, label, insert_after, **kw):
    return cf("Daily Loading Schedule", fieldname, fieldtype, label, insert_after, **kw)


def ro(fieldname, fieldtype, label, insert_after, **kw):
    return dls(fieldname, fieldtype, label, insert_after, read_only=1,
               depends_on="eval:doc.haulage_settled_on", **kw)


DLS_FIELDS = [
    dls("haulage_section", "Section Break", "Haulage Costing (IAS 2)", "force_close_reason", collapsible=1),
    dls("haulage_mode", "Select", "Haulage Mode", "haulage_section",
        options="Own Fleet\nThird-Party Hauler", default="Own Fleet", no_copy=0,
        allow_on_submit=1, read_only_depends_on=LOCKED, in_standard_filter=1),
    # The DLS already has a native `hauler` (Link Supplier) in the Truck section -- reused, not duplicated.
    dls("haulage_rate_per_kg", "Currency", "Agreed / Override Haulage Rate (per kg)", "haulage_mode",
        no_copy=0, allow_on_submit=1, read_only_depends_on=LOCKED,
        description="Leave BLANK to use the Route Rate table (each drop priced by its own route). "
                    "Third-Party Hauler: enter the agreed freight rate per kg -- it overrides the "
                    "route table for every drop. Locked once the trip is dispatched."),
    dls("haulage_cb1", "Column Break", None, "haulage_rate_per_kg"),
    ro("haulage_loaded_kg", "Float", "Loaded (kg)", "haulage_cb1"),
    ro("haulage_delivered_kg", "Float", "Delivered to Outlets (kg)", "haulage_loaded_kg"),
    ro("haulage_returned_kg", "Float", "Returned to Source (kg)", "haulage_delivered_kg"),
    ro("haulage_retained_kg", "Float", "Retained Onboard / Lost (kg)", "haulage_returned_kg"),
    dls("haulage_cb2", "Column Break", None, "haulage_retained_kg"),
    ro("haulage_actual_cost", "Currency", "Actual Trip Cost", "haulage_cb2"),
    ro("haulage_accrued_cost", "Currency", "of which Accrued (not yet invoiced)", "haulage_actual_cost"),
    ro("haulage_capitalised_cost", "Currency", "Capitalised to Stock (standard)", "haulage_accrued_cost"),
    ro("haulage_unproductive_cost", "Currency", "Unproductive Haulage (P&L)", "haulage_capitalised_cost"),
    ro("haulage_variance", "Currency", "Haulage Variance (P&L)", "haulage_unproductive_cost"),
    dls("haulage_cb3", "Column Break", None, "haulage_variance"),
    ro("unproductive_cause", "Data", "Unproductive Cause", "haulage_cb3"),
    ro("unproductive_cost_center", "Link", "Unproductive Cost Center", "unproductive_cause",
       options="Cost Center"),
    ro("haulage_settlement_je", "Link", "Settlement Journal Entry", "unproductive_cost_center",
       options="Journal Entry"),
    ro("haulage_settled_by", "Link", "Settled By", "haulage_settlement_je", options="User"),
    ro("haulage_settled_on", "Datetime", "Settled On", "haulage_settled_by"),
]

TRIP_LINK_DOCTYPES = ["Purchase Invoice", "Payment Entry", "Employee Advance", "Expense Claim", "Journal Entry"]
TRIP_LINK_FIELDS = [
    cf(dt, "sungas_loading_schedule", "Link", "Trip (Daily Loading Schedule)", "posting_date",
       options="Daily Loading Schedule", in_standard_filter=1, search_index=1,
       description="Link trip costs, hauler/driver advances and prepaid drawdowns to the trip. "
                   "Code the cost line to the Logistics Cost Clearing account.")
    for dt in TRIP_LINK_DOCTYPES
]

WAREHOUSE_FIELDS = [
    cf("Warehouse", "sungas_operations_cost_center", "Link", "Operations Cost Center",
       "custom_default_cost_center", options="Cost Center", no_copy=0,
       description="Outlet Operations cost centre. Charged with unproductive haulage / haulage "
                   "variance. Falls back to the outlet's default cost centre when blank."),
]

CUSTOM_FIELDS = DLS_FIELDS + TRIP_LINK_FIELDS + WAREHOUSE_FIELDS

CLIENT_SCRIPT = {
    "doctype": "Client Script",
    "dt": "Daily Loading Schedule",
    "enabled": 1,
    "module": None,
    "name": "DLS Haulage Costing UI",
    "script": """// Patch 0016 -- IAS 2 trip cost pool: settled banner + Settle Trip Costs dialog.
const SUNGAS_FINANCE_ROLES = ['LPG Head of Finance', 'Accounts Manager', 'System Manager'];

function sungas_haulage_preview_html(p) {
    const cur = (v) => format_currency(v || 0, frappe.defaults.get_default('currency'));
    const row = (label, value, tid) =>
        `<tr><td>${label}</td><td class="text-right" data-testid="${tid}">${value}</td></tr>`;
    return `<table class="table table-bordered table-sm" data-testid="haulage-preview-table">
        ${row(__('Loaded (kg)'), p.loaded_kg, 'haulage-preview-loaded')}
        ${row(__('Delivered to outlets (kg)'), p.delivered_kg, 'haulage-preview-delivered')}
        ${row(__('Returned to source (kg)'), p.returned_kg, 'haulage-preview-returned')}
        ${row(__('Retained onboard / lost (kg)'), p.retained_kg, 'haulage-preview-retained')}
        ${row(__('Actual trip cost posted to clearing'), cur(p.actual_cost), 'haulage-preview-actual')}
        ${row(__('Capitalised on receipts (standard)'), cur(p.capitalised_cost), 'haulage-preview-capitalised')}
        ${row(__('Unproductive haulage (before accrual)'), cur(p.unproductive_cost), 'haulage-preview-unproductive')}
        ${row(__('Haulage variance (before accrual)'), cur(p.variance), 'haulage-preview-variance')}
    </table>
    <p class="text-muted small">${__('Any accrual you enter is added to the actual cost and shared the same way (loaded kg). Clearing nets to zero after posting.')}</p>`;
}

function sungas_open_settle_dialog(frm) {
    frappe.call({
        method: 'sungas.overrides.haulage_costing.preview_trip_costs',
        args: { ls: frm.doc.name },
        freeze: true,
    }).then((r) => {
        const p = r.message;
        if (!p) return;
        const d = new frappe.ui.Dialog({
            title: __('Settle Trip Costs -- {0}', [frm.doc.name]),
            fields: [
                { fieldtype: 'HTML', fieldname: 'preview', options: sungas_haulage_preview_html(p) },
                { fieldtype: 'Currency', fieldname: 'accrual_amount', label: __('Accrue un-invoiced freight (NGN)'),
                  description: __('Hauler freight (or other trip cost) not yet invoiced. Credited to Freight Accrued; the later Purchase Invoice clears it.') },
                { fieldtype: 'Link', fieldname: 'accrual_supplier', label: __('Hauler for accrual'), options: 'Supplier',
                  default: frm.doc.hauler, depends_on: 'eval:doc.accrual_amount>0' },
                { fieldtype: 'Select', fieldname: 'cause', label: __('Cause of undelivered kg'),
                  options: [''].concat(p.causes).join('\\n'), reqd: p.undelivered_kg > 0 ? 1 : 0,
                  description: __('Destination -> destination Operations CC. Source -> source Operations CC. HQ call -> HQ Operations CC.') },
                { fieldtype: 'Select', fieldname: 'cause_outlet', label: __('Destination outlet at fault'),
                  options: [''].concat(p.destinations).join('\\n'),
                  depends_on: `eval:doc.cause=='${p.cause_destination}'` },
                { fieldtype: 'Small Text', fieldname: 'remarks', label: __('Remarks') },
            ],
            primary_action_label: __('Post Settlement'),
            primary_action(values) {
                frappe.call({
                    method: 'sungas.overrides.haulage_costing.settle_trip_costs',
                    args: Object.assign({ ls: frm.doc.name }, values),
                    freeze: true,
                    freeze_message: __('Posting trip cost settlement...'),
                }).then((res) => {
                    if (res && res.message && res.message.ok) {
                        d.hide();
                        frappe.show_alert({ message: __('Trip costs settled.'), indicator: 'green' });
                        frm.reload_doc();
                    }
                });
            },
        });
        d.show();
    });
}

frappe.ui.form.on('Daily Loading Schedule', {
    refresh(frm) {
        if (!frm.doc || frm.doc.docstatus === 2) return;
        if (frm.doc.haulage_settled_on) {
            frm.dashboard.set_headline_alert(
                __('Trip costs settled{0}.', [frm.doc.haulage_settlement_je ? ' -- ' + frm.doc.haulage_settlement_je : '']),
                'green'
            );
            return;
        }
        if (!['Dispatched', 'Closed'].includes(frm.doc.state)) return;
        const roles = frappe.user_roles || [];
        if (!SUNGAS_FINANCE_ROLES.some((role) => roles.includes(role))) return;
        frm.add_custom_button(__('Settle Trip Costs'), () => sungas_open_settle_dialog(frm), __('Actions'));
    },
    haulage_mode(frm) {
        frm.toggle_reqd('hauler', frm.doc.haulage_mode === 'Third-Party Hauler');
    },
    onload_post_render(frm) {
        frm.toggle_reqd('hauler', frm.doc.haulage_mode === 'Third-Party Hauler');
    },
});
""",
    "view": "Form",
}

IOVC_SCRIPT = "Inter-Outlet Variance Case Resolve"
IOVC_ANCHOR = "        git_wh = 'Goods In Transit - SCL'\n        op_se = None\n"
IOVC_TRIP = (
    "        # Patch 0016 -- returned / redelivered gas stays on its original trip.\n"
    "        trip_ls = frappe.db.get_value('Stock Entry', doc.get('receipt_entry'), 'loading_schedule') if doc.get('receipt_entry') else None\n"
)
IOVC_INSERT = "            op_se.insert(ignore_permissions=True)\n            op_se.submit()\n"
IOVC_STAMP = "            if trip_ls:\n                op_se.loading_schedule = trip_ls\n"


def patch_iovc(scripts):
    for s in scripts:
        if s["name"] != IOVC_SCRIPT or "trip_ls" in s["script"]:
            continue
        src = s["script"]
        assert src.count(IOVC_ANCHOR) == 1 and src.count(IOVC_INSERT) == 2
        src = src.replace(IOVC_ANCHOR, IOVC_ANCHOR + IOVC_TRIP)
        s["script"] = src.replace(IOVC_INSERT, IOVC_STAMP + IOVC_INSERT)
    return scripts


# 0016a -- removed: clashed with the DLS's native `hauler` field.
DROPPED = {"Daily Loading Schedule-hauler"}


def upsert(path, records):
    data = json.loads(path.read_text())
    names = {r["name"] for r in records} | DROPPED
    data = [d for d in data if d.get("name") not in names] + records
    path.write_text(json.dumps(data, indent=1) + "\n")


def main():
    upsert(FIXTURES / "custom_field.json", CUSTOM_FIELDS)
    print(f"[1/3] custom_field.json -- +{len(CUSTOM_FIELDS)} fields (DLS haulage, trip links, warehouse ops CC)")
    upsert(FIXTURES / "client_script.json", [CLIENT_SCRIPT])
    print("[2/3] client_script.json -- +DLS Haulage Costing UI")
    ss_path = FIXTURES / "server_script.json"
    ss_path.write_text(json.dumps(patch_iovc(json.loads(ss_path.read_text())), indent=1) + "\n")
    print("[3/3] server_script.json -- IOVC Resolve stamps loading_schedule on return/redelivery SEs")


if __name__ == "__main__":
    main()
