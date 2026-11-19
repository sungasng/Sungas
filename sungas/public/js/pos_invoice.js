// Patch 0041 -- Plant Manager decides on paid receipts that were not filled in time.
frappe.ui.form.on("POS Invoice", {
	refresh(frm) {
		// Patch 0062 -- cashiers ask Finance to cancel; they no longer cancel themselves.
		if (frm.doc.docstatus === 1 && !frm.doc.is_return && !frm.doc.consolidated_invoice) {
			frm.add_custom_button(__("Request cancellation"), () =>
				frappe.prompt([{ fieldname: "reason", fieldtype: "Small Text", label: __("Why should this receipt be cancelled?"), reqd: 1 }], (v) =>
					frappe.call({
						method: "sungas.receipt_cancel.request",
						args: { invoice: frm.doc.name, reason: v.reason },
						callback: (r) => frappe.msgprint(r.message.message),
					}),
				__("Request cancellation of {0}", [frm.doc.name])));
		}
		const st = frm.doc.sungas_fill_status;
		const can = ["LPG Plant Manager", "LPG Head of Operations", "LPG Head of Finance", "System Manager"].some((r) =>
			frappe.user.has_role(r),
		);
		if (frm.doc.docstatus !== 1 || !can || !["Awaiting Fill", "Extended", "Expired"].includes(st)) return;
		const decide = (action, fields) =>
			frappe.prompt(fields, (v) =>
				frappe.call({
					method: "sungas.lpg_fill.decide",
					args: { invoice: frm.doc.name, action, note: v.note, days: v.days || 0 },
					callback: (r) => { frappe.show_alert({ message: r.message.message, indicator: "green" }); frm.reload_doc(); },
				}),
			__(action === "Extend" ? "Extend fill time" : "Approve refund"));
		const note = { fieldname: "note", fieldtype: "Small Text", label: __("Reason"), reqd: 1 };
		frm.add_custom_button(__("Extend fill time"), () =>
			decide("Extend", [{ fieldname: "days", fieldtype: "Int", label: __("Extra days (1-7)"), default: 7, reqd: 1 }, note]),
			__("Unfilled gas"));
		frm.add_custom_button(__("Approve refund"), () => decide("Refund", [note]), __("Unfilled gas"));
	},
});
