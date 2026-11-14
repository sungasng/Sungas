// Patch 0043 -- Plant Manager records the bank deposit; Finance matches the draft bank posting.
frappe.ui.form.on("Sungas Cash Lodgement", {
	setup(frm) {
		frm.set_query("bank_account", () => ({
			filters: { company: frm.doc.company, account_type: "Bank", is_group: 0 },
		}));
	},
	refresh(frm) {
		if (frm.doc.status === "In Transit" && frm.doc.bank_journal) {
			frm.dashboard.set_headline(
				__("Finance: match {0} to the bank statement, then submit the draft bank posting {1}.", [
					format_currency(frm.doc.lodged_amount), frm.doc.bank_journal,
				]),
			);
			frm.add_custom_button(__("Open draft bank posting"), () =>
				frappe.set_route("Form", "Journal Entry", frm.doc.bank_journal));
		}
	},
	lodged_amount(frm) {
		frm.set_value("difference", flt(frm.doc.lodged_amount) - flt(frm.doc.cash_to_lodge));
	},
});
