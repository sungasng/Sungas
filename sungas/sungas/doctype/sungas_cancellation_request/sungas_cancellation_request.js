// Patch 0062 -- Finance approves or declines a cashier's request to cancel a receipt.
frappe.ui.form.on("Sungas Cancellation Request", {
	refresh(frm) {
		if (frm.doc.status !== "Pending") return;
		const decide = (approve) =>
			frappe.prompt([{ fieldname: "note", fieldtype: "Small Text", label: __("Finance note"), reqd: !approve }], (v) =>
				frappe.call({
					method: "sungas.receipt_cancel.decide",
					args: { name: frm.doc.name, approve: approve ? 1 : 0, note: v.note || "" },
					callback: (r) => { frappe.show_alert({ message: r.message.message, indicator: approve ? "green" : "orange" }); frm.reload_doc(); },
				}),
			approve ? __("Approve and cancel {0}", [frm.doc.pos_invoice]) : __("Decline"));
		frm.add_custom_button(__("Approve cancellation"), () => decide(true)).addClass("btn-primary");
		frm.add_custom_button(__("Decline"), () => decide(false));
	},
});
