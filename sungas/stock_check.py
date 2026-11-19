"""Patch 0057 (Workflow v2, Phase 4): plant readings (7 am / close of day) and the daily stock check per plant.

Check 1  dispensers:  sum(close - open totalizer)              vs  kg sold through dispensers (receipts, deliveries)
Check 2  tank:        open tank + received - dispensed - loaded from tank (bulk / transfers)  vs  closing tank
Check 3  overnight:   today's open tank  vs  yesterday's close tank + received - loaded from tank in between
Gap above max(tolerance kg, tolerance % of dispensed) -> Stock Check becomes a case: Plant Manager -> Head of Operations.
"""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, flt, get_url_to_form, getdate, now_datetime, nowdate

SC, PR, PS = "Sungas Stock Check", "Sungas Plant Reading", "Sungas Plant Setup"
W_PM, W_HOO, CLOSED = "Waiting for Plant Manager", "Waiting for Head of Operations", "Closed"
TANK_VOUCHERS = ("Stock Entry",)  # trucks (inter-outlet transfers) load from the tank, not a dispenser
VOLUME = {"Oworo - SCL": 22000, "Ebutte - SCL": 10000, "Mafoluku - SCL": 22000}
MULTI_TANK = {"Ekehuan - SCL": 2, "Idowina - SCL": 2}


# ---------------------------------------------------------------- readings
def reading_validate(doc, method=None):
    plant = frappe.get_doc(PS, doc.plant)
    if not doc.dispensers:
        doc.set("dispensers", [{"dispenser_no": i + 1} for i in range(plant.dispenser_count or 1)])
    if not doc.tanks:
        doc.set("tanks", [{"tank_name": t.tank_name, "instrument": t.instrument} for t in plant.tanks])
    cap = {t.tank_name: flt(t.capacity_litres) for t in plant.tanks}
    for t in doc.tanks:
        if t.instrument == "Volume gauge":
            if not (0 <= flt(t.gauge_percent) <= 100):
                frappe.throw(_("Tank {0}: the gauge reads 0 to 100 %.").format(t.tank_name))
            t.kg = flt(t.gauge_percent) / 100 * cap.get(t.tank_name, 0) * flt(t.density_kg_per_l)
        else:
            t.kg = flt(t.load_cell_kg)
    doc.total_tank_kg = sum(flt(t.kg) for t in doc.tanks)


def reading_before_submit(doc, method=None):
    roles = set(frappe.get_roles())
    if not roles & {"LPG Plant Manager", "LPG Head of Operations", "System Manager"}:
        frappe.throw(_("The Plant Manager confirms (submits) the readings."))
    for t in doc.tanks:
        if t.instrument == "Volume gauge" and not (flt(t.gauge_percent) and flt(t.density_kg_per_l)):
            frappe.throw(_("Tank {0}: enter the gauge % and the density.").format(t.tank_name))
    doc.confirmed_by = frappe.session.user


def reading_on_submit(doc, method=None):
    if doc.reading_type == "Day close":
        run_check(doc.plant, doc.reading_date)
        low_tank_check(doc)
    else:
        prev = frappe.db.exists(SC, {"plant": doc.plant, "check_date": add_days(doc.reading_date, -1)})
        if prev:
            run_check(doc.plant, add_days(doc.reading_date, -1))


# ---------------------------------------------------------------- the check
def _reading(plant, day, kind):
    name = frappe.db.get_value(PR, {"plant": plant, "reading_date": day, "reading_type": kind, "docstatus": 1}, "name")
    return frappe.get_doc(PR, name) if name else None


