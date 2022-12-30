// Copyright (c) 2022, Manqala and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["End of Day Report (Creation Date)"] = {
	"filters": [
			{
				fieldname:"from_date",
				label: __("From Date"),
				fieldtype: "Date",
				default: new Date(),
				reqd: 1
			},
			{
				fieldname:"to_date",
				label: __("To Date"),
				fieldtype: "Date",
				default: new Date(),
				reqd: 1
			},
			{
				fieldname:"customer",
				label: __("Customer"),
				fieldtype: "Link",
				options:"Customer",
				reqd: 0
			},
			{
				fieldname:"warehouse",
				label: __("Warehoue"),
				fieldtype: "Link",
				options:"Warehouse",
				reqd: 0
			},
			{
				fieldname:"item_group",
				label: __("Item Group"),
				fieldtype: "Link",
				options:"Item Group",
				reqd: 0
			},
			{
				fieldname:"pos_profile",
				label: __("Store"),
				fieldtype: "Link",
				options:"POS Profile",
				reqd:0
			},
		]
};



