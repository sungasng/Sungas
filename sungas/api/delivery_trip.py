import frappe
from frappe.model.mapper import get_mapped_doc


def get_delivery_type(doctype):

    stop_type_settings = frappe.get_cached_doc(
        "Sungas Settings"
    ).delivery_stop_type

    delivery_stop_dict = {
        row.doctype_: row.delivery_stop_type for row in stop_type_settings
    }
    return delivery_stop_dict.get(
            doctype, ""
        )


@frappe.whitelist()
def make_delivery_trip_(source_name, target_doc=None):
    def update_stop_details(source_doc, target_doc, source_parent):
        target_doc.customer = source_parent.customer
        target_doc.customer_name = source_parent.customer_name
        target_doc.customer_phone = source_parent.contact_mobile
        target_doc.address = source_parent.shipping_address_name
        target_doc.customer_address = source_parent.shipping_address
        target_doc.contact = source_parent.contact_person
        target_doc.customer_contact = source_parent.contact_display
        target_doc.from_doctype = source_parent.doctype
        target_doc.grand_total = source_parent.grand_total
        target_doc.delivery_type = get_delivery_type(
            source_parent.doctype
        )

        # Append unique Delivery Notes in Delivery Trip
        delivery_notes.append(target_doc.delivery_note)

    delivery_notes = []

    doclist = get_mapped_doc(
        "Delivery Note",
        source_name,
        {
            "Delivery Note": {
                "doctype": "Delivery Trip",
                "validation": {"docstatus": ["=", 1]}
            },
            "Delivery Note Item": {
                "doctype": "Delivery Stop",
                "field_map": {"parent": "delivery_note"},
                "condition": lambda item: item.parent not in delivery_notes,
                "postprocess": update_stop_details,
            },
        },
        target_doc,
    )

    return doclist


@frappe.whitelist()
def make_delivery_trip_from_sales_order(source_name, target_doc=None):
    def update_stop_details(source_doc, target_doc, source_parent):
        target_doc.customer = source_parent.customer
        target_doc.customer_name = source_parent.customer_name
        target_doc.customer_phone = source_parent.contact_mobile
        target_doc.address = source_parent.customer_address
        target_doc.customer_address = source_parent.address_display
        target_doc.contact = source_parent.contact_person
        target_doc.customer_contact = source_parent.contact_display
        target_doc.grand_total = source_parent.grand_total
        target_doc.from_doctype = source_parent.doctype
        target_doc.delivery_type = get_delivery_type(
            source_parent.doctype
        )

        # Append unique Sales Order in Delivery Trip
        sales_order.append(target_doc.sales_order)

    sales_order = []

    doclist = get_mapped_doc(
        "Sales Order",
        source_name,
        {
            "Sales Order": {
                "doctype": "Sales Order",
                "validation": {"docstatus": ["=", 1]}
            },
            "Sales Order Item": {
                "doctype": "Delivery Stop",
                "field_map": {"parent": "sales_order"},
                "condition": lambda item: item.parent not in sales_order,
                "postprocess": update_stop_details,
            },
        },
        target_doc,
    )
    return doclist
