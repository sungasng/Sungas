// Patch 0032 -- Commercial Desk
frappe.query_reports["Account Leakage Watch"] = {
    filters: [
        { fieldname: "from_date", label: __("From"), fieldtype: "Date", default: frappe.datetime.add_days(frappe.datetime.get_today(), -7), reqd: 1 },
        { fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
        { fieldname: "per_day", label: __("Flag at invoices / day"), fieldtype: "Int", default: 3, reqd: 1 },
    ],
};
