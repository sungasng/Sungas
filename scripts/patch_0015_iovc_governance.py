"""Patch 0015 -- IOVC Governance Parity + Truck-Residual Resolution.

Adds to Inter-Outlet Variance Case (IOVC):
  * 5 new resolution options: Return to Source, Redeliver to another Outlet,
    Hold in GIT (Pending), Hauler Liable, Driver Liable
  * HoF Write-Off Gate (parity with TLVC Patch 0013)
  * Operational resolution SE back-link + redelivery destination
  * HoF remarks field

Mirrors TLVC's docstatus + role-gated pattern (no new Workflow doctype).
Server script `Inter-Outlet Variance Case Resolve` is rewritten to:
  - Cancel the auto-created clearing MI for operational resolutions
    (Return to Source / Redeliver / Hold)
  - Create reverse/forward Material Transfer SE for the physical movement
  - Keep existing JE logic for Hauler/Driver Liable + Write-Off
  - Enforce HoF stamp for Write-Off resolutions
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "sungas" / "fixtures"


# ---------------------------------------------------------------------------
# 1. Property Setter: expand IOVC `resolution` field options
# ---------------------------------------------------------------------------
IOVC_RESOLUTION_OPTIONS = "\n".join([
    "",  # empty-first so field is non-mandatory on Draft
    "Identify culpable staff and recover",
    "Write-off as transit loss",
    "No action / qty corrected separately",
    "Return to Source",
    "Redeliver to another Outlet",
    "Hold in GIT (Pending)",
    "Hauler Liable",
    "Driver Liable",
])

PROP_SETTER_RESOLUTION = {
    "doc_type": "Inter-Outlet Variance Case",
    "doctype": "Property Setter",
    "doctype_or_field": "DocField",
    "field_name": "resolution",
    "is_system_generated": 0,
    "module": None,
    "name": "Inter-Outlet Variance Case-resolution-options",
    "property": "options",
    "property_type": "Text",
    "value": IOVC_RESOLUTION_OPTIONS,
}


# ---------------------------------------------------------------------------
# 2. Custom Fields on IOVC
# ---------------------------------------------------------------------------
def _cf(dt, fieldname, fieldtype, label, **kw):
    """Boilerplate Custom Field builder matching existing fixture shape."""
    row = {
        "allow_in_quick_entry": 0,
        "allow_on_submit": kw.get("allow_on_submit", 0),
        "bold": 0,
        "collapsible": 0,
        "collapsible_depends_on": None,
        "columns": 0,
        "default": kw.get("default"),
        "depends_on": kw.get("depends_on"),
        "description": kw.get("description"),
        "docstatus": 0,
        "doctype": "Custom Field",
        "dt": dt,
        "fetch_from": None,
        "fetch_if_empty": 0,
        "fieldname": fieldname,
        "fieldtype": fieldtype,
        "hidden": 0,
        "hide_border": 0,
        "hide_days": 0,
        "hide_seconds": 0,
        "ignore_user_permissions": 0,
        "ignore_xss_filter": 0,
        "in_global_search": 0,
        "in_list_view": 0,
        "in_preview": 0,
        "in_standard_filter": 0,
        "insert_after": kw.get("insert_after", "resolution"),
        "is_system_generated": 0,
        "is_virtual": 0,
        "label": label,
        "length": 0,
        "mandatory_depends_on": kw.get("mandatory_depends_on"),
        "modified": "2026-02-28 00:00:00.000000",
        "module": None,
        "name": f"{dt}-{fieldname}",
        "no_copy": kw.get("no_copy", 0),
        "non_negative": 0,
        "options": kw.get("options"),
        "permlevel": 0,
        "placeholder": None,
        "precision": "",
        "print_hide": 0,
        "print_hide_if_no_value": 0,
        "print_width": None,
        "read_only": kw.get("read_only", 0),
        "read_only_depends_on": None,
        "report_hide": 0,
        "reqd": 0,
        "search_index": 0,
        "show_dashboard": 0,
        "show_in_report_builder": 0,
        "sort_options": 0,
        "translatable": 0,
        "unique": 0,
        "width": None,
    }
    return row


NEW_IOVC_FIELDS = [
    _cf(
        "Inter-Outlet Variance Case",
        "redelivery_destination",
        "Link",
        "Redelivery Destination Warehouse",
        options="Warehouse",
        insert_after="resolution",
        description="Required when Resolution = 'Redeliver to another Outlet'. The warehouse "
                    "the truck should drive to instead of returning to source.",
        depends_on="eval:doc.resolution=='Redeliver to another Outlet'",
        mandatory_depends_on="eval:doc.resolution=='Redeliver to another Outlet'",
    ),
    _cf(
        "Inter-Outlet Variance Case",
        "operational_resolution_se",
        "Link",
        "Operational Resolution Stock Entry",
        options="Stock Entry",
        insert_after="clearing_stock_entry",
        read_only=1,
        no_copy=1,
        description="Auto-stamped by the Resolve script for Return to Source / Redeliver / Hold. "
                    "Points at the reverse (or re-destined) Material Transfer that moved the "
                    "physical residual.",
    ),
    _cf(
        "Inter-Outlet Variance Case",
        "hof_remarks",
        "Small Text",
        "HoF Write-Off Remarks",
        insert_after="hod_finance_notes",
        description="Captured when the LPG Head of Finance stamps a Write-Off approval. "
                    "Visible on the Resolve audit trail.",
        read_only=1,
    ),
    _cf(
        "Inter-Outlet Variance Case",
        "clearing_cancelled",
        "Check",
        "Clearing MI Cancelled",
        insert_after="operational_resolution_se",
        read_only=1,
        no_copy=1,
        description="Set to 1 when the auto-created clearing Material Issue has been cancelled "
                    "because the physical gas was recovered (returned, redelivered, or held).",
    ),
]


# ---------------------------------------------------------------------------
# 3. Rewritten Server Script -- Inter-Outlet Variance Case Resolve
# ---------------------------------------------------------------------------
NEW_RESOLVE_SCRIPT = '''# Patch 0015 -- IOVC Resolve with operational + party-liability paths + HoF gate.
if not doc.get('resolution'):
    frappe.throw('Resolution is required before submitting a variance case.')
if not (doc.get('hod_ops_signed_by') or '').strip():
    frappe.throw('HOD Ops sign-off is required before submitting a variance case.')

policy = frappe.get_doc('Sungas Close Policy', 'Sungas Close Policy')
suspense_acc = policy.get('it_suspense_account') or '2609 - Stock Variance In Transit Recovery - SCL'
writeoff_acc = policy.get('it_writeoff_account') or '1609 - GIT - Transit Loss - SCL'
recov_acc = policy.get('it_employee_recoverable_account') or '2900 - Staff Loan Receivable - SCL'
amount = doc.value_variance or 0
res = doc.resolution

# -----------------------------------------------------------------
# Group A: OPERATIONAL -- physical gas recovered; cancel the clearing MI
# and (optionally) create a reverse / redelivery Material Transfer.
# No GL entries beyond the cancellation reversal.
# -----------------------------------------------------------------
OPERATIONAL = ('Return to Source', 'Redeliver to another Outlet', 'Hold in GIT (Pending)')
if res in OPERATIONAL:
    if doc.get('operational_resolution_se'):
        pass  # idempotent -- already resolved
    else:
        # Step 1: cancel the auto-created clearing Material Issue so GIT is restored
        clearing_name = doc.get('clearing_stock_entry')
        if clearing_name and not doc.get('clearing_cancelled'):
            try:
                clearing = frappe.get_doc('Stock Entry', clearing_name)
                if clearing.docstatus == 1:
                    clearing.cancel()
                doc.clearing_cancelled = 1
            except Exception as e:
                frappe.log_error(title='IOVC clearing cancel failed', message=str(e))
                frappe.throw('Could not cancel clearing SE %s. See Error Log.' % clearing_name)
        # Step 2: physical movement
        git_wh = 'Goods In Transit - SCL'
        op_se = None
        if res == 'Return to Source':
            src = doc.get('source_warehouse')
            if not src:
                frappe.throw('Source Outlet is missing on this case; cannot return to source.')
            op_se = frappe.new_doc('Stock Entry')
            op_se.stock_entry_type = 'Material Transfer'
            op_se.purpose = 'Material Transfer'
            op_se.company = doc.company
            op_se.from_warehouse = git_wh
            op_se.to_warehouse = src
            op_se.set_posting_time = 1
            op_se.remarks = 'IOVC %s Return-to-Source. Physical gas returned to %s.' % (doc.name, src)
            # Pull row items from the clearing MI so qty is correct
            if clearing_name:
                src_items = frappe.get_all('Stock Entry Detail',
                    filters={'parent': clearing_name},
                    fields=['item_code', 'qty', 'basic_rate'])
                for r in src_items:
                    op_se.append('items', {
                        'item_code': r['item_code'], 'qty': r['qty'],
                        's_warehouse': git_wh, 't_warehouse': src,
                        'basic_rate': r['basic_rate'],
                    })
            op_se.insert(ignore_permissions=True)
            op_se.submit()
        elif res == 'Redeliver to another Outlet':
            dest = doc.get('redelivery_destination')
            if not dest:
                frappe.throw('Redelivery Destination Warehouse is required for this resolution.')
            op_se = frappe.new_doc('Stock Entry')
            op_se.stock_entry_type = 'Material Transfer'
            op_se.purpose = 'Material Transfer'
            op_se.company = doc.company
            op_se.from_warehouse = git_wh
            op_se.to_warehouse = dest
            op_se.set_posting_time = 1
            op_se.remarks = 'IOVC %s Redelivery. Physical gas redelivered to %s.' % (doc.name, dest)
            if clearing_name:
                src_items = frappe.get_all('Stock Entry Detail',
                    filters={'parent': clearing_name},
                    fields=['item_code', 'qty', 'basic_rate'])
                for r in src_items:
                    op_se.append('items', {
                        'item_code': r['item_code'], 'qty': r['qty'],
                        's_warehouse': git_wh, 't_warehouse': dest,
                        'basic_rate': r['basic_rate'],
                    })
            op_se.insert(ignore_permissions=True)
            op_se.submit()
        # 'Hold in GIT (Pending)' -- no new SE; the clearing cancellation leaves gas in GIT.
        if op_se:
            doc.operational_resolution_se = op_se.name

# -----------------------------------------------------------------
# Group B: NO ACTION -- already-corrected elsewhere.
# -----------------------------------------------------------------
elif res == 'No action / qty corrected separately':
    pass

# -----------------------------------------------------------------
# Group C: FINANCIAL -- JE moves suspense into recovery/write-off account.
# -----------------------------------------------------------------
elif amount <= 0:
    pass
elif doc.get('resolution_journal_entry'):
    pass  # idempotent
else:
    # Write-Off requires HoF sign-off (parity with TLVC Patch 0013)
    if res == 'Write-off as transit loss' and not (doc.get('hod_finance_signed_by') or '').strip():
        frappe.throw(
            'Inter-Outlet write-offs require explicit sign-off from LPG Head of Finance. '
            'Click the "Approve Write-Off as HoF" button on this case first '
            '(available only to the HoF role).'
        )
    je = frappe.new_doc('Journal Entry')
    je.voucher_type = 'Journal Entry'
    je.company = doc.company
    je.posting_date = frappe.utils.today()
    if res == 'Identify culpable staff and recover':
        if not doc.get('culpable_employee'):
            frappe.throw('Culpable Employee is required for staff recovery resolution.')
        je.user_remark = ('Stage 2.2: clear suspense to Staff Loan Receivable for variance case %s. '
                          'Culpable employee: %s. Amount NGN %.2f.' %
                          (doc.name, doc.culpable_employee, amount))
        je.append('accounts', {'account': suspense_acc, 'credit_in_account_currency': amount, 'debit_in_account_currency': 0})
        je.append('accounts', {
            'account': recov_acc, 'party_type': 'Employee', 'party': doc.culpable_employee,
            'debit_in_account_currency': amount, 'credit_in_account_currency': 0,
        })
    elif res == 'Driver Liable':
        if not doc.get('culpable_employee'):
            frappe.throw('Culpable Employee (driver) is required for Driver Liable resolution.')
        je.user_remark = 'Inter-Outlet variance %s -- in-house driver %s liable. Amount NGN %.2f.' % (
            doc.name, doc.culpable_employee, amount)
        je.append('accounts', {'account': suspense_acc, 'credit_in_account_currency': amount})
        je.append('accounts', {
            'account': recov_acc, 'party_type': 'Employee', 'party': doc.culpable_employee,
            'debit_in_account_currency': amount,
        })
    elif res == 'Hauler Liable':
        if not doc.get('hauler'):
            frappe.throw('Hauler is required for Hauler Liable resolution. Set the hauler supplier on the dispatching SE.')
        co = frappe.get_doc('Company', doc.company)
        payable_account = co.default_payable_account
        if not payable_account:
            frappe.throw('Company default payable account not set; cannot post hauler charge.')
        je.user_remark = 'Inter-Outlet variance %s -- 3rd-party hauler %s liable. Amount NGN %.2f.' % (
            doc.name, doc.hauler, amount)
        je.append('accounts', {
            'account': payable_account, 'party_type': 'Supplier', 'party': doc.hauler,
            'debit_in_account_currency': amount, 'company': doc.company,
        })
        je.append('accounts', {'account': suspense_acc, 'credit_in_account_currency': amount})
    elif res == 'Write-off as transit loss':
        je.user_remark = ('Stage 2.2: write off variance case %s to 1609 - GIT - Transit Loss. '
                          'HoF-approved by %s. Amount NGN %.2f.' %
                          (doc.name, doc.hod_finance_signed_by, amount))
        je.append('accounts', {'account': suspense_acc, 'credit_in_account_currency': amount})
        je.append('accounts', {'account': writeoff_acc, 'debit_in_account_currency': amount})
    else:
        frappe.throw('Unknown resolution value: %s' % res)
    je.insert(ignore_permissions=True)
    je.submit()
    doc.resolution_journal_entry = je.name
'''


# ---------------------------------------------------------------------------
# 4. Client Script -- IOVC HoF Write-Off Gate UI (mirror TLVC Patch 0013)
# ---------------------------------------------------------------------------
IOVC_HOF_CLIENT_SCRIPT = {
    "doctype": "Client Script",
    "dt": "Inter-Outlet Variance Case",
    "enabled": 1,
    "module": None,
    "name": "IOVC HoF Write-Off Gate UI",
    "script": """// Patch 0015 -- IOVC Write-Off HoF Gate UI (mirrors TLVC Patch 0013).