def _moves(warehouse, start, end):
    """kg in / out of the plant between two moments, split by where it leaves from."""
    rows = frappe.db.sql("""
        select sle.voucher_type, sle.voucher_no, sle.actual_qty
        from `tabStock Ledger Entry` sle join `tabItem` i on i.name = sle.item_code
        where sle.warehouse = %s and sle.is_cancelled = 0 and i.stock_uom = 'Kg'
          and timestamp(sle.posting_date, sle.posting_time) > %s and timestamp(sle.posting_date, sle.posting_time) <= %s
    """, (warehouse, start, end), as_dict=True)
    # Till sales reach stock only when the shift closes (often after the day-close reading); count them by
    # receipt time instead and drop the consolidated invoices.
    si = list({r.voucher_no for r in rows if r.voucher_type == "Sales Invoice"})
    merged = set(frappe.get_all("Sales Invoice", filters={"name": ["in", si], "is_consolidated": 1}, pluck="name")) if si else set()
    rows = [r for r in rows if r.voucher_no not in merged]
    till = frappe.db.sql("""
        select coalesce(sum(pii.stock_qty), 0) from `tabPOS Invoice Item` pii
        join `tabPOS Invoice` pi on pi.name = pii.parent join `tabItem` i on i.name = pii.item_code
        where pi.docstatus = 1 and pii.warehouse = %s and i.stock_uom = 'Kg'
          and timestamp(pi.posting_date, pi.posting_time) > %s and timestamp(pi.posting_date, pi.posting_time) <= %s
    """, (warehouse, start, end))[0][0]
    bulk = set()
    for dt in ("Delivery Note", "Sales Invoice"):
        names = list({r.voucher_no for r in rows if r.voucher_type == dt})
        if names:
            bulk |= set(frappe.get_all(dt, filters={"name": ["in", names], "sungas_bulk_from_tank": 1}, pluck="name"))
    received = sum(flt(r.actual_qty) for r in rows if flt(r.actual_qty) > 0)
    tank_out = sum(-flt(r.actual_qty) for r in rows if flt(r.actual_qty) < 0
                   and (r.voucher_type in TANK_VOUCHERS or r.voucher_no in bulk))
    sold = sum(-flt(r.actual_qty) for r in rows if flt(r.actual_qty) < 0) - tank_out + flt(till)
    return received, tank_out, sold


def _tolerance(dispensed):
    p = frappe.get_single("Sungas Close Policy")
    return max(flt(p.get("stock_tolerance_kg")) or 2, (flt(p.get("stock_tolerance_pct")) or 0.1) / 100 * abs(dispensed))


def run_check(plant, day):
    day = getdate(day)
    op, cl = _reading(plant, day, "Day open"), _reading(plant, day, "Day close")
    if not (op and cl):
        return None
    wh = frappe.db.get_value(PS, plant, "warehouse")
    tot = {d.dispenser_no: flt(d.totalizer_kg) for d in op.dispensers}
    dispensed = sum(flt(d.totalizer_kg) - tot.get(d.dispenser_no, 0) for d in cl.dispensers)
    received, tank_out, sold = _moves(wh, op.reading_time, cl.reading_time)
    book = flt(op.total_tank_kg) + received - dispensed - tank_out
    overnight = 0.0
    nxt = _reading(plant, add_days(day, 1), "Day open")
    if nxt:
        r2, t2, _s2 = _moves(wh, cl.reading_time, nxt.reading_time)
        overnight = flt(nxt.total_tank_kg) - (flt(cl.total_tank_kg) + r2 - t2)
    tol = _tolerance(dispensed)
    gaps = dict(dispenser_gap_kg=sold - dispensed, tank_gap_kg=flt(cl.total_tank_kg) - book, overnight_gap_kg=overnight)
    name = frappe.db.get_value(SC, {"plant": plant, "check_date": day}, "name")
    doc = frappe.get_doc(SC, name) if name else frappe.new_doc(SC)
    doc.update(dict(plant=plant, check_date=day, open_reading=op.name, close_reading=cl.name, dispensed_kg=dispensed,
                    sold_kg=sold, open_tank_kg=op.total_tank_kg, received_kg=received, tank_out_kg=tank_out,
                    book_close_kg=book, close_tank_kg=cl.total_tank_kg, tolerance_kg=tol, **gaps))
    bad = any(abs(flt(v)) > tol for v in gaps.values())
    doc.result = "Variance" if bad else "OK"
    opened = bad and not doc.case_status
    if opened:
        doc.case_status, doc.waiting_since = W_PM, now_datetime()
    doc.flags.ignore_permissions = True
    doc.save()
    if opened:
        _tell(doc)
    return doc.name


# ---------------------------------------------------------------- low tank (Patch 0062)
def reorder_level(plant) -> tuple[float, float]:
    """(level in force, average daily usage). Usage = dispensed + loaded from the tank, last 14 checks."""
    ps = frappe.get_doc(PS, plant)
    days = frappe.get_all(SC, filters={"plant": plant}, fields=["dispensed_kg", "tank_out_kg"],
                          order_by="check_date desc", limit=14)
    avg = sum(flt(r.dispensed_kg) + flt(r.tank_out_kg) for r in days) / len(days) if days else 0.0
    auto = flt(ps.get("days_of_cover") or 3) * avg
    frappe.db.set_value(PS, plant, {"avg_daily_kg": avg, "auto_reorder_kg": auto}, update_modified=False)
    return (flt(ps.get("reorder_level_kg")) or auto), avg


