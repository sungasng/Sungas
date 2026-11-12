// Patch 0035 -- Weekly Engagement Plan actions.
frappe.ui.form.on("Weekly Engagement Plan", {
	refresh(frm) {
		if (frm.is_new()) return;
		const me = frappe.session.user === frm.doc.owner_user;
		const decider = ["LPG Commercial Desk", "LPG Head of Sales", "LPG Deputy Head of Sales", "System Manager"].some((r) =>
			frappe.user.has_role(r),
		);
		const call = (method, args = {}) =>
			frappe.call({ method: `sungas.engagement.${method}`, args: { name: frm.doc.name, ...args } }).then(() => frm.reload_doc());
		const withNote = (method, title, reqd) =>
			frappe.prompt([{ fieldname: "note", fieldtype: "Small Text", label: __("Note"), reqd }], (v) => call(method, { note: v.note }), title);
		const s = frm.doc.status;
		if ((me || decider) && ["Draft", "Sent Back"].includes(s))
			frm.add_custom_button(__("Submit for Approval"), () => frm.save().then(() => call("submit_plan"))).addClass("btn-primary");
		if (decider && ["Pending Approval", "Executing Unapproved"].includes(s)) {
			frm.add_custom_button(__("Approve"), () => withNote("approve_plan", __("Approve plan"), 0)).addClass("btn-primary");
			frm.add_custom_button(__("Send Back"), () => withNote("send_back_plan", __("Send plan back"), 1));
		}
		if ((me || decider) && ["Approved", "Executing Unapproved"].includes(s))
			frm.add_custom_button(__("Report Outcomes"), () => frm.save().then(() => call("report_outcome"))).addClass("btn-primary");
		if (decider && s === "Outcome Reported")
			frm.add_custom_button(__("Close Plan"), () => withNote("close_plan", __("Close plan"), 0)).addClass("btn-primary");
		const colour = { Draft: "orange", "Sent Back": "red", "Pending Approval": "orange", Approved: "green",
			"Executing Unapproved": "yellow", "Outcome Reported": "blue", Closed: "gray" }[s];
		frm.page.set_indicator(__(s), colour);
	},
});
