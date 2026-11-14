"""Patch 0040 -- till rules enforced by the ERP (not only by POS settings)."""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, validate_email_address

BLOCKED_CUSTOMER_GROUPS = ("Bulk",)
BLOCKED_ITEM_GROUPS = ("Equipment",)
TILL_CUSTOMER_GROUPS = ("Retail", "Commercial", "Distributors")
TILL_ITEM_GROUPS = ("LPG", "LPG-Cylinders", "Gas Cookers", "Accessories")


def validate(doc, method=None):
    if doc.get("is_return"):
        return
    group = frappe.db.get_value("Customer", doc.customer, "customer_group")
    if group in BLOCKED_CUSTOMER_GROUPS:
        frappe.throw(_("{0} is a Bulk customer. Bulk customers are served by the Bulk desk, not the till. "
                       "If they want to buy as Retail, change the customer to a Retail walk-in customer.").format(doc.customer_name or doc.customer),
                     title=_("Bulk customer"))
    bad = [it.item_name or it.item_code for it in doc.items
           if frappe.db.get_value("Item", it.item_code, "item_group") in BLOCKED_ITEM_GROUPS]
    if bad:
        frappe.throw(_("Equipment is not sold at the till: {0}").format(", ".join(bad)), title=_("Not a till item"))


def before_submit(doc, method=None):
    if doc.get("is_return"):
        return
    due = flt(doc.rounded_total) or flt(doc.grand_total)
    paid = flt(doc.paid_amount) + flt(doc.get("write_off_amount"))
    if paid + 0.5 < due:
        frappe.throw(_("Part payment and credit sales are not allowed at the till. Amount due {0}, paid {1}.")
                     .format(frappe.format_value(due, {"fieldtype": "Currency"}), frappe.format_value(paid, {"fieldtype": "Currency"})),
                     title=_("Full payment required"))


@frappe.whitelist()
def email_receipt(invoice: str, email: str):
    """Email the receipt (PDF) to the customer; save the address on the customer if they had none."""
    email = (email or "").strip()
    validate_email_address(email, throw=True)
    doc = frappe.get_doc("POS Invoice", invoice)
    doc.check_permission("read")
    if doc.docstatus != 1:
        frappe.throw(_("Only a paid receipt can be emailed."))
    cust = frappe.get_doc("Customer", doc.customer)
    if not cust.email_id:
        frappe.db.set_value("Customer", cust.name, "email_id", email)
    doc._sungas_copy = {"blocked": False, "label": _("EMAIL COPY - NOT FOR FILLING"), "email": True}
    frappe.sendmail(recipients=[email], subject=_("Your Sungas receipt {0}").format(doc.name),
                    message=_("Dear {0},<br><br>Thank you for your purchase. Your receipt is attached.<br><br>Sungas").format(doc.customer_name),
                    attachments=[frappe.attach_print("POS Invoice", doc.name, file_name=doc.name,
                                                     print_format="Sungas Thermal 58mm", doc=doc)],
                    reference_doctype="POS Invoice", reference_name=doc.name, now=True)
    return {"sent": True, "saved_on_customer": not cust.email_id}


def install():
    """Limit every till to the till customer/item groups and switch off part payment / credit sale."""
    try:
        for p in frappe.get_all("POS Profile", filters={"disabled": 0}, pluck="name"):
            prof = frappe.get_doc("POS Profile", p)
            prof.set("customer_groups", [{"customer_group": g} for g in TILL_CUSTOMER_GROUPS])
            prof.set("item_groups", [{"item_group": g} for g in TILL_ITEM_GROUPS])
            for f in ("posa_allow_partial_payment", "posa_allow_credit_sale"):
                if prof.meta.has_field(f):
                    prof.set(f, 0)
            prof.flags.ignore_permissions = True
            prof.save()
        frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "sungas.pos_sale_rules.install")
