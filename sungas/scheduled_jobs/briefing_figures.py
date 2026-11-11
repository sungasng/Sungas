"""Patch 0025 -- sales and losses table for the morning briefing.

Columns: Yesterday / Month-to-date / Year-to-date (calendar = financial year),
all ending yesterday, for sales and for losses.
Sales  = submitted POS Invoices + non-consolidated Sales Invoices (returns net off).
Losses = transit-loss cases (TLVC) + branch-to-branch transfer cases (IOVC)
         opened in the period + cashier cash shortfalls at shift close.
Plant managers see their own plant(s); heads see every plant plus the company total.
Month-to-date is compared with the same days last month; losses as % of sales
are shown red at or above LOSS_ALERT_PCT. Missing-price items (missing_prices)
are listed for plant managers and counted per plant for heads.
"""
from __future__ import annotations

import frappe
from dateutil.relativedelta import relativedelta
from frappe.utils import escape_html, flt, formatdate, getdate

KINDS = ("sales", "transit", "transfers", "cash")
PERIODS = ("day", "mtd", "lm", "ytd")
LOSS_ALERT_PCT = 2.0
MAX_ITEMS = 15
OTHER = "Other / head office"
COMPANY_ROLES = {"System Manager", "Accounts Manager", "LPG Head of Operations", "LPG Head of Sales",
                 "LPG Head of Finance", "HR Manager", "POS Manager", "Sales Manager", "Auditor", "COO"}


def periods(day: str) -> dict:
    d = getdate(day)
    lm_end = d - relativedelta(months=1)
    return {"day": (d, d), "mtd": (d.replace(day=1), d), "lm": (lm_end.replace(day=1), lm_end),
            "ytd": (d.replace(month=1, day=1), d)}


def _sum(dt, key, amount, filters, buckets, mapper=None, absolute=False):
    for r in frappe.get_all(dt, filters=filters, fields=[f"{key} as k", f"sum({amount}) as amt"], group_by=key):
        wh = mapper.get(r.k) if mapper is not None else r.k
        buckets[wh] = buckets.get(wh, 0.0) + (abs(flt(r.amt)) if absolute else flt(r.amt))


def figures_for(start, end) -> dict:
    prof_wh = dict(frappe.get_all("POS Profile", fields=["name", "warehouse"], as_list=True))
    dates = ["between", [str(start), str(end)]]
    span = ["between", [f"{start} 00:00:00", f"{end} 23:59:59"]]
    f = {k: {} for k in KINDS}
    _sum("POS Invoice", "pos_profile", "grand_total", {"docstatus": 1, "posting_date": dates}, f["sales"], prof_wh)
    _sum("Sales Invoice", "pos_profile", "grand_total", {"docstatus": 1, "posting_date": dates, "is_consolidated": 0},
         f["sales"], prof_wh)
    for r in frappe.get_all("Transit Loss Variance Case", filters={"docstatus": ["<", 2], "creation": span},
                            fields=["destination_warehouse", "outlet_receipt_se", "shortfall_value"]):
        wh = r.destination_warehouse or (r.outlet_receipt_se and frappe.db.get_value(
            "Stock Entry Detail", {"parent": r.outlet_receipt_se, "t_warehouse": ["is", "set"]}, "t_warehouse"))
        f["transit"][wh] = f["transit"].get(wh, 0.0) + flt(r.shortfall_value)
    _sum("Inter-Outlet Variance Case", "destination_warehouse", "value_variance",
         {"docstatus": ["<", 2], "creation": span}, f["transfers"], absolute=True)
    _sum("POS Closing Shift", "pos_profile", "variance_amount",
         {"docstatus": ["<", 2], "posting_date": dates, "variance_amount": ["<", 0]}, f["cash"], prof_wh, absolute=True)
    return f


def figures(day: str) -> dict:
    return {p: figures_for(*rng) for p, rng in periods(day).items()}


def totals(figs: dict, warehouses=None) -> dict:
    """{period: {sales, losses, transit, transfers, cash}} for the warehouses (None = whole company)."""
    out = {}
    for p in PERIODS:
        t = {k: sum(v for wh, v in figs[p][k].items() if warehouses is None or wh in warehouses) for k in KINDS}
        t["losses"] = t["transit"] + t["transfers"] + t["cash"]
        out[p] = t
    return out


def outlets_for(user: str, roles: set):
    """None = head (all plants + company); list = the plant manager's own warehouses."""
    if "LPG Plant Manager" not in roles or roles & COMPANY_ROLES:
        return None
    return frappe.get_all("Warehouse", or_filters={"outlet_plant_manager": user, "outlet_secondary_manager": user},
                          pluck="name")


def _all_plants(figs: dict) -> list:
    whs = {wh for p in PERIODS for k in KINDS for wh in figs[p][k]}
    return sorted(whs, key=lambda w: (w is None, -figs["ytd"]["sales"].get(w, 0), str(w)))


def _label(wh) -> str:
    return OTHER if wh is None else wh.replace(" - SCL", "")


