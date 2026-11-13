// Patch 0032 -- Commercial Desk approves / rejects group change requests.
frappe.ui.form.on("Customer Group Change Request", {
	onload(frm) {
		// 0036: group fields are plain choices (ERPNext would rewrite Customer Group links).
		frappe.db.get_list("Customer Group", { filters: { is_group: 0 }, pluck: "name", limit: 50 }).then((groups) => {
			frm.set_df_property("requested_group", "options", [""].concat(groups).join("\n"));
			frm.set_df_property("current_group", "options", [""].concat(groups).join("\n"));
			frm.refresh_field("requested_group");
		});
	},
	refresh(frm) {
		const desk = ["LPG Commercial Desk", "LPG Head of Sales", "LPG Deputy Head of Sales", "System Manager"].some((r) => frappe.user.has_role(r));
		if (frm.is_new() || frm.doc.status !== "Pending" || !desk) return;
		const decide = (method, title, reqd) =>
			frappe.prompt(
				[{ fieldname: "note", fieldtype: "Small Text", label: __("Note"), reqd }],
				(v) =>
					frappe
						.call({ method: `sungas.commercial_desk.${method}`, args: { name: frm.doc.name, note: v.note } })
						.then(() => frm.reload_doc()),
				title,
			);
		frm.add_custom_button(__("Approve"), () => decide("approve", __("Approve group change"), 0)).addClass("btn-primary");
		frm.add_custom_button(__("Reject"), () => decide("reject", __("Reject group change"), 1));
	},
});
