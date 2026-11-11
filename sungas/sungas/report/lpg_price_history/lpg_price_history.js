// Patch 0029 -- LPG Price History
frappe.query_reports["LPG Price History"] = {
    filters: [
        { fieldname: "from_date", label: __("From Date"), fieldtype: "Date",
          default: frappe.datetime.add_months(frappe.datetime.get_today(), -12), reqd: 1 },
        { fieldname: "to_date", label: __("To Date"), fieldtype: "Date",
          default: frappe.datetime.get_today(), reqd: 1 },
        { fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
        { fieldname: "territory", label: __("Plant (Territory)"), fieldtype: "Link", options: "Territory" },
        { fieldname: "customer_group", label: __("Customer Group"), fieldtype: "Link", options: "Customer Group" },
    ],
};
