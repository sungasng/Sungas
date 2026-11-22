// Patch 0067 -- recorded stock less till receipts not yet closed.
frappe.query_reports["Stock Available Now"] = {
    filters: [
        { fieldname: "plant", label: __("Plant"), fieldtype: "Link", options: "Warehouse" },
        { fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
    ],
};
