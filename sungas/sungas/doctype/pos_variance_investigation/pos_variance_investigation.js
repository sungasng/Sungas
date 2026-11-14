// Patch 0045 -- cashier signs her own statement; Plant Manager records an unavailable cashier.
frappe.ui.form.on("POS Variance Investigation", {
	refresh(frm) {
		if (frm.doc.docstatus !== 0 || frm.doc.cashier_signed_by) return;
		if (frappe.session.user === frm.doc.cashier) {
			frm.add_custom_button(__("Sign my statement"), () => {
				if (frm.is_dirty()) return frappe.msgprint(__("Save your statement first."));
				frappe.confirm(__("Sign your statement? It cannot be changed after signing."), () =>
					frappe.call({ method: "sungas.overrides.pvi_rules.sign_statement", args: { name: frm.doc.name },
						callback: () => frm.reload_doc() }));
			}).addClass("btn-primary");
		} else if (frappe.user.has_role("LPG Plant Manager") || frappe.user.has_role("LPG Head of Operations")) {
			frm.add_custom_button(__("Record cashier unavailable"), () =>
				frappe.prompt([
					{ fieldname: "witness", fieldtype: "Data", label: __("Witness (full name)"), reqd: 1 },
					{ fieldname: "reason", fieldtype: "Small Text", label: __("Why she could not give a statement"), reqd: 1 },
				], (v) => frappe.call({ method: "sungas.overrides.pvi_rules.record_unavailable",
					args: { name: frm.doc.name, witness: v.witness, reason: v.reason }, callback: () => frm.reload_doc() }),
				__("Cashier unavailable (after 48 hours)")));
		}
	},
});
