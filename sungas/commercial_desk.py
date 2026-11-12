"""Patch 0032 -- customer group gate owned by the Commercial Desk.

* New customers are always Retail (till, desk, import) unless created by the Commercial Desk.
* Only the Commercial Desk, Head of Sales / Deputy (and System Manager) can change a customer's group; a reason is
  required and every change is logged as an approved Customer Group Change Request.
* Everyone else raises a Customer Group Change Request; the desk approves / rejects it.
  Pending > 48 h nudges Head of Sales. Alerts go by bell, email and WhatsApp.
"""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_to_date, now_datetime

DESK_ROLE = "LPG Commercial Desk"
HOS_ROLES = ("LPG Head of Sales", "LPG Deputy Head of Sales")
SETTER_ROLES = {DESK_ROLE, "System Manager", *HOS_ROLES}
LOCKED_FIELDS = ("customer_group", "sungas_account_owner", "sungas_expected_monthly_kg")
DEFAULT_GROUP = "Retail"
CGCR = "Customer Group Change Request"
ESCALATE_HOURS = 48
DESK_MEMBERS = ("toyin.falana@sungas.org", "sonia.ogumar@sungas.org")
SERVICE_ACCOUNTS = {"lmd-bot@sungas.org", "clouderp@sungas.org", "Administrator"}


def can_set_group(roles) -> bool:
    return bool(SETTER_ROLES & set(roles or []))


def _users_with(roles) -> list[str]:
    users = frappe.get_all("Has Role", filters={"role": ["in", list(roles)], "parenttype": "User"},
                           pluck="parent", distinct=True)
    return [u for u in frappe.get_all("User", filters={"name": ["in", users or [""]], "enabled": 1},
                                      pluck="name") if u not in SERVICE_ACCOUNTS]


def desk_users() -> list[str]:
    return _users_with([DESK_ROLE])


def _link(name: str) -> str:
    return frappe.utils.get_url(f"/app/customer-group-change-request/{name}")


def _alert(users, subject, body, name, template, wa_vars):
    from sungas.utils.bell import ring
    from sungas.utils import whatsapp

    users = [u for u in users if u]
    if not users:
        return
    ring(users, subject, body, CGCR, name)
    try:
        frappe.sendmail(recipients=[frappe.db.get_value("User", u, "email") or u for u in users],
                        subject=f"[SCL] {subject}", message=body, now=False)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "sungas.commercial_desk email")
    whatsapp.send(users, template, wa_vars, ref=f"{CGCR}:{name}:{template}")


# -- Customer hooks ----------------------------------------------------------

def enforce_customer_group(doc, method=None):
    """Customer validate."""
    if doc.flags.sungas_group_change_ok:
        return
    allowed = can_set_group(frappe.get_roles())
    if doc.is_new():
        if not allowed:
            doc.customer_group = DEFAULT_GROUP
        return
    before = doc.get_doc_before_save()
    if not before:
        return
    if not allowed and any((before.get(f) or None) != (doc.get(f) or None) for f in LOCKED_FIELDS[1:]):
        frappe.throw(_("Only the Commercial Desk or Head of Sales can change the account owner or kg target."),
                     title=_("Commercial Desk Fields Locked"))
    if before.customer_group == doc.customer_group:
        return
    if not allowed:
        frappe.throw(_("Only the Commercial Desk or Head of Sales can change a customer's group. Use "
                       "<b>Request Group Change</b> on the customer (or in the till) and the desk will review it."),
                     title=_("Customer Group Locked"))
    if not (doc.get("sungas_group_change_reason") or "").strip():
        frappe.throw(_("Enter a <b>Reason for group change</b> before changing the customer group."),
                     title=_("Reason Required"))
    doc.flags.sungas_log_group_change = (before.customer_group, doc.customer_group)


def log_direct_change(doc, method=None):
    """Customer on_update: a desk edit is logged as an already-approved request."""
    change = doc.flags.sungas_log_group_change
    if not change:
        return
    doc.flags.sungas_log_group_change = None
    req = frappe.get_doc({
        "doctype": CGCR, "customer": doc.name, "current_group": change[0], "requested_group": change[1],
        "status": "Approved", "direct_change": 1, "justification": doc.sungas_group_change_reason,
        "requested_by": frappe.session.user, "decided_by": frappe.session.user, "decided_on": now_datetime()})
    req.flags.sungas_internal = True
    req.insert(ignore_permissions=True)
    if change[1] != DEFAULT_GROUP and not doc.get("sungas_account_owner"):
        frappe.db.set_value("Customer", doc.name, "sungas_account_owner", frappe.session.user, update_modified=False)


