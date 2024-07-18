import frappe


def get_stock_availability(item_code, warehouse):
    if frappe.db.get_value("Item", item_code, "is_stock_item"):
        is_stock_item = True
        bin_qty = get_bin_qty(item_code, warehouse)
        pos_sales_qty = get_pos_reserved_qty(item_code, warehouse)
        return bin_qty - pos_sales_qty, is_stock_item
    else:
        is_stock_item = False
        if frappe.db.exists("Product Bundle", item_code):
            return get_bundle_availability(item_code, warehouse), is_stock_item
        else:
            # Is a service item
            return 0, is_stock_item


def get_bundle_availability(bundle_item_code, warehouse):
    product_bundle = frappe.get_doc("Product Bundle", bundle_item_code)

    bundle_bin_qty = 1000000
    for item in product_bundle.items:
        item_bin_qty = get_bin_qty(item.item_code, warehouse)
        item_pos_reserved_qty = get_pos_reserved_qty(item.item_code, warehouse)
        available_qty = item_bin_qty - item_pos_reserved_qty

        max_available_bundles = available_qty / item.qty
        if bundle_bin_qty > max_available_bundles and frappe.get_value(
            "Item", item.item_code, "is_stock_item"
        ):
            bundle_bin_qty = max_available_bundles

    pos_sales_qty = get_pos_reserved_qty(bundle_item_code, warehouse)
    return bundle_bin_qty - pos_sales_qty


def get_bin_qty(item_code, warehouse):
    bin_qty = frappe.db.sql(
        """select actual_qty from `tabBin`
        where item_code = %s and warehouse = %s
        limit 1""",
        (item_code, warehouse),
        as_dict=1,
    )
    return bin_qty[0].actual_qty or 0 if bin_qty else 0


def get_pos_reserved_qty(item_code, warehouse):
    reserved_qty = frappe.db.sql(
        """select sum(p_item.qty) as qty
        from `tabPOS Invoice` p, `tabPOS Invoice Item` p_item
        where p.name = p_item.parent
        and ifnull(p.consolidated_invoice, '') = ''
        and p_item.docstatus = 1
        and p_item.item_code = %s
        and p_item.warehouse = %s
        """,
        (item_code, warehouse),
        as_dict=1,
    )
    return reserved_qty[0].qty or 0 if reserved_qty else 0
