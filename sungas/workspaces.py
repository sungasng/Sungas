"""Patch 0020 -- role landing workspaces + module isolation.

Each user lands on the workspace of their highest-priority Sungas persona
and the sidebar only shows modules their personas use (User.block_modules,
purely visual -- permissions are untouched). System Managers, users with
a Module Profile and users without a Sungas persona are left alone.

`install()` runs after every migrate: upserts the KPI Number Cards and the
five workspaces, then re-syncs every user. The User `validate` hook keeps
it in step whenever roles change.
"""
from __future__ import annotations

import json

import frappe

# Persona order = priority when a user holds several.
PERSONAS = [
    {"key": "ops", "workspace": "Sungas Ops Command", "module": "Stock", "icon": "truck",
     "roles": ["COO", "LPG Head of Operations"],
     "modules": ["Stock", "Buying", "Selling", "Assets", "POSAwesome", "Sungas"]},
    {"key": "finance", "workspace": "Sungas Finance", "module": "Accounts", "icon": "accounting",
     "roles": ["LPG Head of Finance", "Accounts Manager"],
     "modules": ["Accounts", "Stock", "Buying", "Selling", "Assets", "Payroll", "Sungas"]},
    {"key": "hr", "workspace": "Sungas HR Desk", "module": "HR", "icon": "hr",
     "roles": ["LPG Head of HR", "HR Manager", "HR User"],
     "modules": ["HR", "Payroll", "Sungas"]},
    {"key": "sales", "workspace": "Sungas Sales", "module": "Selling", "icon": "sell",
     "roles": ["LPG Head of Sales", "LPG Deputy Head of Sales", "LPG Sales Executive", "Sales Manager"],
     "modules": ["Selling", "CRM", "FCRM", "Stock", "POSAwesome", "Sungas"]},
    {"key": "plant", "workspace": "Sungas My Plant", "module": "Stock", "icon": "organization",
     "roles": ["LPG Plant Manager"],
     "modules": ["Stock", "POSAwesome", "Sungas"]},
    # Cashiers keep the existing POS Awesome workspace.
    {"key": "cashier", "workspace": "POS Awesome", "module": None, "icon": None,
     "roles": ["LPG POS User"], "modules": ["POSAwesome", "Sungas"]},
]
OUR_WORKSPACES = {p["workspace"] for p in PERSONAS}
EXEMPT_ROLES = {"System Manager", "Workspace Manager"}

ME = "frappe.session.user"


def _card(dt, filters, dynamic=None, color="#2980b9", fn="Count", based_on=None):
    return {"document_type": dt, "filters": filters, "dynamic": dynamic, "color": color,
            "function": fn, "based_on": based_on}