# -- Requests ----------------------------------------------------------------

@frappe.whitelist()
def request_group_change(customer, requested_group, justification, business_type=None,
                         expected_monthly_kg=None, location=None, contact_phone=None, requested_from=None):
    doc = frappe.get_doc({
        "doctype": CGCR, "customer": customer, "requested_group": requested_group,
        "justification": justification, "business_type": business_type,
        "expected_monthly_kg": expected_monthly_kg, "location": location,
        "contact_phone": contact_phone, "requested_from": requested_from})
    doc.insert()
    return doc.name


def notify_new_request(doc):
    who = frappe.db.get_value("User", doc.requested_by, "full_name") or doc.requested_by
    subj = f"Group change request {doc.name}: {doc.customer_name} {doc.current_group} -> {doc.requested_group}"
    body = (f"<p><b>{frappe.utils.escape_html(who)}</b> asks to move <b>{frappe.utils.escape_html(doc.customer_name)}</b> "
            f"from <b>{doc.current_group}</b> to <b>{doc.requested_group}</b>.</p>"
            f"<p>Reason: {frappe.utils.escape_html(doc.justification or '')}<br>Expected: {doc.expected_monthly_kg or 0:g} kg/month</p>"
            f'<p><a href="{_link(doc.name)}">Open request</a></p>')
    for u in desk_users():
        _alert([u], subj, body, doc.name, "sungas_approval_needed", {
            "approver_name": frappe.db.get_value("User", u, "first_name") or "there",
            "doc_label": f"Group change {doc.name}",
            "summary": f"{doc.customer_name}: {doc.current_group} to {doc.requested_group}, "
                       f"{doc.expected_monthly_kg or 0:g} kg/month, by {who}",
            "state": "Pending Commercial Desk", "link": _link(doc.name)})


def plant_manager_for(pos_profile, requester):
    """Default account owner: manager of the plant that raised the request."""
    wh = frappe.db.get_value("POS Profile", pos_profile, "warehouse") if pos_profile else None
    if not wh and requester:
        wh = (frappe.get_all("Warehouse", or_filters={"outlet_plant_manager": requester,
                                                      "outlet_secondary_manager": requester}, pluck="name") or [None])[0]
    return frappe.db.get_value("Warehouse", wh, "outlet_plant_manager") if wh else None


def _decide(name, status, note):
    if not can_set_group(frappe.get_roles()):
        frappe.throw(_("Only the Commercial Desk or Head of Sales can decide group change requests."), frappe.PermissionError)
    doc = frappe.get_doc(CGCR, name)
    if doc.status != "Pending":
        frappe.throw(_("This request is already {0}.").format(doc.status))
    if status == "Rejected" and not (note or "").strip():
        frappe.throw(_("Give a reason for rejecting."))
    doc.status, doc.decision_note = status, note
    doc.decided_by, doc.decided_on = frappe.session.user, now_datetime()
    doc.flags.sungas_internal = True
    doc.save(ignore_permissions=True)
    if status == "Approved":
        cust = frappe.get_doc("Customer", doc.customer)
        cust.customer_group = doc.requested_group
        cust.sungas_group_change_reason = f"{doc.name}: {doc.justification or ''}"[:500]
        if doc.expected_monthly_kg:
            cust.sungas_expected_monthly_kg = doc.expected_monthly_kg
        if doc.requested_group != DEFAULT_GROUP and not cust.get("sungas_account_owner"):
            cust.sungas_account_owner = plant_manager_for(doc.requested_from, doc.requested_by) or frappe.session.user
        cust.flags.sungas_group_change_ok = True
        cust.save(ignore_permissions=True)
    _notify_requester(doc)
    return doc.status


def _notify_requester(doc):
    if not doc.requested_by or doc.requested_by == frappe.session.user:
        return
    subj = f"Your group change {doc.name} for {doc.customer_name} was {doc.status.lower()}"
    note = frappe.utils.escape_html(doc.decision_note or "")
    _alert([doc.requested_by], subj, f"<p>{subj}.</p><p>{note}</p>", doc.name, "sungas_approval_update", {
        "requester_name": frappe.db.get_value("User", doc.requested_by, "first_name") or "there",
        "doc_label": f"group change {doc.name} ({doc.customer_name})", "state": doc.status,
        "note": doc.decision_note or "-", "link": _link(doc.name)})


