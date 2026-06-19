// Copyright (c) 2026, Manqala and contributors
// For license information, please see license.txt

frappe.query_reports["Cashier Variance Ledger"] = {
    filters: [
        {
            fieldname: "company",
            label: __("Company"),
            fieldtype: "Link",
            options: "Company",
            default: frappe.defaults.get_user_default("Company"),
            reqd: 1,
        },
        {
            fieldname: "from_date",
            label: __("From Date"),
            fieldtype: "Date",
            default: frappe.datetime.add_days(frappe.datetime.get_today(), -90),
            reqd: 1,
        },
        {
            fieldname: "to_date",
            label: __("To Date"),
            fieldtype: "Date",
            default: frappe.datetime.get_today(),
            reqd: 1,
        },
        {
            fieldname: "employee",
            label: __("Cashier (Employee)"),
            fieldtype: "Link",
            options: "Employee",
        },
        {
            fieldname: "open_only",
            label: __("Open Balances Only"),
            fieldtype: "Check",
            default: 1,
        },
    ],

    formatter(value, row, column, data, default_formatter) {
        let v = default_formatter(value, row, column, data);
        if (column.fieldname === "open_balance" && data && data.open_balance != null) {
            const b = parseFloat(data.open_balance);
            if (b > 0) v = `<span style="color:#b91c1c">${v}</span>`;
            else if (b < 0) v = `<span style="color:#0a7">${v}</span>`;
        }
        if (column.fieldname === "days_open" && data && data.days_open > 14) {
            v = `<span style="color:#b91c1c;font-weight:600">${v}</span>`;
        }
        return v;
    },
};
