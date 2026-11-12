"""Patch 0035 -- Weekly Engagement Plan (calendar week Mon-Sun), the first piece of the Engagement App.

Draft (auto, pre-filled with the owner's behind / dormant accounts) -> owner submits -> Commercial Desk /
Head of Sales / Deputy approve or send back -> owner executes -> owner reports outcomes (actual kg comes
from sales) -> desk closes. All deadlines live in Sungas Engagement Settings; an hourly tick applies them.
"""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, escape_html, flt, getdate, now_datetime, nowdate

from sungas.commercial_desk import HOS_ROLES, SERVICE_ACCOUNTS, can_set_group, desk_users, _users_with

PLAN = "Weekly Engagement Plan"
SETTINGS = "Sungas Engagement Settings"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
EXECUTING = ("Approved", "Executing Unapproved")
DEFAULTS = {"enabled": 1, "include_dormant": 1, "draft_day": "Thursday", "draft_hour": 18,
            "default_action_day": "Friday", "submit_reminder_day": "Friday", "submit_reminder_hour": 12,
            "submit_deadline_day": "Friday", "submit_deadline_hour": 17, "approve_deadline_day": "Monday",
            "approve_deadline_hour": 10, "outcome_reminder_day": "Tuesday", "outcome_reminder_hour": 12,
            "outcome_deadline_day": "Tuesday", "outcome_deadline_hour": 18}


def settings() -> dict:
    s = dict(DEFAULTS)
    try:
        doc = frappe.get_cached_doc(SETTINGS)
        s.update({k: doc.get(k) for k in DEFAULTS if doc.get(k) not in (None, "")})
    except Exception:
        pass
    return s


def week_start_for(day):
    """Monday of the plan week an event on `day` belongs to: today if Monday, else the coming Monday."""
    day = getdate(day)
    return day if day.weekday() == 0 else add_days(day, 7 - day.weekday())


def monday_of(day):
    day = getdate(day)
    return add_days(day, -day.weekday())


def due_in_week(week_start, day_name) -> str:
    return str(add_days(getdate(week_start), DAYS.index(day_name)))


def events_due(now, s) -> list[str]:
    """Which configured events fire in this hourly tick."""
    day, hour = DAYS[now.weekday()], now.hour
    return [ev for ev in ("draft", "submit_reminder", "submit_deadline", "approve_deadline",
                          "outcome_reminder", "outcome_deadline")
            if s.get(f"{ev}_day") == day and int(s.get(f"{ev}_hour") or 0) == hour]


def _can_decide() -> bool:
    return can_set_group(frappe.get_roles())


def _link(name):
    return frappe.utils.get_url(f"/app/weekly-engagement-plan/{name}")


def _tell(users, subject, note, name=None, state="", link=None):
    from sungas.utils import whatsapp
    from sungas.utils.bell import ring

    users = [u for u in users if u and u not in SERVICE_ACCOUNTS]
    if not users:
        return
    link = link or (_link(name) if name else frappe.utils.get_url("/app/weekly-engagement-plan"))
    body = f"<p>{escape_html(subject)}</p><p>{escape_html(note)}</p><p><a href=\"{link}\">Open</a></p>"
    ring(users, subject, body, PLAN if name else None, name)
    try:
        frappe.sendmail(recipients=[frappe.db.get_value("User", u, "email") or u for u in users],
                        subject=f"[SCL] {subject}", message=body, now=False)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "sungas.engagement email")
    for u in users:
        whatsapp.send([u], "sungas_approval_update", {
            "requester_name": whatsapp.first_name(u), "doc_label": f"engagement plan {name or ''}".strip(),
            "state": state or subject, "note": note, "link": link}, ref=f"WEP:{name}:{state}:{nowdate()}")


# -- Draft creation ----------------------------------------------------------