@frappe.whitelist()
def approve(name, note=None):
    return _decide(name, "Approved", note)


@frappe.whitelist()
def reject(name, note=None):
    return _decide(name, "Rejected", note)


# -- Scheduled ---------------------------------------------------------------

def escalate_overdue():
    """Hourly: pending > 48 h -> Head of Sales + Deputy, once per request."""
    cutoff = add_to_date(now_datetime(), hours=-ESCALATE_HOURS)
    rows = frappe.get_all(CGCR, filters={"status": "Pending", "creation": ["<", cutoff], "escalated_on": ["is", "not set"]},
                          fields=["name", "customer_name", "current_group", "requested_group", "creation"])
    heads = _users_with(HOS_ROLES)
    for r in rows:
        hours = int((now_datetime() - r.creation).total_seconds() // 3600)
        subj = f"Overdue: group change {r.name} ({r.customer_name}) waiting {hours} h for the Commercial Desk"
        for u in heads:
            _alert([u], subj, f'<p>{subj}.</p><p><a href="{_link(r.name)}">Open request</a></p>', r.name,
                   "sungas_approval_overdue", {
                       "approver_name": frappe.db.get_value("User", u, "first_name") or "there",
                       "doc_label": f"Group change {r.name} ({r.customer_name})", "hours": str(hours),
                       "waiting_on": "the Commercial Desk", "link": _link(r.name)})
        frappe.db.set_value(CGCR, r.name, "escalated_on", now_datetime(), update_modified=False)
    frappe.db.commit()
    return len(rows)


def briefing_rows(user, roles, day):
    """(pending requests for the desk, yesterday's group changes for desk + Head of Sales)."""
    pending, changes = [], []
    if DESK_ROLE in roles:
        pending = [(CGCR, r.name, f"{r.customer_name}: {r.current_group} -> {r.requested_group}")
                   for r in frappe.get_all(CGCR, filters={"status": "Pending"},
                                           fields=["name", "customer_name", "current_group", "requested_group"],
                                           order_by="creation asc")]
    if roles & ({DESK_ROLE} | set(HOS_ROLES)):
        for r in frappe.get_all(CGCR, filters={"status": "Approved", "decided_on": ["between", [f"{day} 00:00:00", f"{day} 23:59:59"]]},
                                fields=["name", "customer_name", "current_group", "requested_group", "decided_by"]):
            watch = " [WATCH]" if r.requested_group == "Distributors" or r.current_group != DEFAULT_GROUP and r.requested_group == DEFAULT_GROUP else ""
            changes.append((CGCR, r.name, f"{r.customer_name}: {r.current_group} -> {r.requested_group} by {r.decided_by}{watch}"))
    return pending, changes


def weekly_digest():
    """Monday: Commercial Desk digest (bell + email); Head of Sales gets the same summary."""
    from frappe.utils import add_days, escape_html, nowdate
    from sungas.commercial_desk_data import account_rows, leakage_rows, prospect_rows
    from sungas.utils.bell import ring

    today = nowdate()
    week = ["between", [f"{add_days(today, -7)} 00:00:00", f"{add_days(today, -1)} 23:59:59"]]
    pending = frappe.get_all(CGCR, filters={"status": "Pending"}, fields=["name", "creation"], order_by="creation asc")
    decided = frappe.get_all(CGCR, filters={"decided_on": week, "status": ["in", ["Approved", "Rejected"]]},
                             fields=["status", "current_group", "requested_group"])
    approved = sum(d.status == "Approved" for d in decided)
    watch = [d for d in decided if d.status == "Approved" and (d.requested_group == "Distributors" or
             (d.current_group != DEFAULT_GROUP and d.requested_group == DEFAULT_GROUP))]
    accts = account_rows(today)
    dormant = [a for a in accts if a["dormant"]]
    behind = [a for a in accts if a["status"] == "Behind"]
    prospects = prospect_rows(30)
    leaks = [r for r in leakage_rows(add_days(today, -7), add_days(today, -1)) if r["flag"]]

    def lst(rows, fmt):
        if not rows:
            return "<p>None.</p>"
        return "<ul>" + "".join(f"<li>{escape_html(fmt(r))}</li>" for r in rows[:10]) + "</ul>"

    oldest = f" (oldest since {str(pending[0].creation)[:16]})" if pending else ""
    body = (f"<h4>Commercial Desk - week to {add_days(today, -1)}</h4>"
            f"<p>Requests waiting: <b>{len(pending)}</b>{oldest}<br>"
            f"Decided last week: {approved} approved, {len(decided) - approved} rejected; "
            f"{len(watch)} to watch (downgrades to Retail or moves to Distributors)<br>"
            f"Commercial / Distributors accounts: {len(accts)}, dormant over 30 days: <b>{len(dormant)}</b>, "
            f"behind kg target: <b>{len(behind)}</b></p>"
            "<h4>Behind target this month</h4>" +
            lst(behind, lambda r: "{0}: {1:,.0f} of {2:,.0f} kg so far ({3})".format(
                r["customer_name"] or r["customer"], r["kg_mtd"], r["target_to_date"], r["account_owner"] or "no owner")) +
            "<h4>Dormant accounts</h4>" + lst(dormant, lambda r: r["customer_name"] or r["customer"]) +
            "<h4>Upgrade prospects (Retail, 200+ kg in 30 days)</h4>" +
            lst(prospects, lambda r: "{0}: {1:,.0f} kg".format(r["customer"], r["kg"])) +
            "<h4>Leakage watch (3+ invoices in a day on one account at one till)</h4>" +
            lst(leaks, lambda r: "{0} at {1} ({2} in one day)".format(r["customer"], r["plant"], r["max_per_day"])) +
            f'<p><a href="{frappe.utils.get_url("/app/sungas-commercial-desk")}">Open the Commercial Desk</a></p>')
    subj = (f"Commercial Desk weekly - {len(pending)} waiting, {len(behind)} behind target, "
            f"{len(dormant)} dormant, {len(leaks)} to check")
    users = sorted(set(desk_users()) | set(_users_with(HOS_ROLES)))
    for u in users:
        ring([u], subj, body)
    if users:
        frappe.sendmail(recipients=[frappe.db.get_value("User", u, "email") or u for u in users],
                        subject=f"[SCL] {subj}", message=body, now=False)
    return {"recipients": len(users), "pending": len(pending), "behind": len(behind), "dormant": len(dormant),
            "leaks": len(leaks)}


# -- Install (after_migrate) -------------------------------------------------

CUSTOMER_FIELDS = [
    {"fieldname": "sungas_commercial_section", "fieldtype": "Section Break", "label": "Commercial Desk",
     "insert_after": "customer_group", "collapsible": 1},
    {"fieldname": "sungas_account_owner", "fieldtype": "Link", "options": "User", "label": "Account Owner",
     "insert_after": "sungas_commercial_section",
     "description": "Defaults to the manager of the plant that raised the upgrade; the desk can change it."},
    {"fieldname": "sungas_expected_monthly_kg", "fieldtype": "Float", "label": "Monthly kg Target",
     "insert_after": "sungas_account_owner",
     "description": "Standing monthly target. Behind = this month's kg below the target for the days gone."},
    {"fieldname": "sungas_group_change_reason", "fieldtype": "Small Text", "label": "Reason for group change",
     "insert_after": "sungas_expected_monthly_kg",
     "description": "Required when the Commercial Desk changes the customer group."},
]


def install():
    try:
        from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

        if not frappe.db.exists("Role", DESK_ROLE):
            frappe.get_doc({"doctype": "Role", "role_name": DESK_ROLE, "desk_access": 1}).insert(ignore_permissions=True)
        create_custom_fields({"Customer": CUSTOMER_FIELDS}, update=True)
        for wf in ("LPG Price Change Approval", "LPG Bulk Price Upload Approval"):
            if frappe.db.exists("Workflow", wf):
                frappe.db.set_value("Workflow", wf, "send_email_alert", 1, update_modified=False)
        if not frappe.db.get_default("sungas_0032_desk_seeded"):
            for u in DESK_MEMBERS:
                if frappe.db.exists("User", u):
                    frappe.get_doc("User", u).add_roles(DESK_ROLE)
            frappe.db.set_default("sungas_0032_desk_seeded", "1")
        frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "sungas.commercial_desk.install")
