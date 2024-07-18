// Copyright (c) 2022, Manqala and contributors
// For license information, please see license.txt

frappe.ui.form.on('Sungas Settings', {
	refresh: frm => {
		frm.events.filter_delivery_stop_doctype(frm);
	},

	filter_delivery_stop_doctype: frm => {
		frm.fields_dict.delivery_stop_type.grid.get_field('doctype_').get_query = function(doc, cdt, cdn) {
			return {
				filters: [
					["name", "IN", ["Sales Order", "Delivery Note"]],
					["name", "NOT IN", frm.doc.delivery_stop_type.map(row => row.doctype_)]
				],
			}
		}
	}
})

frappe.ui.form.on('Delivery Stop Type', {
	// 
})