def low_tank_check(reading):
    level, avg = reorder_level(reading.plant)
    tank = flt(reading.total_tank_kg)
    if not level or tank >= level or frappe.db.get_value(PS, reading.plant, "last_low_alert") == getdate(reading.reading_date):
        return
    frappe.db.set_value(PS, reading.plant, "last_low_alert", reading.reading_date, update_modified=False)
    from sungas.utils import whatsapp

    left = f", about {tank / avg:.1f} days of sales left" if avg else ""
    line = (f"Low tank at {reading.plant.replace(' - SCL', '')}: {tank:,.0f} kg at close, below the reorder level "
            f"of {level:,.0f} kg{left}. Please arrange a supply truck.")
    link = get_url_to_form(PR, reading.name)
    prof = frappe._dict(pos_profile=frappe.db.get_value("POS Profile", {"warehouse": frappe.db.get_value(PS, reading.plant, "warehouse")}, "name"))
    from sungas.overrides.closing_approval_alerts import approvers

    users = {u for st in ("Pending Plant Manager", "Pending HOD Operations") for u in approvers(prof, st)}
    users -= {"Administrator", "lmd-bot@sungas.org"}
    for u in sorted(users):
        frappe.get_doc({"doctype": "Notification Log", "for_user": u, "type": "Alert", "subject": line,
                        "document_type": PR, "document_name": reading.name}).insert(ignore_permissions=True)
        whatsapp.send([u], "sungas_approval_needed", {"approver_name": whatsapp.first_name(u), "doc_label": "Low tank",
                       "summary": line[:150], "state": "Reorder", "link": link}, ref=f"LOWTANK:{reading.name}:{u}")


# ---------------------------------------------------------------- the case
def _people(doc, status):
    from sungas.overrides.closing_approval_alerts import approvers

    prof = frappe.db.get_value("POS Profile", {"warehouse": frappe.db.get_value(PS, doc.plant, "warehouse")}, "name")
    state = {W_PM: "Pending Plant Manager", W_HOO: "Pending HOD Operations"}[status]
    return approvers(frappe._dict(pos_profile=prof), state)


def _tell(doc, line=None):
    from sungas.utils import brevo, whatsapp

    if doc.case_status not in (W_PM, W_HOO):
        return
    users = [u for u in _people(doc, doc.case_status) if u not in ("Administrator", "lmd-bot@sungas.org")]
    line = line or (f"Stock check {doc.name}: dispensers {flt(doc.dispenser_gap_kg):+,.1f} kg, tank "
                    f"{flt(doc.tank_gap_kg):+,.1f} kg, overnight {flt(doc.overnight_gap_kg):+,.1f} kg "
                    f"(tolerance {flt(doc.tolerance_kg):,.1f} kg). {doc.case_status}.")
    link = get_url_to_form(SC, doc.name)
    to = [{"email": u, "name": frappe.db.get_value("User", u, "full_name") or u} for u in users]
    if to:
        brevo.send_transactional_email(to, f"{doc.name}: {doc.case_status}", f"<p>{line}</p><p><a href=\"{link}\">Open</a></p>",
                                       tags=["stock-check"], ref_doctype=SC, ref_name=doc.name)
    for u in users:
        whatsapp.send([u], "sungas_approval_needed", {"approver_name": whatsapp.first_name(u),
                       "doc_label": f"Stock check {doc.name}", "summary": line[:150], "state": doc.case_status,
                       "link": link}, ref=f"SC:{doc.name}:{doc.case_status}:{u}")


def _move(doc, status, **fields):
    doc.update(dict(case_status=status, waiting_since=None if status == CLOSED else now_datetime(), **fields))
    doc.flags.ignore_permissions = True
    doc.save()
    _tell(doc)


@frappe.whitelist(methods=["POST"])
def send_for_approval(name: str) -> dict:
    doc = frappe.get_doc(SC, name)
    roles = set(frappe.get_roles())
    if doc.case_status != W_PM or not roles & {"LPG Plant Manager", "System Manager"}:
        frappe.throw(_("Only the Plant Manager sends this check for approval, while it waits for him."))
    if not doc.cause or not (doc.finding or "").strip():
        frappe.throw(_("Fill the Cause and what happened / action taken, and Save, first."))
    _move(doc, W_HOO, pm_signed_by=frappe.session.user)
    return {"status": doc.case_status}


@frappe.whitelist(methods=["POST"])
def decide(name: str, approve: int = 1, notes: str = "") -> dict:
    doc = frappe.get_doc(SC, name)
    user = frappe.session.user
    if doc.case_status != W_HOO or not set(frappe.get_roles()) & {"LPG Head of Operations", "System Manager"}:
        frappe.throw(_("Only the Head of Operations decides this check, while it waits for him."))
    if user == doc.pm_signed_by:
        frappe.throw(_("You sent this check, so another person must decide it."))
    if int(approve):
        _move(doc, CLOSED, hoo_signed_by=user, hoo_notes=notes or doc.hoo_notes)
    else:
        if not (notes or "").strip():
            frappe.throw(_("Say what the Plant Manager must correct."))
        _move(doc, W_PM, send_back_reason=notes.strip(), pm_signed_by=None)
    return {"status": doc.case_status}


