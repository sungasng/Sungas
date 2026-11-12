// Patch 0032 -- Commercial Desk
frappe.query_reports["Group Upgrade Prospects"] = {
    filters: [
        { fieldname: "days", label: __("Look Back (days)"), fieldtype: "Int", default: 30, reqd: 1 },
        { fieldname: "min_kg", label: __("Minimum kg"), fieldtype: "Float", default: 200, reqd: 1 },
    ],
};
