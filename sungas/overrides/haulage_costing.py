"""Patch 0016 -- IAS 2 Logistics Cost Capitalisation (Trip Cost Pool).

Flow (per Daily Loading Schedule = one trip):
  1. Every trip cost (hauler PI, driver Expense Claim, diesel Material Issue,
     prepaid drawdown JE) is coded to the Logistics Cost Clearing account and
     linked to the DLS -- never straight to P&L.
  2. Each receipt leg (GIT -> outlet) gets kg x route rate as an SE
     Additional Cost (Dr outlet stock / Cr Clearing). Return-to-source legs
     get nothing, so source WAC is never inflated by a round trip.
  3. Finance settles the trip: optional freight accrual, then the actual pool
     is shared over LOADED kg -- undelivered share to Unproductive Haulage
     (cause-based cost centre), delivered-share gap to Haulage Variance
     (source Operations cost centre). Clearing nets to zero per trip.
"""
from __future__ import annotations

import frappe  # type: ignore

GIT_WH = "Goods In Transit - SCL"
POLICY = "Sungas Logistics Costing Policy"
DLS = "Daily Loading Schedule"
STD_MARKER = "Haulage (standard)"
THIRD_PARTY = "Third-Party Hauler"

SETTLE_ROLES = {"LPG Head of Finance", "Accounts Manager", "System Manager"}
PREVIEW_ROLES = SETTLE_ROLES | {"LPG Head of Operations"}

CAUSE_DESTINATION = "Destination could not receive"
CAUSE_SOURCE = "Over-loading / planning error (source)"
CAUSE_HQ = "HQ dispatch / planning call"
CAUSES = (CAUSE_DESTINATION, CAUSE_SOURCE, CAUSE_HQ)

COST_LINK_DOCTYPES = ("Purchase Invoice", "Expense Claim", "Journal Entry")
LINK_FIELD = "sungas_loading_schedule"


# --------------------------------------------------------------------------- #
# Pure maths (unit-tested without Frappe)
# --------------------------------------------------------------------------- #

def compute_settlement(loaded_kg, delivered_kg, actual_cost, capitalised_cost, accrual=0.0) -> dict:
    loaded = float(loaded_kg or 0)
    if loaded <= 0:
        raise ValueError("Loaded kg must be positive to settle a trip.")
    actual_total = round(float(actual_cost or 0) + float(accrual or 0), 2)
    undelivered = max(loaded - float(delivered_kg or 0), 0.0)
    unproductive = round(actual_total * undelivered / loaded, 2)
    variance = round(actual_total - unproductive - float(capitalised_cost or 0), 2)
    return {
        "actual_total": actual_total,
        "undelivered_kg": round(undelivered, 3),
        "unproductive": unproductive,
        "variance": variance,
        "clearing_after": round(actual_total - float(capitalised_cost or 0) - unproductive - variance, 2),
    }


def build_settlement_lines(accounts: dict, calc: dict, accrual: float, unproductive_cc, source_cc) -> list:
    clearing = accounts["clearing"]
    lines = []

    def add(account, dr, cr, cc):
        lines.append({
            "account": account,
            "debit_in_account_currency": round(dr, 2),
            "credit_in_account_currency": round(cr, 2),
            "cost_center": cc,
        })

    def pl_pair(pl_account, amount, pl_cc):
        if amount > 0:
            add(pl_account, amount, 0, pl_cc)
            add(clearing, 0, amount, source_cc)
        elif amount < 0:
            add(clearing, -amount, 0, source_cc)
            add(pl_account, 0, -amount, pl_cc)

    accrual = round(float(accrual or 0), 2)
    if accrual > 0:
        add(clearing, accrual, 0, source_cc)
        add(accounts["accrued"], 0, accrual, source_cc)
    pl_pair(accounts["unproductive"], calc["unproductive"], unproductive_cc)
    pl_pair(accounts["variance"], calc["variance"], source_cc)
    return lines