def plan_lines(rows, week_start, s) -> list[dict]:
    lines = []
    for r in rows:
        if r["status"] == "Behind":
            why = "Behind target"
        elif r["dormant"] and s.get("include_dormant"):
            why = "Dormant"
        else:
            continue
        lines.append({"customer": r["customer"], "reason": why, "kg_mtd_at_plan": r["kg_mtd"],
                      "target_to_date_at_plan": r["target_to_date"],
                      "action_due": due_in_week(week_start, s["default_action_day"])})
    return lines


def create_drafts(day=None) -> int:
    from sungas.commercial_desk_data import account_rows

    s = settings()
    day = getdate(day or nowdate())
    ws = week_start_for(day)
    by_owner: dict = {}
    for r in account_rows(day):
        if r["account_owner"] and r["account_owner"] not in SERVICE_ACCOUNTS:
            by_owner.setdefault(r["account_owner"], []).append(r)
    made = 0
    for owner, rows in by_owner.items():
        lines = plan_lines(rows, ws, s)
        if not lines or frappe.db.exists(PLAN, {"owner_user": owner, "week_start": ws}) \
                or not frappe.db.get_value("User", owner, "enabled"):
            continue
        doc = frappe.get_doc({"doctype": PLAN, "owner_user": owner, "week_start": ws, "lines": lines})
        doc.insert(ignore_permissions=True)
        _tell([owner], f"Your engagement plan for the week of {ws} is ready",
              f"{len(lines)} accounts to plan. Submit by {s['submit_deadline_day']} {s['submit_deadline_hour']}:00.",
              doc.name, "Draft - please complete and submit")
        made += 1
    return made


# -- Owner / approver actions ------------------------------------------------

def _get(name, owner_only=False):
    doc = frappe.get_doc(PLAN, name)
    if owner_only and frappe.session.user != doc.owner_user and not _can_decide():
        frappe.throw(_("Only {0} (the account owner) can do this.").format(doc.owner_user), frappe.PermissionError)
    return doc


def _deadline_passed(week_start, day_key, hour_key, s, before_week=True):
    """Deadline datetime for the plan week: submit deadlines fall before week_start, others inside / after."""
    import datetime as dt

    ws = getdate(week_start)
    offset = DAYS.index(s[day_key])
    day = add_days(ws, offset - 7) if before_week and offset > 0 else add_days(ws, offset + (7 if not before_week else 0))
    return now_datetime() > dt.datetime.combine(getdate(day), dt.time(int(s[hour_key])))


@frappe.whitelist()
def submit_plan(name):
    doc = _get(name, owner_only=True)
    if doc.status not in ("Draft", "Sent Back"):
        frappe.throw(_("This plan is already {0}.").format(doc.status))
    missing = [str(i) for i, l in enumerate(doc.lines, 1) if not (l.action and l.root_cause and l.action_due)]
    if not doc.lines or missing:
        frappe.throw(_("Fill in root cause, action and due date on every line (rows {0}).").format(", ".join(missing) or "-"))
    s = settings()
    doc.status, doc.submitted_on = "Pending Approval", now_datetime()
    doc.late_submit = 1 if _deadline_passed(doc.week_start, "submit_deadline_day", "submit_deadline_hour", s) else 0
    doc.flags.sungas_internal = True
    doc.save(ignore_permissions=True)
    _tell(desk_users() + _users_with(HOS_ROLES), f"Engagement plan {doc.name} from {doc.owner_name} needs approval",
          f"Week of {doc.week_start}: {len(doc.lines)} accounts, {doc.planned_kg:,.0f} kg expected.", doc.name,
          "Pending Approval")
    return doc.status


