// Patch 0032 -- Commercial Desk
frappe.query_reports["Commercial Accounts Performance"] = {
    filters: [
        { fieldname: "as_of", label: __("As Of"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
        { fieldname: "dormant_only", label: __("Dormant Only"), fieldtype: "Check" },
    ],
};