# --------------------------------------------------------------------------- #
# Frappe helpers
# --------------------------------------------------------------------------- #

def get_policy():
    try:
        policy = frappe.get_cached_doc(POLICY, POLICY)
    except Exception:
        return None
    return policy if policy.get("policy_enabled") else None


def policy_accounts(policy) -> dict:
    return {
        "clearing": policy.get("logistics_clearing_account"),
        "accrued": policy.get("freight_accrued_account"),
        "unproductive": policy.get("unproductive_haulage_account"),
        "variance": policy.get("haulage_variance_account"),
    }


def ops_cost_center(warehouse):
    row = frappe.db.get_value(
        "Warehouse", warehouse,
        ["sungas_operations_cost_center", "custom_default_cost_center"], as_dict=True,
    ) or {}
    cc = row.get("sungas_operations_cost_center") or row.get("custom_default_cost_center")
    if not cc:
        frappe.throw(
            f"Warehouse {warehouse} has no Operations Cost Center. Set "
            "'Operations Cost Center' on the warehouse first."
        )
    return cc


def require_roles(allowed):
    if not (set(allowed) & set(frappe.get_roles(frappe.session.user))):
        frappe.throw("You are not permitted to perform trip cost settlement actions.")


def kg(row) -> float:
    return float(row.get("qty") or 0) * float(row.get("conversion_factor") or 1)


# --------------------------------------------------------------------------- #
# Hooks
# --------------------------------------------------------------------------- #

def apply_standard_haulage(doc, method=None):
    """Stock Entry before_validate: kg x standard rate on GIT -> outlet legs."""
    if doc.get("docstatus") != 0 or doc.get("purpose") != "Material Transfer":
        return
    existing = doc.get("additional_costs") or []
    rows = [r for r in existing if not (r.get("description") or "").startswith(STD_MARKER)]
    std_row = standard_haulage_row(doc)
    if std_row:
        rows.append(std_row)
    if std_row or len(rows) != len(existing):
        doc.set("additional_costs", rows)


def resolve_route_rate(source, dest, trip_rate, routes, fallback) -> float:
    """Trip rate (agreed / manual) > route table (exact, then reverse) > fallback."""
    if float(trip_rate or 0) > 0:
        return float(trip_rate)
    for key in ((source, dest), (dest, source)):
        if key in routes:
            return float(routes[key] or 0)
    return float(fallback or 0)


def route_table(policy) -> dict:
    return {(r.get("from_outlet"), r.get("to_outlet")): r.get("rate_per_kg")
            for r in (policy.get("route_rates") or [])}


def standard_haulage_row(doc):
    policy = get_policy()
    ls_name = doc.get("loading_schedule")
    if not policy or not ls_name:
        return None
    ls = frappe.db.get_value(
        DLS, ls_name, ["source_outlet", "haulage_rate_per_kg", "haulage_settled_on"], as_dict=True,
    ) or {}
    if ls.get("haulage_settled_on"):
        return None
    source = ls.get("source_outlet")
    routes = route_table(policy)
    per_dest = {}
    for r in doc.get("items") or []:
        dest = r.get("t_warehouse")
        if r.get("s_warehouse") != GIT_WH or not dest or dest in (GIT_WH, source):
            continue
        per_dest[dest] = per_dest.get(dest, 0.0) + kg(r)
    amount, parts = 0.0, []
    for dest, qty in per_dest.items():
        rate = resolve_route_rate(source, dest, ls.get("haulage_rate_per_kg"), routes,
                                  policy.get("default_haulage_rate_per_kg"))
        if rate > 0 and qty > 0:
            amount += rate * qty
            parts.append(f"{rate:,.2f}/kg x {qty:,.2f} kg to {dest}")
    amount = round(amount, 2)
    if amount <= 0:
        return None
    clearing = policy.get("logistics_clearing_account")
    return {
        "expense_account": clearing,
        "account_currency": frappe.get_cached_value("Account", clearing, "account_currency"),
        "exchange_rate": 1,
        "description": f"{STD_MARKER} {'; '.join(parts)} -- {ls_name}",
        "amount": amount,
        "base_amount": amount,
    }


