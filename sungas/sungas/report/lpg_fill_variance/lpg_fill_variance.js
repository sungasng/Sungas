// Patch 0041 -- kg sold vs kg filled (over-fills are a loss).
frappe.query_reports["LPG Fill Variance"] = {
    filters: [
        { fieldname: "from_date", label: __("From"), fieldtype: "Date", default: frappe.datetime.month_start(), reqd: 1 },
        { fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
        { fieldname: "plant", label: __("Plant"), fieldtype: "Link", options: "Warehouse" },
    ],
};
