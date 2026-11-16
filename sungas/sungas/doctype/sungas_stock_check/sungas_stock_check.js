// Patch 0057 -- stock check case: Plant Manager finding -> Head of Operations approves or sends back.
frappe.ui.form.on("Sungas Stock Check", {
	refresh(frm) {
		const d = frm.doc;
		const has = (r) => frappe.user.has_role(r) || frappe.user.has_role("System Manager");
		const go = (method, args) => frappe.call({ method: "sungas.stock_check." + method, args: Object.assign({ name: d.name }, args),
			freeze: true, callback: () => frm.reload_doc() });
		const tip = { "Waiting for Plant Manager": has("LPG Plant Manager") ? __("Your turn: choose the Cause, write what happened, Save, then Send for approval.") : "",
			"Waiting for Head of Operations": has("LPG Head of Operations") ? __("Your turn: Approve or Send back to Plant Manager.") : "" }[d.case_status] || "";
		const back = d.send_back_reason && d.case_status === "Waiting for Plant Manager" ? `<br><b>${__("Sent back")}:</b> ${frappe.utils.escape_html(d.send_back_reason)}` : "";
		frm.set_intro(`<b>${d.result || ""}</b> ${d.case_status ? "&middot; " + d.case_status : ""}${back}${tip ? "<br>" + tip : ""}`, d.result === "Variance" ? "orange" : "green");
		["cause", "finding"].forEach((f) => frm.set_df_property(f, "read_only", d.case_status === "Waiting for Plant Manager" ? 0 : 1));
		frm.set_df_property("hoo_notes", "read_only", d.case_status === "Waiting for Head of Operations" ? 0 : 1);
		if (d.case_status === "Waiting for Plant Manager" && has("LPG Plant Manager"))
			frm.add_custom_button(__("Send for approval"), () => frm.is_dirty() ? frappe.msgprint(__("Save first.")) : go("send_for_approval")).addClass("btn-primary");
		if (d.case_status === "Waiting for Head of Operations" && has("LPG Head of Operations")) {
			frm.add_custom_button(__("Approve"), () => go("decide", { approve: 1, notes: d.hoo_notes || "" })).addClass("btn-primary");
			frm.add_custom_button(__("Send back to Plant Manager"), () => frappe.prompt([{ fieldname: "r", fieldtype: "Small Text", label: __("What must be corrected"), reqd: 1 }],
				(v) => go("decide", { approve: 0, notes: v.r }), __("Send back")));
		}
	},
});
