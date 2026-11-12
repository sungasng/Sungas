// Patch 0032 -- Commercial Desk approves / rejects group change requests.
frappe.ui.form.on("Customer Group Change Request", {
	refresh(frm) {
		const desk = frappe.user.has_role("LPG Commercial Desk") || frappe.user.has_role("System Manager");
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
