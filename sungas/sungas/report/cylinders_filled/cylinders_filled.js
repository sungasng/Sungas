// Patch 0038 -- cylinders filled by size, plant and cashier (match against filler slips).
frappe.query_reports["Cylinders Filled"] = {
    filters: [
        { fieldname: "from_date", label: __("From"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
        { fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
        { fieldname: "pos_profile", label: __("Till"), fieldtype: "Link", options: "POS Profile" },
    ],
};