// Shows an 'Approve Write-Off as HoF' button on Draft Inter-Outlet
// Variance Cases where Resolution = 'Write-off as transit loss' and
// the HoF stamp is still empty. Visible ONLY to LPG Head of Finance.
frappe.ui.form.on('Inter-Outlet Variance Case', {
    refresh(frm) {
        if (!frm.doc || frm.doc.docstatus !== 0) return;
        if (frm.doc.resolution !== 'Write-off as transit loss') return;
        if (frm.doc.hod_finance_signed_by) {
            frm.dashboard.add_indicator(
                __(`HoF Write-Off Approved by ${frm.doc.hod_finance_signed_by.split('@')[0]}`),
                'green'
            );
            return;
        }
        const roles = frappe.user_roles || [];
        if (!roles.includes('LPG Head of Finance') && !roles.includes('System Manager')) {
            frm.dashboard.add_indicator(
                __('Pending LPG Head of Finance Write-Off Approval'),
                'orange'
            );
            return;
        }
        frm.add_custom_button(__('Approve Write-Off as HoF'), () => {
            frappe.prompt([{
                fieldtype: 'Small Text',
                label: 'Remarks (optional)',
                fieldname: 'remarks',
                description: 'Why are you approving this write-off? Will be stamped on the case.'
            }], (values) => {
                frappe.call({
                    method: 'sungas.api.governance.approve_writeoff_as_hof_iovc',
                    args: { case: frm.doc.name, remarks: values.remarks || '' },
                    freeze: true,
                    freeze_message: __('Stamping HoF approval...'),
                }).then((r) => {
                    if (r && r.message && r.message.ok) {
                        frappe.show_alert({ message: __('Write-Off approved as HoF'), indicator: 'green' });
                        frm.reload_doc();
                    }
                });
            }, __('Approve Write-Off'), __('Approve'));
        }, __('Approvals')).addClass('btn-primary');
    }
});
""",
    "view": "Form",
}


def main() -> None:
    # 1. Property Setter
    ps_path = FIXTURES / "property_setter.json"
    ps = json.loads(ps_path.read_text())
    ps = [p for p in ps if p.get("name") != PROP_SETTER_RESOLUTION["name"]]
    ps.append(PROP_SETTER_RESOLUTION)
    ps_path.write_text(json.dumps(ps, indent=1) + "\n")
    print(f"[1/4] property_setter.json -- {PROP_SETTER_RESOLUTION['name']}")

    # 2. Custom Fields
    cf_path = FIXTURES / "custom_field.json"
    cf = json.loads(cf_path.read_text())
    new_names = {f["name"] for f in NEW_IOVC_FIELDS}
    cf = [c for c in cf if c.get("name") not in new_names]
    cf.extend(NEW_IOVC_FIELDS)
    cf_path.write_text(json.dumps(cf, indent=1) + "\n")
    print(f"[2/4] custom_field.json -- +{len(NEW_IOVC_FIELDS)} IOVC fields")

    # 3. Server Script
    ss_path = FIXTURES / "server_script.json"
    ss = json.loads(ss_path.read_text())
    for e in ss:
        if e.get("name") == "Inter-Outlet Variance Case Resolve":
            e["script"] = NEW_RESOLVE_SCRIPT
            break
    else:
        raise SystemExit("ERROR: Inter-Outlet Variance Case Resolve not found")
    # 4. Client Script
    cs_path = FIXTURES / "client_script.json"
    cs = json.loads(cs_path.read_text())
    cs = [c for c in cs if c.get("name") != IOVC_HOF_CLIENT_SCRIPT["name"]]
    cs.append(IOVC_HOF_CLIENT_SCRIPT)
    ss_path.write_text(json.dumps(ss, indent=1) + "\n")
    cs_path.write_text(json.dumps(cs, indent=1) + "\n")
    print(f"[3/4] server_script.json -- rewrote Inter-Outlet Variance Case Resolve")
    print(f"[4/4] client_script.json -- +{IOVC_HOF_CLIENT_SCRIPT['name']}")
    print("[Patch 0015] fixtures updated OK")


if __name__ == "__main__":
    main()