def validate_trip_haulage(doc, method=None):
    """DLS validate: a Third-Party Hauler trip must name its hauler."""
    if doc.get("haulage_settled_on") or doc.get("state") in ("Dispatched", "Closed"):
        return
    if doc.get("haulage_mode") == THIRD_PARTY and not doc.get("hauler"):
        frappe.throw("Select the Hauler (Supplier) for a Third-Party Hauler trip.")


def on_settlement_je_cancel(doc, method=None):
    """Journal Entry on_cancel: re-open the trip for settlement."""
    ls = doc.get(LINK_FIELD)
    if not ls or frappe.db.get_value(DLS, ls, "haulage_settlement_je") != doc.name:
        return
    frappe.db.set_value(DLS, ls, {
        "haulage_settlement_je": None, "haulage_settled_by": None, "haulage_settled_on": None,
    }, update_modified=False)
    frappe.get_doc(DLS, ls).add_comment(
        "Info", f"<b>[Trip Cost Settlement]</b> {doc.name} cancelled -- trip re-opened for settlement."
    )


def ensure_trip_settled(ls_doc):
    """Gate used by force_close_trip: dispatched trips must be settled first."""
    policy = get_policy()
    if not policy or not policy.get("require_settlement_before_close"):
        return
    if ls_doc.get("haulage_settled_on"):
        return
    disp = ls_doc.get("dispatch_stock_entry")
    if not disp or frappe.db.get_value("Stock Entry", disp, "docstatus") != 1:
        return
    frappe.throw(
        f"Trip costs for {ls_doc.name} are not settled. Ask Finance to click "
        "'Settle Trip Costs' (Actions menu) before force-closing this trip."
    )


# --------------------------------------------------------------------------- #
# Trip figures
# --------------------------------------------------------------------------- #

def trip_figures(ls_doc, policy) -> dict:
    source = ls_doc.get("source_outlet")
    loaded = 0.0
    disp = ls_doc.get("dispatch_stock_entry")
    if disp and frappe.db.get_value("Stock Entry", disp, "docstatus") == 1:
        loaded = sum(
            kg(r) for r in frappe.get_all(
                "Stock Entry Detail", filters={"parent": disp, "t_warehouse": GIT_WH},
                fields=["qty", "conversion_factor"],
            )
        )

    ses = frappe.get_all(
        "Stock Entry", filters={"loading_schedule": ls_doc.name, "docstatus": 1},
        fields=["name", "purpose"],
    )
    transfer_names = {s["name"] for s in ses if s["purpose"] == "Material Transfer" and s["name"] != disp}
    delivered_by_dest, returned = {}, 0.0
    if transfer_names:
        for r in frappe.get_all(
            "Stock Entry Detail",
            filters={"parent": ["in", list(transfer_names)], "s_warehouse": GIT_WH},
            fields=["t_warehouse", "qty", "conversion_factor"],
        ):
            wh = r.get("t_warehouse")
            if not wh or wh == GIT_WH:
                continue
            if wh == source:
                returned += kg(r)
            else:
                delivered_by_dest[wh] = delivered_by_dest.get(wh, 0.0) + kg(r)
    delivered = sum(delivered_by_dest.values())

    vouchers = {("Stock Entry", s["name"]) for s in ses}
    settlement_je = ls_doc.get("haulage_settlement_je")
    for dt in COST_LINK_DOCTYPES:
        for name in frappe.get_all(dt, filters={LINK_FIELD: ls_doc.name, "docstatus": 1}, pluck="name"):
            if not (dt == "Journal Entry" and name == settlement_je):
                vouchers.add((dt, name))

    actual, capitalised = 0.0, 0.0
    if vouchers:
        for g in frappe.get_all(
            "GL Entry",
            filters={
                "account": policy.get("logistics_clearing_account"), "is_cancelled": 0,
                "voucher_no": ["in", list({v[1] for v in vouchers})],
            },
            fields=["voucher_type", "voucher_no", "debit", "credit"],
        ):
            if (g["voucher_type"], g["voucher_no"]) not in vouchers:
                continue
            net = float(g.get("debit") or 0) - float(g.get("credit") or 0)
            if g["voucher_type"] == "Stock Entry" and g["voucher_no"] in transfer_names:
                capitalised -= net
            else:
                actual += net

    planned = {}
    for d in (ls_doc.get("drops") or []):
        dest = d.get("destination_outlet")
        if dest:
            planned[dest] = planned.get(dest, 0.0) + float(d.get("qty") or 0)
    shortfall = {
        dest: round(qty - delivered_by_dest.get(dest, 0.0), 3)
        for dest, qty in planned.items() if qty - delivered_by_dest.get(dest, 0.0) > 0
    }
    return {
        "loaded_kg": round(loaded, 3),
        "delivered_kg": round(delivered, 3),
        "returned_kg": round(returned, 3),
        "retained_kg": round(max(loaded - delivered - returned, 0.0), 3),
        "actual_cost": round(actual, 2),
        "capitalised_cost": round(capitalised, 2),
        "clearing_balance": round(actual - capitalised, 2),
        "destinations": sorted(planned),
        "shortfall_by_destination": shortfall,
    }


