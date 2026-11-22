"""Patch 0067 -- till receipts not yet closed into the day's sales count against stock on every channel.

A till receipt (POS Invoice) moves no stock until the till closes. Without this, a delivery,
invoice or transfer could take kg the till has already sold, and the till close then fails.
"""
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, now_datetime, time_diff_in_seconds

GIT = ("Goods In Transit - SCL", "Goods in Transit from Suppliers - SCL")
FINANCE = ("LPG Head of Finance", "Accounts Manager")
OFFLINE_GRACE_SECONDS = 600


def open_till_qty(pairs=None, warehouses=None):
    """{(item, warehouse): stock qty on submitted till sales (not returns) not yet closed into a Sales Invoice}."""
    cond, args = "", {}
    if pairs:
        cond = "and x.item_code in %(items)s and x.warehouse in %(whs)s"
        args = {"items": tuple({p[0] for p in pairs}), "whs": tuple({p[1] for p in pairs})}
    elif warehouses is not None:
        cond, args = "and x.warehouse in %(whs)s", {"whs": tuple(warehouses) or ("",)}
    rows = frappe.db.sql(f"""select x.item_code, x.warehouse, sum(x.qty) as qty from (
            select it.item_code, it.warehouse, it.stock_qty as qty from `tabPOS Invoice` p
              join `tabPOS Invoice Item` it on it.parent = p.name
             where p.docstatus = 1 and p.is_return = 0 and ifnull(p.consolidated_invoice, '') = ''
            union all
            select pk.item_code, pk.warehouse, pk.qty * ifnull(pk.conversion_factor, 1) from `tabPOS Invoice` p
              join `tabPacked Item` pk on pk.parent = p.name and pk.parenttype = 'POS Invoice'
             where p.docstatus = 1 and p.is_return = 0 and ifnull(p.consolidated_invoice, '') = '') x
        where 1 = 1 {cond} group by x.item_code, x.warehouse""", args, as_dict=True)
    return {(r.item_code, r.warehouse): flt(r.qty) for r in rows}


def _bin(item, wh):
    return flt(frappe.db.get_value("Bin", {"item_code": item, "warehouse": wh}, "actual_qty"))


def _outgoing(doc):
    need = defaultdict(float)
    if doc.doctype == "Stock Entry":
        for r in doc.items:
            if r.s_warehouse:
                need[(r.item_code, r.s_warehouse)] += flt(r.transfer_qty or r.qty)
        return need
    for r in doc.items:
        if r.warehouse:
            need[(r.item_code, r.warehouse)] += flt(r.stock_qty or r.qty)
    for r in doc.get("packed_items") or []:
        if r.warehouse:
            need[(r.item_code, r.warehouse)] += flt(r.qty) * flt(r.get("conversion_factor") or 1)
    return need


def _stock_items(items):
    return set(frappe.get_all("Item", filters={"name": ["in", list(items) or [""]], "is_stock_item": 1}, pluck="name"))


def _skip(doc):
    if frappe.db.get_single_value("Stock Settings", "allow_negative_stock"):
        return True
    if doc.get("is_return"):
        return True
    if doc.doctype == "Sales Invoice":
        return not doc.get("update_stock") or bool(doc.get("is_consolidated"))
    return False


def guard(doc, method=None):
    """before_submit on Sales Invoice / Delivery Note / Stock Entry."""
    if _skip(doc):
        return
    need = {k: v for k, v in _outgoing(doc).items() if v > 0}
    stock = _stock_items({k[0] for k in need})
    need = {k: v for k, v in need.items() if k[0] in stock}
    if not need:
        return
    till = open_till_qty(pairs=list(need))
    short = []
    for (item, wh), qty in need.items():
        held = till.get((item, wh), 0)
        if not held:
            continue
        recorded = _bin(item, wh)
        if qty > recorded - held + 1e-6:
            short.append(_("{0} at {1}: {2} needed, {3} available now ({4} recorded less {5} sold at the till and not yet closed)").format(
                item, wh, f"{qty:,.2f}", f"{recorded - held:,.2f}", f"{recorded:,.2f}", f"{held:,.2f}"))
    if short:
        frappe.throw("<br>".join(short) + "<br><br>" + _("Reduce the quantity, or wait until the till closes and the stock is received."),
                     title=_("Not enough stock"))


