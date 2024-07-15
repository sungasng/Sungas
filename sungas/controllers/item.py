import frappe


def item_name(doc, event):
    if frappe.db.get_default("item_naming_by") == "Naming Series":
        if doc.variant_of:
            doc.naming_series = frappe.db.get_value(
                "Item", doc.variant_of, 'naming_series'
            )
        from frappe.model.naming import set_name_by_naming_series
        set_name_by_naming_series(doc)
        doc.item_code = doc.name