NEW_CARDS = {
    "Sungas · My Open Tasks": _card("ToDo", [["ToDo", "status", "=", "Open"]],
                                    [["ToDo", "allocated_to", "=", ME]], "#e67e22"),
    "Sungas · My Unread Alerts": _card("Notification Log", [["Notification Log", "read", "=", 0]],
                                       [["Notification Log", "for_user", "=", ME]], "#c0392b"),
    "Sungas · Receipts Awaiting Confirmation": _card("Stock Entry", [
        ["Stock Entry", "docstatus", "=", 0], ["Stock Entry", "purpose", "=", "Material Transfer"],
        ["Stock Entry", "outgoing_stock_entry", "is", "set"]], color="#2980b9"),
    "Sungas · Open Variance Cases": _card("Inter-Outlet Variance Case", [
        ["Inter-Outlet Variance Case", "workflow_state", "not in", ["Approved", "Rejected"]]], color="#c0392b"),
    "Sungas · Open Transit Loss Cases": _card("Transit Loss Variance Case", [
        ["Transit Loss Variance Case", "docstatus", "=", 0]], color="#d35400"),
    "Sungas · Open POS Shifts": _card("POS Opening Shift", [
        ["POS Opening Shift", "status", "=", "Open"], ["POS Opening Shift", "docstatus", "=", 1]], color="#16a085"),
    "Sungas · Trips In Transit": _card("Daily Loading Schedule", [
        ["Daily Loading Schedule", "state", "=", "Dispatched"]], color="#8e44ad"),
    "Sungas · Trips Awaiting Cost Settlement": _card("Daily Loading Schedule", [
        ["Daily Loading Schedule", "state", "in", ["Dispatched", "Closed"]],
        ["Daily Loading Schedule", "dispatch_stock_entry", "is", "set"],
        ["Daily Loading Schedule", "haulage_settled_on", "is", "not set"]], color="#8e44ad"),
    "Sungas · Write-Offs Awaiting HoF": _card("Transit Loss Variance Case", [
        ["Transit Loss Variance Case", "docstatus", "=", 0],
        ["Transit Loss Variance Case", "resolution", "=", "Written Off"],
        ["Transit Loss Variance Case", "hod_finance_signed_by", "is", "not set"]], color="#c0392b"),
    "Sungas · IOVC Pending HoF": _card("Inter-Outlet Variance Case", [
        ["Inter-Outlet Variance Case", "workflow_state", "=", "Pending HoF Approval"]], color="#c0392b"),
    "Sungas · Shift Variances Pending HoF": _card("POS Closing Shift", [
        ["POS Closing Shift", "workflow_state", "=", "Pending HOD Finance"]], color="#e74c3c"),
    "Sungas · Price Requests Open": _card("LPG Price Change Request", [
        ["LPG Price Change Request", "docstatus", "=", 0]], color="#f39c12"),
    "Sungas · Bulk Price Uploads Pending": _card("LPG Bulk Price Upload", [
        ["LPG Bulk Price Upload", "docstatus", "=", 0]], color="#f39c12"),
    "Sungas · Leave Applications Open": _card("Leave Application", [
        ["Leave Application", "status", "=", "Open"], ["Leave Application", "docstatus", "=", 0]], color="#27ae60"),
}

COMMON = ["Sungas · My Open Tasks", "Sungas · My Unread Alerts"]


def _sc(label, link_to, kind="DocType", stats=None, color="Blue", url=None):
    return {"label": label, "type": kind, "link_to": link_to, "url": url, "color": color,
            "doc_view": "List" if kind == "DocType" else None, "stats_filter": stats}


MY_TASKS = _sc("My Tasks", "ToDo", stats='{"status": "Open", "allocated_to": frappe.session.user}', color="Orange")
POS_APP = _sc("POS Awesome", "posapp", kind="Page", color="Green")