def loss_pct(losses: float, sales: float):
    """(text, is_red). Losses with no sales are always red."""
    if not sales:
        return ("no sales", True) if losses else ("-", False)
    pct = losses / sales * 100
    return f"{pct:.1f}%", pct >= LOSS_ALERT_PCT


def change(now: float, before: float) -> str:
    if not before:
        return "new" if now else "-"
    return f"{(now - before) / before * 100:+.0f}%"


TD = '<td style="text-align:right;padding:2px 8px{extra}">{v}</td>'


def _row(label: str, t: dict, bold=False) -> str:
    money = lambda v: TD.format(extra="", v=f"{v:,.0f}")
    cells = [money(t[p]["sales"]) for p in ("day", "mtd", "lm")]
    cells.append(TD.format(extra="", v=change(t["mtd"]["sales"], t["lm"]["sales"])))
    cells.append(money(t["ytd"]["sales"]))
    cells += [money(t[p]["losses"]) for p in PERIODS]
    for p in ("mtd", "ytd"):
        txt, red = loss_pct(t[p]["losses"], t[p]["sales"])
        cells.append(TD.format(extra=";color:#c62828;font-weight:bold" if red else "", v=txt))
    name = f"<b>{escape_html(label)}</b>" if bold else escape_html(label)
    return f'<tr><td style="padding:2px 8px">{name}</td>{"".join(cells)}</tr>'


def table(day: str, rows: list[tuple[str, dict, bool]], scope_total: dict) -> str:
    head = ('<tr><th rowspan="2" style="text-align:left;padding:2px 8px">Plant</th>'
            '<th colspan="5">Sales (NGN)</th><th colspan="4">Losses (NGN)</th><th colspan="2">Losses % of sales</th></tr><tr>'
            "<th>Yesterday</th><th>Month-to-date</th><th>Same days last month</th><th>Change</th><th>Year-to-date</th>"
            "<th>Yesterday</th><th>Month-to-date</th><th>Same days last month</th><th>Year-to-date</th>"
            "<th>Month-to-date</th><th>Year-to-date</th></tr>")
    y = scope_total["ytd"]
    note = (f"<p style=\"font-size:12px\">Losses year-to-date: transit {y['transit']:,.0f}, "
            f"transfers {y['transfers']:,.0f}, cash shortfalls {y['cash']:,.0f}. "
            f"Red = losses at or above {LOSS_ALERT_PCT:g}% of sales.</p>")
    body = "".join(_row(*r) for r in rows)
    return (f"<h4>Sales and losses to {formatdate(day, 'dd MMM yyyy')}</h4>"
            f'<table border="1" cellspacing="0" style="border-collapse:collapse;font-size:13px">{head}{body}</table>{note}')


def missing_section(whs, missing: dict) -> str:
    """Plant manager (whs list): item list. Head (whs None): count per plant."""
    if whs is None:
        counts = sorted(((len(v), w) for w, v in missing.items() if v), key=lambda x: (-x[0], x[1]))
        if not counts:
            return ""
        lis = "".join(f"<li>{escape_html(_label(w))}: {n} item(s)</li>" for n, w in counts)
        return f"<h4>Items in stock with no price ({sum(n for n, _ in counts)})</h4><ul>{lis}</ul>"
    items = [(w, it) for w in whs for it in missing.get(w, [])]
    if not items:
        return ""
    lis = "".join(f"<li>{escape_html(code)} {escape_html(name or '')} - {qty:,.0f} in stock"
                  f"{' at ' + escape_html(_label(w)) if len(whs) > 1 else ''}</li>"
                  for w, (code, name, qty) in items[:MAX_ITEMS])
    more = f"<p>... and {len(items) - MAX_ITEMS} more.</p>" if len(items) > MAX_ITEMS else ""
    return (f"<h4>Items in stock with no price ({len(items)})</h4>"
            f"<p>These cannot be sold at the till until a price is set.</p><ul>{lis}</ul>{more}")


def for_user(user: str, roles: set, day: str, figs: dict, missing: dict | None = None, policy_log: str = ""):
    """Returns (html, has_content); (None, False) for a plant manager with no plant.
    policy_log (Patch 0028) is shown to heads only."""
    missing = missing or {}
    whs = outlets_for(user, roles)
    if whs is not None and not whs:
        return None, False
    if whs is None:
        rows = [(_label(w), totals(figs, {w}), False) for w in _all_plants(figs)]
        scope = totals(figs)
        rows.append(("Company total", scope, True))
    else:
        rows = [(_label(w), totals(figs, {w}), False) for w in whs]
        scope = totals(figs, set(whs))
        if len(whs) > 1:
            rows.append(("Total", scope, True))
    gaps = missing_section(whs, missing)
    log = policy_log if whs is None else ""
    has = bool(gaps or log) or any(scope[p][k] for p in PERIODS for k in ("sales", "losses"))
    return table(day, rows, scope) + gaps + log, has
