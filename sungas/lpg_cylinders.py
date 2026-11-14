"""Patch 0038 -- LPG sold by cylinder size; receipt + filler slip; reprints controlled.

* Each refill size is a selling unit of LPG-REFILL ("12.5kg Cyl" = 12.5 kg). Stock, tiers and
  reports stay in kg; a cylinder costs the customer's kg rate x size (tier code in posawesome).
* Kg / amount lines must say which cylinder they go into (sungas_fill_into).
* The "Sungas LPG Receipt" print prints the receipt and a filler slip. The first print is the
  ORIGINAL; any later print is stamped DUPLICATE #n and logged, and only managers may reprint.
"""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

SIZES = (0.5, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 12.5, 15, 18, 20, 23, 25, 50)
REFILL_ITEMS = ("LPG-REFILL",)
UNKNOWN = "Customer's own / unknown"
PRINT_FORMAT = "Sungas LPG Receipt"
REPRINT_ROLES = {"LPG Plant Manager", "LPG Head of Operations", "LPG Head of Finance", "Accounts Manager",
                 "System Manager", "Internal Control"}


def uom_name(size) -> str:
    return f"{size:g}kg Cyl"


def is_cyl_uom(uom) -> bool:
    return str(uom or "").endswith("kg Cyl")


def fill_choices() -> list[str]:
    return [uom_name(s) for s in SIZES] + [UNKNOWN]


def line_problems(items, is_return=False) -> list[str]:
    out = []
    for i, it in enumerate(items or [], 1):
        if it.get("item_code") not in REFILL_ITEMS:
            continue
        if is_cyl_uom(it.get("uom")):
            if flt(it.get("qty")) != int(flt(it.get("qty"))):
                out.append(_("Row {0}: {1} must be a whole number of cylinders.").format(i, it.get("uom")))
        elif not is_return and not it.get("sungas_fill_into"):
            out.append(_("Row {0}: pick which cylinder the {1} kg goes into (Fill into).").format(i, flt(it.get("qty"))))
    return out


def validate_lines(doc, method=None):
    """POS Invoice / Sales Invoice validate."""
    problems = line_problems([d.as_dict() for d in doc.items], bool(doc.get("is_return")))
    if problems:
        frappe.throw("<br>".join(problems), title=_("Cylinder Details Needed"))


# -- Receipt print control (Jinja) -----------------------------------------

RECEIPT_FORMATS = ("Sungas Thermal 58mm", PRINT_FORMAT)


def before_print(doc, method=None, *args, **kwargs):
    """Count receipt prints here: Frappe renders print formats read-only (no writes inside Jinja)."""
    fmt = frappe.form_dict.get("format") or frappe.form_dict.get("print_format")
    if fmt not in RECEIPT_FORMATS:
        return
    if cint(doc.docstatus) != 1:
        doc._sungas_copy = {"blocked": False, "label": _("NOT SUBMITTED - NOT A RECEIPT")}
        return
    n = cint(frappe.db.get_value(doc.doctype, doc.name, "sungas_print_count")) + 1
    user = frappe.session.user
    who = frappe.db.get_value("User", user, "full_name") or user
    at = now_datetime().strftime("%d-%m-%Y %H:%M")
    if n > 1 and not (REPRINT_ROLES & set(frappe.get_roles(user))):
        _log(doc, _("Reprint REFUSED for {0} at {1}").format(who, at))
        doc._sungas_copy = {"blocked": True, "label": _("DUPLICATE NOT ALLOWED"), "by": who, "at": at}
        return
    frappe.db.set_value(doc.doctype, doc.name, "sungas_print_count", n, update_modified=False)
    label = _("ORIGINAL") if n == 1 else _("DUPLICATE COPY #{0}").format(n - 1)
    _log(doc, _("Receipt printed: {0} by {1} at {2}").format(label, who, at))
    doc._sungas_copy = {"blocked": False, "label": label, "copy": n, "by": who, "at": at}


def receipt_copy(doc) -> dict:
    """Read-only (used inside the print template)."""
    info = getattr(doc, "_sungas_copy", None)
    if info:
        return info
    if cint(doc.docstatus) != 1:
        return {"blocked": False, "label": _("NOT SUBMITTED - NOT A RECEIPT")}
    return {"blocked": False, "label": _("COPY") if cint(doc.get("sungas_print_count")) else _("ORIGINAL")}


def lpg_kg(doc) -> float:
    """Total LPG kg on the receipt (cylinder lines count qty x size) -- carried in the dispenser barcode."""
    kg = sum(flt(it.stock_qty) or flt(it.qty) * (flt(it.conversion_factor) or 1)
             for it in doc.items if it.item_code in REFILL_ITEMS)
    return flt(kg, 2)