def unproductive_cost_center(cause, ls_doc, figs, cause_outlet, policy):
    if cause == CAUSE_HQ:
        cc = policy.get("hq_operations_cost_center")
        if not cc:
            frappe.throw("Set 'HQ Operations Cost Center' on Sungas Logistics Costing Policy first.")
        return cc
    if cause == CAUSE_SOURCE:
        return ops_cost_center(ls_doc.get("source_outlet"))
    if cause == CAUSE_DESTINATION:
        shortfall = figs["shortfall_by_destination"]
        outlet = cause_outlet or (max(shortfall, key=shortfall.get) if shortfall else None)
        if not outlet or outlet not in figs["destinations"]:
            frappe.throw("Pick the destination outlet that could not receive (must be a drop on this trip).")
        return ops_cost_center(outlet)
    frappe.throw("Select the cause of the undelivered kg: " + " / ".join(CAUSES))


# --------------------------------------------------------------------------- #
# Whitelisted endpoints
# --------------------------------------------------------------------------- #

@frappe.whitelist()
def preview_trip_costs(ls: str) -> dict:
    require_roles(PREVIEW_ROLES)
    policy = get_policy()
    if not policy:
        frappe.throw("Sungas Logistics Costing Policy is not enabled.")
    doc = frappe.get_doc(DLS, ls)
    figs = trip_figures(doc, policy)
    calc = compute_settlement(figs["loaded_kg"], figs["delivered_kg"], figs["actual_cost"],
                              figs["capitalised_cost"]) if figs["loaded_kg"] > 0 else None
    figs.update({
        "settled": bool(doc.get("haulage_settled_on")),
        "haulage_mode": doc.get("haulage_mode"),
        "hauler": doc.get("hauler"),
        "undelivered_kg": calc["undelivered_kg"] if calc else 0,
        "unproductive_cost": calc["unproductive"] if calc else 0,
        "variance": calc["variance"] if calc else 0,
        "causes": list(CAUSES),
        "cause_destination": CAUSE_DESTINATION,
    })
    return figs