LAYOUT = {
    "Sungas My Plant": {
        "cards": COMMON + ["Sungas · Receipts Awaiting Confirmation", "Sungas · Open POS Shifts",
                           "Sungas · Open Variance Cases", "Sungas · Open Transit Loss Cases"],
        "charts": ["Sungas Ops · Tank Volume by Outlet"],
        "shortcuts": [MY_TASKS, POS_APP,
                      _sc("Receipts to Confirm", "Stock Entry", stats='{"docstatus": 0}'),
                      _sc("Material Requests", "Material Request"),
                      _sc("Variance Cases", "Inter-Outlet Variance Case", color="Red"),
                      _sc("Transit Loss Cases", "Transit Loss Variance Case", color="Red"),
                      _sc("Shift Closings", "POS Closing Shift")],
    },
    "Sungas Ops Command": {
        "cards": COMMON + ["Sungas Ops · Pending HoO Approvals", "Sungas Ops · Draft Loading Schedules",
                           "Sungas Ops · Trucks Pending Assignment", "Sungas · Trips In Transit",
                           "Sungas Ops · Network Tank Volume", "Sungas Ops · GIT Inter-Outlet",
                           "Sungas Ops · GIT Supplier to Outlet", "Transit Loss — Open Cases (90d)"],
        "charts": ["Sungas Ops · Tank Volume by Outlet", "Transit Loss by Hauler (90d)"],
        "shortcuts": [MY_TASKS,
                      _sc("Loading Schedules", "Daily Loading Schedule"),
                      _sc("Material Requests", "Material Request"),
                      _sc("Variance Cases", "Inter-Outlet Variance Case", color="Red"),
                      _sc("Transit Loss Cases", "Transit Loss Variance Case", color="Red"),
                      _sc("Purchase Receipts", "Purchase Receipt"),
                      _sc("Purchase Orders", "Purchase Order")],
    },
    "Sungas Finance": {
        "cards": COMMON + ["Sungas · Trips Awaiting Cost Settlement", "Sungas · Write-Offs Awaiting HoF",
                           "Sungas · IOVC Pending HoF", "Sungas · Shift Variances Pending HoF",
                           "Sungas · Price Requests Open", "Total Outgoing Bills", "Total Incoming Bills"],
        "charts": ["Bank Balance", "Accounts Receivable Ageing", "Transit Loss Trend (12mo)"],
        "shortcuts": [MY_TASKS,
                      _sc("Journal Entry", "Journal Entry"), _sc("Payment Entry", "Payment Entry"),
                      _sc("Purchase Invoice", "Purchase Invoice"), _sc("Sales Invoice", "Sales Invoice"),
                      _sc("Trips to Settle", "Daily Loading Schedule", color="Purple"),
                      _sc("General Ledger", "General Ledger", kind="Report", color="Grey")],
    },
    "Sungas HR Desk": {
        "cards": COMMON + ["Sungas · Leave Applications Open", "Total Employees", "New Hires (This Year)",
                           "Expense Claims (This Month)", "Total Absent (This Month)"],
        "charts": ["Department Wise Employee Count", "Employees by Branch"],
        "shortcuts": [MY_TASKS,
                      _sc("Employee", "Employee"), _sc("Leave Application", "Leave Application"),
                      _sc("Attendance", "Attendance"), _sc("Expense Claim", "Expense Claim"),
                      _sc("Salary Slip", "Salary Slip"), _sc("Payroll Entry", "Payroll Entry")],
    },
    "Sungas Sales": {
        "cards": COMMON + ["Sungas · Price Requests Open", "Sungas · Bulk Price Uploads Pending",
                           "Active Customers", "Annual Sales", "Sales Orders to Deliver"],
        "charts": ["Territory Wise Sales", "Top Customers"],
        "shortcuts": [MY_TASKS, POS_APP,
                      _sc("Customer", "Customer"), _sc("Sales Order", "Sales Order"),
                      _sc("Sales Invoice", "Sales Invoice"),
                      _sc("Price Change Requests", "LPG Price Change Request", color="Orange"),
                      _sc("Bulk Price Upload", "LPG Bulk Price Upload", color="Orange")],
    },
}


# -- persona resolution (pure) ---------------------------------------------

def resolve(roles, all_modules) -> dict | None:
    """Return {"workspace", "blocked"} for this role set, or None to leave the user alone."""
    roles = set(roles)
    if roles & EXEMPT_ROLES:
        return None
    hits = [p for p in PERSONAS if roles & set(p["roles"])]
    if not hits:
        return None
    allowed = set().union(*(p["modules"] for p in hits))
    return {"workspace": hits[0]["workspace"], "blocked": sorted(set(all_modules) - allowed)}


def apply_to_user(doc, method=None):
    """User validate hook."""
    if doc.name in ("Administrator", "Guest") or doc.get("user_type") != "System User" \
            or doc.get("module_profile"):
        return
    plan = resolve([r.role for r in doc.get("roles") or []], _all_modules())
    if not plan:
        return
    if not frappe.db.exists("Workspace", plan["workspace"]):
        return
    if [b.module for b in doc.get("block_modules") or []] != plan["blocked"]:
        doc.set("block_modules", [{"module": m} for m in plan["blocked"]])
    if not doc.get("default_workspace") or doc.default_workspace in OUR_WORKSPACES:
        doc.default_workspace = plan["workspace"]


def _all_modules():
    return frappe.get_all("Module Def", pluck="name")


# -- install (after_migrate) -----------------------------------------------

def _upsert(dt, name, values):
    doc = frappe.get_doc(dt, name) if frappe.db.exists(dt, name) else frappe.new_doc(dt)
    doc.update(values)
    if doc.is_new():
        doc.name = name
        doc.insert(ignore_permissions=True, set_name=name)
    else:
        doc.save(ignore_permissions=True)


