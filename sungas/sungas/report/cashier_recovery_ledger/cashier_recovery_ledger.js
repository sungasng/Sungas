// Copyright (c) 2026, Manqala and contributors
frappe.query_reports["Cashier Recovery Ledger"] = {
	filters: [
		{ fieldname: "employee", label: __("Cashier (Employee)"), fieldtype: "Link", options: "Employee" },
		{ fieldname: "from_date", label: __("From"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "summary", label: __("One line per cashier"), fieldtype: "Check", default: 1 },
		{ fieldname: "outstanding_only", label: __("Only cashiers who still owe"), fieldtype: "Check", default: 1,
			depends_on: "eval:doc.summary" },
	],
};