def _decide(name, status, note):
    if not _can_decide():
        frappe.throw(_("Only the Commercial Desk, Head of Sales or Deputy can approve plans."), frappe.PermissionError)
    doc = _get(name)
    if doc.status not in ("Pending Approval", "Executing Unapproved"):
        frappe.throw(_("This plan is {0}; nothing to approve.").format(doc.status))
    if status == "Sent Back" and not (note or "").strip():
        frappe.throw(_("Say what needs to change before sending the plan back."))
    doc.status, doc.approval_note = status, note
    doc.approved_by, doc.approved_on = frappe.session.user, now_datetime()
    doc.flags.sungas_internal = True
    doc.save(ignore_permissions=True)
    _tell([doc.owner_user], f"Your engagement plan {doc.name} was {status.lower()}", note or "-", doc.name, status)
    return doc.status


@frappe.whitelist()
def approve_plan(name, note=None):
    return _decide(name, "Approved", note)


@frappe.whitelist()
def send_back_plan(name, note=None):
    return _decide(name, "Sent Back", note)


@frappe.whitelist()
def report_outcome(name):
    doc = _get(name, owner_only=True)
    if doc.status not in EXECUTING:
        frappe.throw(_("Outcomes can be reported once the plan is approved or executing (now {0}).").format(doc.status))
    if getdate(nowdate()) < getdate(doc.week_start):
        frappe.throw(_("The plan week has not started yet."))
    missing = [str(i) for i, l in enumerate(doc.lines, 1) if not l.outcome]
    if missing:
        frappe.throw(_("Mark the outcome on every line (rows {0}).").format(", ".join(missing)))
    s = settings()
    doc.status, doc.outcome_reported_on = "Outcome Reported", now_datetime()
    doc.late_outcome = 1 if _deadline_passed(doc.week_start, "outcome_deadline_day", "outcome_deadline_hour", s,
                                             before_week=False) else 0
    doc.flags.sungas_internal = True
    doc.save(ignore_permissions=True)
    _tell(desk_users(), f"Outcome reported on {doc.name} ({doc.owner_name})",
          f"{doc.lines_done} of {doc.lines_total} done, {doc.actual_kg:,.0f} of {doc.planned_kg:,.0f} kg.", doc.name,
          "Outcome Reported")
    return doc.status


@frappe.whitelist()
def close_plan(name, note=None):
    if not _can_decide():
        frappe.throw(_("Only the Commercial Desk, Head of Sales or Deputy can close plans."), frappe.PermissionError)
    doc = _get(name)
    if doc.status != "Outcome Reported":
        frappe.throw(_("Only plans with outcomes reported can be closed."))
    doc.status, doc.close_note = "Closed", note
    doc.closed_by, doc.closed_on = frappe.session.user, now_datetime()
    doc.flags.sungas_internal = True
    doc.save(ignore_permissions=True)
    return doc.status


# -- Actual kg from sales ----------------------------------------------------

def fill_actuals(doc):
    from sungas.commercial_desk_data import invoices, kg_by_customer

    if getdate(nowdate()) < getdate(doc.week_start) or not doc.lines:
        return
    end = min(getdate(doc.week_end), getdate(nowdate()))
    kg = kg_by_customer(invoices(doc.week_start, end, [l.customer for l in doc.lines]))
    for line in doc.lines:
        line.actual_kg = round(kg.get(line.customer, 0.0), 1)


def totals(doc):
    doc.planned_kg = sum(flt(l.expected_kg) for l in doc.lines)
    doc.actual_kg = sum(flt(l.actual_kg) for l in doc.lines)
    doc.lines_total = len(doc.lines)
    doc.lines_done = sum(1 for l in doc.lines if l.outcome == "Done")


# -- Hourly tick -------------------------------------------------------------

def tick(now=None):
    s = settings()
    if not s.get("enabled"):
        return []
    now = now or now_datetime()
    fired = events_due(now, s)
    today = getdate(now)
    for ev in fired:
        try:
            globals()[f"_on_{ev}"](today, s)
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"sungas.engagement.{ev}")
    frappe.db.commit()
    return fired


def _on_draft(today, s):
    create_drafts(today)


def _plans(filters):
    return frappe.get_all(PLAN, filters=filters, fields=["name", "owner_user", "owner_name", "status", "week_start"])


