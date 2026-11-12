// Patch 0032/0033 -- group, account owner and kg target are set by the Commercial Desk / Head of Sales only.
frappe.ui.form.on("Customer", {
	refresh(frm) {
		const desk = ["LPG Commercial Desk", "LPG Head of Sales", "LPG Deputy Head of Sales", "System Manager"].some((r) => frappe.user.has_role(r));
		["customer_group", "sungas_account_owner", "sungas_expected_monthly_kg"].forEach((f) =>
			frm.set_df_property(f, "read_only", desk ? 0 : 1),
		);
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