@frappe.whitelist()
def settle_trip_costs(ls: str, cause: str = None, cause_outlet: str = None,
                      accrual_amount: float = 0, accrual_supplier: str = None,
                      remarks: str = "") -> dict:
    require_roles(SETTLE_ROLES)
    policy = get_policy()
    if not policy:
        frappe.throw("Sungas Logistics Costing Policy is not enabled.")
    doc = frappe.get_doc(DLS, ls)
    if doc.get("haulage_settled_on"):
        return {"ok": True, "note": "already settled", "journal_entry": doc.get("haulage_settlement_je")}
    if doc.get("state") not in ("Dispatched", "Closed"):
        frappe.throw("Trip costs can only be settled once the trip is Dispatched or Closed.")

    figs = trip_figures(doc, policy)
    if figs["loaded_kg"] <= 0:
        frappe.throw("The outward (dispatch) Stock Entry for this trip is not submitted yet.")
    accrual = round(float(accrual_amount or 0), 2)
    if accrual < 0:
        frappe.throw("Accrual amount cannot be negative.")

    calc = compute_settlement(figs["loaded_kg"], figs["delivered_kg"], figs["actual_cost"],
                              figs["capitalised_cost"], accrual)
    source_cc = ops_cost_center(doc.get("source_outlet"))
    unprod_cc = None
    if calc["unproductive"]:
        unprod_cc = unproductive_cost_center(cause, doc, figs, cause_outlet, policy)
    lines = build_settlement_lines(policy_accounts(policy), calc, accrual, unprod_cc, source_cc)

    je_name = None
    if lines:
        je = frappe.new_doc("Journal Entry")
        je.voucher_type = "Journal Entry"
        je.company = doc.get("company") or frappe.db.get_single_value("Global Defaults", "default_company")
        je.posting_date = frappe.utils.today()
        je.set(LINK_FIELD, doc.name)
        je.user_remark = (
            f"Trip cost settlement {doc.name}. Loaded {figs['loaded_kg']} kg, delivered "
            f"{figs['delivered_kg']} kg, returned {figs['returned_kg']} kg, retained/lost "
            f"{figs['retained_kg']} kg. Actual NGN {calc['actual_total']:,.2f} "
            f"(accrued {accrual:,.2f}{' for ' + accrual_supplier if accrual_supplier and accrual else ''}), "
            f"capitalised {figs['capitalised_cost']:,.2f}, unproductive {calc['unproductive']:,.2f}"
            f"{' [' + cause + ']' if unprod_cc else ''}, variance {calc['variance']:,.2f}."
            + (f" {frappe.utils.strip_html(remarks)[:300]}" if remarks else "")
        )
        for line in lines:
            je.append("accounts", line)
        je.insert(ignore_permissions=True)
        je.submit()
        je_name = je.name

    frappe.db.set_value(DLS, doc.name, {
        "haulage_loaded_kg": figs["loaded_kg"],
        "haulage_delivered_kg": figs["delivered_kg"],
        "haulage_returned_kg": figs["returned_kg"],
        "haulage_retained_kg": figs["retained_kg"],
        "haulage_actual_cost": calc["actual_total"],
        "haulage_accrued_cost": accrual,
        "haulage_capitalised_cost": figs["capitalised_cost"],
        "haulage_unproductive_cost": calc["unproductive"],
        "haulage_variance": calc["variance"],
        "unproductive_cause": cause if unprod_cc else None,
        "unproductive_cost_center": unprod_cc,
        "haulage_settlement_je": je_name,
        "haulage_settled_by": frappe.session.user,
        "haulage_settled_on": frappe.utils.now_datetime(),
    }, update_modified=False)
    doc.add_comment(
        "Info",
        f"<b>[Trip Cost Settlement]</b> by {frappe.session.user} -- actual NGN "
        f"{calc['actual_total']:,.2f}, unproductive {calc['unproductive']:,.2f}, "
        f"variance {calc['variance']:,.2f}" + (f", JE {je_name}" if je_name else ", no JE needed"),
    )
    return {"ok": True, "journal_entry": je_name, **calc}