def _on_submit_reminder(today, s):
    for p in _plans({"week_start": week_start_for(today), "status": ["in", ["Draft", "Sent Back"]]}):
        _tell([p.owner_user], f"Reminder: submit engagement plan {p.name} by {s['submit_deadline_day']} "
              f"{s['submit_deadline_hour']}:00", "It is still not submitted.", p.name, "Submit reminder")


def _on_submit_deadline(today, s):
    late = _plans({"week_start": week_start_for(today), "status": ["in", ["Draft", "Sent Back"]]})
    for p in late:
        frappe.db.set_value(PLAN, p.name, "late_submit", 1, update_modified=False)
    if late:
        _tell(desk_users(), f"{len(late)} engagement plans missed the submit deadline",
              "; ".join(f"{p.owner_name or p.owner_user} ({p.name})" for p in late))


def _on_approve_deadline(today, s):
    waiting = _plans({"week_start": monday_of(today), "status": "Pending Approval"})
    for p in waiting:
        frappe.db.set_value(PLAN, p.name, "status", "Executing Unapproved", update_modified=False)
    if waiting:
        _tell(desk_users() + _users_with(HOS_ROLES), f"{len(waiting)} engagement plans started without approval",
              "; ".join(f"{p.owner_name or p.owner_user} ({p.name})" for p in waiting))


def _overdue_outcomes(today):
    return _plans({"week_start": ["<", monday_of(today)], "status": ["in", list(EXECUTING)]})


def _on_outcome_reminder(today, s):
    for p in _overdue_outcomes(today):
        doc = frappe.get_doc(PLAN, p.name)
        doc.flags.sungas_internal = True
        doc.save(ignore_permissions=True)
        _tell([p.owner_user], f"Reminder: report outcomes on {p.name} by {s['outcome_deadline_day']} "
              f"{s['outcome_deadline_hour']}:00", f"Actual kg is filled in: {doc.actual_kg:,.0f} kg.", p.name,
              "Outcome reminder")


def _on_outcome_deadline(today, s):
    late = _overdue_outcomes(today)
    for p in late:
        frappe.db.set_value(PLAN, p.name, "late_outcome", 1, update_modified=False)
    if late:
        _tell(desk_users(), f"{len(late)} engagement plans are late reporting outcomes",
              "; ".join(f"{p.owner_name or p.owner_user} ({p.name})" for p in late))


# -- Permissions (plant managers see their own plans) ------------------------

def _sees_all(user) -> bool:
    return can_set_group(frappe.get_roles(user)) or user == "Administrator"


def plan_query(user=None):
    user = user or frappe.session.user
    if _sees_all(user):
        return ""
    return f"`tabWeekly Engagement Plan`.owner_user = {frappe.db.escape(user)}"


def plan_has_permission(doc, ptype=None, user=None):
    user = user or frappe.session.user
    return True if _sees_all(user) else doc.owner_user == user


def digest_html(today) -> str:
    """Weekly digest block: this week's plans by status + last week's outcomes."""
    this = frappe.get_all(PLAN, filters={"week_start": monday_of(today)}, fields=["status"])
    last = frappe.get_all(PLAN, filters={"week_start": add_days(monday_of(today), -7)},
                          fields=["status", "planned_kg", "actual_kg", "lines_done", "lines_total"])
    by: dict = {}
    for p in this:
        by[p.status] = by.get(p.status, 0) + 1
    done = sum(p.lines_done or 0 for p in last)
    lines = sum(p.lines_total or 0 for p in last)
    return (f"<h4>Engagement plans</h4><p>This week: {len(this)} plans ("
            + (", ".join(f"{n} {k}" for k, n in sorted(by.items())) or "none") + ")<br>"
            f"Last week: {done} of {lines} actions done, {sum(flt(p.actual_kg) for p in last):,.0f} of "
            f"{sum(flt(p.planned_kg) for p in last):,.0f} kg</p>")
