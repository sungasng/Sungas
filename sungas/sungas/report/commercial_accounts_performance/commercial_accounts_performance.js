// Patch 0032 -- Commercial Desk
frappe.query_reports["Commercial Accounts Performance"] = {
    filters: [
        { fieldname: "as_of", label: __("As Of"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
        { fieldname: "dormant_only", label: __("Dormant Only"), fieldtype: "Check" },
        { fieldname: "behind_only", label: __("Behind Target Only"), fieldtype: "Check" },
    ],
    formatter(value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);
        if (column.fieldname === "status" && data && data.status === "Behind") return `<span style="color:#c53030;font-weight:600">${value}</span>`;
        return value;
    },
};