def till_guard(doc):
    """Patch 0068 -- POS Invoice submit: recorded stock less receipts not yet closed must cover this receipt."""
    if frappe.db.get_single_value("Stock Settings", "allow_negative_stock") or _late_offline(doc):
        return
    need = {k: v for k, v in _outgoing(doc).items() if v > 0}
    stock = _stock_items({k[0] for k in need})
    need = {k: v for k, v in need.items() if k[0] in stock}
    if not need:
        return
    for item, wh in need:
        # Two tills selling the last kg at once: the second waits for the first, then sees its receipt.
        frappe.db.sql("select name from `tabBin` where item_code = %s and warehouse = %s for update", (item, wh))
    till = open_till_qty(pairs=list(need))
    short = []
    for (item, wh), qty in need.items():
        recorded, held = _bin(item, wh), till.get((item, wh), 0)
        if qty > recorded - held + 1e-6:
            name = frappe.db.get_value("Item", item, "item_name") or item
            short.append(_("Not enough {0}: {1} available now ({2} recorded less {3} sold today and not yet closed). Reduce the quantity.").format(
                name, _qty(recorded - held), _qty(recorded), _qty(held)))
    if short:
        frappe.throw("<br>".join(short), title=_("Not enough stock"))


def _late_offline(doc):
    """A receipt made offline and sent later: the sale has happened; the till close check and stock check catch any gap."""
    if not doc.get("set_posting_time") or not doc.get("posting_date"):
        return False
    made = get_datetime(f"{doc.posting_date} {doc.get('posting_time') or '00:00:00'}")
    return time_diff_in_seconds(now_datetime(), made) > OFFLINE_GRACE_SECONDS


def _qty(v):
    return f"{flt(v):,.2f}".rstrip("0").rstrip(".")


def close_precheck(doc, method=None):
    """before_submit on POS Closing Shift: the day's sales will post; say clearly if stock cannot cover them."""
    if frappe.db.get_single_value("Stock Settings", "allow_negative_stock"):
        return
    names = [r.pos_invoice for r in doc.get("pos_transactions") or [] if r.get("pos_invoice")]
    if not names:
        return
    rows = frappe.db.sql("""select x.item_code, x.warehouse, sum(x.qty) as qty from (
            select it.item_code, it.warehouse, it.stock_qty as qty from `tabPOS Invoice Item` it where it.parent in %(n)s
            union all
            select pk.item_code, pk.warehouse, pk.qty * ifnull(pk.conversion_factor, 1) from `tabPacked Item` pk
             where pk.parenttype = 'POS Invoice' and pk.parent in %(n)s) x
        group by x.item_code, x.warehouse""", {"n": tuple(names)}, as_dict=True)
    stock = _stock_items({r.item_code for r in rows})
    short = [(r.item_code, r.warehouse, flt(r.qty), _bin(r.item_code, r.warehouse))
             for r in rows if r.item_code in stock and r.warehouse and flt(r.qty) > _bin(r.item_code, r.warehouse) + 1e-6]
    if not short:
        return
    lines = [f"{i} at {w}: {q:,.2f} sold, {b:,.2f} recorded" for i, w, q, b in short]
    frappe.enqueue("sungas.stock_available.alert_close_short", queue="short", enqueue_after_commit=False,
                   shift=doc.name, pos_profile=doc.pos_profile, lines=lines)
    frappe.throw("<br>".join(lines) + "<br><br>" + _(
        "The till cannot close: recorded stock is below what was sold. The Plant Manager and Finance have been alerted. "
        "Once the missing stock is received or corrected, close the till again."), title=_("Till close stopped: stock short"))


def alert_close_short(shift, pos_profile, lines):
    from sungas.overrides.closing_approval_alerts import _users, approvers
    from sungas.utils.bell import ring

    users = set(approvers(frappe._dict(pos_profile=pos_profile), "Pending Plant Manager")) | set(_users(FINANCE))
    plant = (pos_profile or "").replace("POS - ", "")
    ring(sorted(users), f"Till close stopped at {plant}: stock short", "<br>".join(lines), "POS Closing Shift", shift)


def _scope():
    from sungas.scheduled_jobs.briefing_figures import outlets_for

    user = frappe.session.user
    return outlets_for(user, set(frappe.get_roles(user)))


def available_rows(plant=None, item=None):
    whs = _scope()
    f = {"warehouse": ["not in", GIT], "item_code": item or ["is", "set"]}
    if plant:
        f["warehouse"] = plant
    bins = frappe.get_all("Bin", filters=f, fields=["item_code", "warehouse", "actual_qty", "stock_uom"])
    bins = [b for b in bins if (whs is None or b.warehouse in whs) and b.warehouse.endswith(" - SCL")]
    till = open_till_qty(warehouses={b.warehouse for b in bins})
    out = []
    for b in bins:
        held = till.get((b.item_code, b.warehouse), 0)
        if not flt(b.actual_qty) and not held:
            continue
        out.append(frappe._dict(warehouse=b.warehouse, item_code=b.item_code, uom=b.stock_uom, recorded=flt(b.actual_qty),
                                open_till=held, available=flt(b.actual_qty) - held))
    return sorted(out, key=lambda r: (r.warehouse, r.item_code))


@frappe.whitelist()
def available_now_card(filters=None):
    """Number Card: LPG-REFILL kg available now across the plants the user can see."""
    return {"value": sum(r.available for r in available_rows(item="LPG-REFILL")), "fieldtype": "Float"}