def _install_cards():
    for name, c in NEW_CARDS.items():
        if not frappe.db.exists("DocType", c["document_type"]):
            continue
        _upsert("Number Card", name, {
            "label": name, "type": "Document Type", "document_type": c["document_type"],
            "function": c["function"], "aggregate_function_based_on": c["based_on"],
            "filters_json": json.dumps(c["filters"]),
            "dynamic_filters_json": json.dumps(c["dynamic"]) if c["dynamic"] else None,
            "is_public": 1, "module": "Sungas", "color": c["color"], "show_percentage_stats": 0,
        })


def build_content(layout, cards, charts, shortcuts) -> str:
    blocks = [{"type": "header", "data": {"text": '<span class="h4"><b>Today</b></span>', "col": 12}}]
    blocks += [{"type": "number_card", "data": {"number_card_name": c, "col": 3}} for c in cards]
    if charts:
        blocks.append({"type": "spacer", "data": {"col": 12}})
        blocks += [{"type": "chart", "data": {"chart_name": c, "col": 12 if len(charts) == 1 else 6}}
                   for c in charts]
    blocks.append({"type": "spacer", "data": {"col": 12}})
    blocks.append({"type": "header", "data": {"text": '<span class="h4"><b>Quick Access</b></span>', "col": 12}})
    blocks += [{"type": "shortcut", "data": {"shortcut_name": s["label"], "col": 3}} for s in shortcuts]
    return json.dumps(blocks)


def _install_workspaces():
    for seq, p in enumerate(PERSONAS):
        layout = LAYOUT.get(p["workspace"])
        if not layout:
            continue
        cards = [c for c in layout["cards"] if frappe.db.exists("Number Card", c)]
        charts = [c for c in layout["charts"] if frappe.db.exists("Dashboard Chart", c)]
        shortcuts = [s for s in layout["shortcuts"]
                     if frappe.db.exists({"DocType": "DocType", "Page": "Page", "Report": "Report"}[s["type"]],
                                         s["link_to"])]
        _upsert("Workspace", p["workspace"], {
            "label": p["workspace"], "title": p["workspace"], "module": p["module"], "icon": p["icon"],
            "public": 1, "is_hidden": 0, "sequence_id": 0.1 + seq / 10,
            "content": build_content(layout, cards, charts, shortcuts),
            "number_cards": [{"number_card_name": c, "label": c.replace("Sungas · ", "").replace("Sungas Ops · ", "")}
                             for c in cards],
            "charts": [{"chart_name": c, "label": c} for c in charts],
            "shortcuts": shortcuts,
            "roles": [{"role": r} for r in p["roles"] + ["System Manager"]],
        })


def _fix_sungas_operations_cards():
    """Stage 4 workspace used 'card' blocks for Number Cards, so they never rendered."""
    if not frappe.db.exists("Workspace", "Sungas Operations"):
        return
    ws = frappe.get_doc("Workspace", "Sungas Operations")
    blocks = json.loads(ws.content or "[]")
    changed = False
    for b in blocks:
        name = (b.get("data") or {}).get("card_name")
        if b.get("type") == "card" and name and frappe.db.exists("Number Card", name):
            b["type"] = "number_card"
            b["data"] = {"number_card_name": name, "col": b["data"].get("col", 3)}
            changed = True
    if changed:
        ws.content = json.dumps(blocks)
        ws.save(ignore_permissions=True)


def sync_all_users():
    for name in frappe.get_all("User", filters={"enabled": 1, "user_type": "System User"}, pluck="name"):
        if name in ("Administrator", "Guest"):
            continue
        try:
            doc = frappe.get_doc("User", name)
            before = ([b.module for b in doc.block_modules], doc.default_workspace)
            apply_to_user(doc)
            if before != ([b.module for b in doc.block_modules], doc.default_workspace):
                doc.flags.ignore_permissions = True
                doc.save(ignore_permissions=True)
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"sungas.workspaces sync {name}")


def install():
    try:
        _install_cards()
        _install_workspaces()
        _fix_sungas_operations_cards()
        frappe.db.commit()
        sync_all_users()
        frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "sungas.workspaces.install")