def cash_rounding(doc) -> float:
    return flt(doc.get("rounding_adjustment"), 2) if flt(doc.get("rounding_adjustment")) > 0 else 0.0


def _log(doc, text):
    try:
        frappe.get_doc({"doctype": "Comment", "comment_type": "Info", "reference_doctype": doc.doctype,
                        "reference_name": doc.name, "content": text}).insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "sungas.lpg_cylinders print log")


def receipt_lines(doc) -> list[dict]:
    out = []
    for it in doc.items:
        cyl = is_cyl_uom(it.uom)
        out.append({"name": it.item_name, "cyl": cyl, "uom": it.uom, "qty": flt(it.qty), "rate": flt(it.rate),
                    "amount": flt(it.amount), "kg": flt(it.stock_qty) if it.item_code in REFILL_ITEMS else None,
                    "fill_into": it.get("sungas_fill_into") or "",
                    "fill": (f"{flt(it.qty):g} x {it.uom}" if cyl else
                             f"{flt(it.stock_qty):g} kg into {it.get('sungas_fill_into') or UNKNOWN}")
                    if it.item_code in REFILL_ITEMS else None})
    return out


def customer_info(doc) -> dict:
    c = frappe.db.get_value("Customer", doc.customer, ["customer_name", "customer_group", "mobile_no"], as_dict=True) or {}
    return {"name": c.get("customer_name") or doc.customer_name, "group": c.get("customer_group") or "",
            "phone": c.get("mobile_no") or doc.get("contact_mobile") or ""}


# -- Install (after_migrate) -------------------------------------------------

def install():
    try:
        from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

        for size in SIZES:
            name = uom_name(size)
            if not frappe.db.exists("UOM", name):
                frappe.get_doc({"doctype": "UOM", "uom_name": name, "must_be_whole_number": 1}).insert(ignore_permissions=True)
        for item in REFILL_ITEMS:
            if not frappe.db.exists("Item", item):
                continue
            have = set(frappe.get_all("UOM Conversion Detail", filters={"parent": item, "parenttype": "Item"}, pluck="uom"))
            idx = len(have)
            for size in SIZES:
                if uom_name(size) in have:
                    continue
                idx += 1
                frappe.get_doc({"doctype": "UOM Conversion Detail", "parent": item, "parenttype": "Item",
                                "parentfield": "uoms", "idx": idx, "uom": uom_name(size),
                                "conversion_factor": size}).db_insert()
        fill = {"fieldname": "sungas_fill_into", "fieldtype": "Data", "label": "Fill into (cylinder)",
                "insert_after": "uom", "in_list_view": 0}
        count = {"fieldname": "sungas_print_count", "fieldtype": "Int", "label": "Receipt Prints", "read_only": 1,
                 "no_copy": 1, "allow_on_submit": 1, "insert_after": "remarks"}
        create_custom_fields({"POS Invoice Item": [fill], "Sales Invoice Item": [fill],
                              "POS Invoice": [count], "Sales Invoice": [count]}, update=True)
        _install_print_format()
        frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "sungas.lpg_cylinders.install")


def _install_print_format():
    html = frappe.read_file(frappe.get_app_path("sungas", "templates", "sungas_lpg_receipt.html"))
    vals = {"doc_type": "POS Invoice", "module": "Sungas", "print_format_type": "Jinja", "custom_format": 1,
            "standard": "No", "html": html, "disabled": 1, "css": ""}
    if frappe.db.exists("Print Format", PRINT_FORMAT):
        frappe.db.set_value("Print Format", PRINT_FORMAT, vals)
    else:
        frappe.get_doc(dict(vals, doctype="Print Format", name=PRINT_FORMAT)).insert(ignore_permissions=True)
    # Sungas 0039: tills go back to the compliant "Sungas Thermal 58mm" (now carries cylinder sizes,
    # ORIGINAL/DUPLICATE stamp and the filler slip); the separate 0038 receipt is retired.
    if not frappe.db.get_default("sungas_0039_thermal_back"):
        for p in frappe.get_all("POS Profile", filters={"print_format": PRINT_FORMAT}, pluck="name"):
            frappe.db.set_value("POS Profile", p, "print_format", "Sungas Thermal 58mm", update_modified=False)
        frappe.db.set_value("Print Format", PRINT_FORMAT, "disabled", 1)
        frappe.db.set_default("sungas_0039_thermal_back", "1")
