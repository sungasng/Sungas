// Patch 0032 -- customer group is set by the Commercial Desk only.
frappe.ui.form.on("Customer", {
	refresh(frm) {
		const desk = frappe.user.has_role("LPG Commercial Desk") || frappe.user.has_role("System Manager");
		frm.set_df_property("customer_group", "read_only", desk ? 0 : 1);
		frm.toggle_display("sungas_group_change_reason", desk);
		if (frm.is_new()) return;
		frm.add_custom_button(
			__("Request Group Change"),
			() => frappe.new_doc("Customer Group Change Request", { customer: frm.doc.name }),
			__("Commercial Desk"),
		);
		frm.add_custom_button(
			__("Group Change History"),
			() => frappe.set_route("List", "Customer Group Change Request", { customer: frm.doc.name }),
			__("Commercial Desk"),
		);
	},
});