# ---------------------------------------------------------------- jobs
def hourly():
    """Missing readings: no day-open by 09:00 or no day-close by 22:00 (WAT) -> Plant Manager; overdue cases nudged."""
    from sungas.utils.bell import ring

    now = now_datetime()  # site time (WAT)
    today = getdate(now)
    for kind, hour in (("Day open", 9), ("Day close", 22)):
        if now.hour < hour:
            continue
        for p in frappe.get_all(PS, pluck="name"):
            if frappe.db.exists(PR, {"plant": p, "reading_date": today, "reading_type": kind}):
                continue
            subject = f"{p}: no {kind.lower()} reading for {today}"
            if frappe.db.exists("Notification Log", {"subject": subject}):
                continue
            prof = frappe.db.get_value("POS Profile", {"warehouse": frappe.db.get_value(PS, p, "warehouse")}, "name")
            from sungas.overrides.closing_approval_alerts import approvers

            ring(approvers(frappe._dict(pos_profile=prof), "Pending Plant Manager"), subject,
                 f"<p>The {kind.lower()} plant reading (dispenser totalizers and tanks) for {today} has not been entered.</p>",
                 PS, p)
    frappe.db.commit()


def daily():
    """Re-run yesterday's checks (late close readings, back-dated stock entries)."""
    y = add_days(nowdate(), -1)
    for p in frappe.get_all(PR, filters={"reading_date": y, "reading_type": "Day close", "docstatus": 1}, pluck="plant"):
        run_check(p, y)
    frappe.db.commit()


# ---------------------------------------------------------------- install
def install():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    try:
        create_custom_fields({
            "Sungas Close Policy": [
                {"fieldname": "stock_tol_section", "fieldtype": "Section Break", "label": "Daily Stock Check Tolerance",
                 "insert_after": "sla_hof_hours"},
                {"fieldname": "stock_tolerance_kg", "fieldtype": "Float", "label": "Tolerance (kg per plant per day)",
                 "default": "2", "insert_after": "stock_tol_section"},
                {"fieldname": "stock_tolerance_pct", "fieldtype": "Float", "label": "or % of kg dispensed (whichever is larger)",
                 "default": "0.1", "insert_after": "stock_tolerance_kg"},
            ],
            # Patch 0059 -- ticked once on the order; copies to the Delivery Note / Sales Invoice made from it.
            "Sales Order": [{"fieldname": "sungas_bulk_from_tank", "fieldtype": "Check", "label": "Loaded straight from the tank (bulk)",
                             "insert_after": "set_warehouse",
                             "description": "Copies to the Delivery Note / Sales Invoice made from this order."}],
            "Delivery Note": [{"fieldname": "sungas_bulk_from_tank", "fieldtype": "Check", "label": "Loaded straight from the tank (bulk)",
                               "insert_after": "set_warehouse"}],
            "Sales Invoice": [{"fieldname": "sungas_bulk_from_tank", "fieldtype": "Check", "label": "Loaded straight from the tank (bulk)",
                               "insert_after": "set_warehouse"}],
        }, update=True)
        for f, v in (("stock_tolerance_kg", 2), ("stock_tolerance_pct", 0.1)):
            if not frappe.db.get_single_value("Sungas Close Policy", f):
                frappe.db.set_single_value("Sungas Close Policy", f, v)
        _seed_plants()
        frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "sungas.stock_check.install")


def _seed_plants():
    """One setup per POS plant (only if missing): tanks / instrument / capacity as agreed; default cover filler."""
    for wh in frappe.get_all("POS Profile", filters={"disabled": 0}, pluck="warehouse", distinct=True):
        if not wh or frappe.db.exists(PS, wh):
            continue
        branch = wh.replace(" - SCL", "")
        if wh in VOLUME:
            tanks = [{"tank_name": "Tank 1", "instrument": "Volume gauge", "capacity_litres": VOLUME[wh],
                      "density_source": "Mass-flow meter"}]
        else:
            tanks = [{"tank_name": f"Tank {i + 1}", "instrument": "Load cell"} for i in range(MULTI_TANK.get(wh, 1))]
        cover = frappe.db.get_value("Employee", {"status": "Active", "branch": branch, "designation": "Filler"}, "name",
                                    order_by="name asc")
        frappe.get_doc({"doctype": PS, "warehouse": wh, "dispenser_count": 1, "has_inlet_massflow": int(wh == "Oworo - SCL"),
                        "cover_employee": cover, "tanks": tanks}).insert(ignore_permissions=True)
