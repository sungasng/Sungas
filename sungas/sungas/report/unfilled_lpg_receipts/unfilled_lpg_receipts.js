// Patch 0041 -- paid LPG receipts not yet filled.
frappe.query_reports["Unfilled LPG Receipts"] = {
    filters: [
        { fieldname: "plant", label: __("Plant"), fieldtype: "Link", options: "Warehouse" },
        { fieldname: "status", label: __("Status"), fieldtype: "Select",
          options: ["", "Awaiting Fill", "Extended", "Expired", "Refund Approved"] },
    ],
};
