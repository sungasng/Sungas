// Patch 0052 -- Variance Case: status bar + one button per step (cashier signs, PM sends, Heads approve / send back).
const VC = "sungas.variance_case.";
const STEPS = [
	["Waiting for Cashier", "Cashier statement", "cashier_signed_by"],
	["Waiting for Plant Manager", "Plant Manager finding", "plant_manager_signed_by"],
	["Waiting for Head of Operations", "Head of Operations", "hod_ops_signed_by"],
	["Waiting for Head of Finance", "Head of Finance", "hod_finance_signed_by"],
];

function waited(since) {
	if (!since) return "";
	const h = (Date.now() - frappe.datetime.str_to_obj(since).getTime()) / 36e5;
	return h < 1 ? __("under 1 h") : h < 48 ? `${Math.floor(h)} h` : `${Math.floor(h / 24)} days`;
}

function statusBar(frm) {
	const d = frm.doc;
	const steps = STEPS.filter(([s]) => s !== "Waiting for Head of Finance" || d.variance_severity === "critical");
	const html = steps
		.map(([state, label, by]) => {
			const done = !!d[by] || (by === "cashier_signed_by" && d.cashier_unavailable);
			const now = d.case_status === state;
			const cls = done ? "green" : now ? "orange" : "gray";
			const note = done ? frappe.utils.escape_html(d[by] || __("unavailable")) : now ? __("waiting {0}", [waited(d.waiting_since)]) : "";
			return `<span class="indicator-pill ${cls}" style="margin-right:6px">${done ? "&#10003; " : ""}${__(label)}${note ? " &middot; " + note : ""}</span>`;
		})
		.join("&rarr; ");
	const closed = d.case_status === "Closed" ? `<span class="indicator-pill green">${__("Closed")} &middot; ${d.clearing_je || ""}</span>` : "";
	const back = d.send_back_reason && d.case_status === "Waiting for Plant Manager"
		? `<div style="margin-top:6px;color:var(--red-600)"><b>${__("Sent back")}:</b> ${frappe.utils.escape_html(d.send_back_reason)}</div>` : "";
	// Patch 0054: one plain sentence telling the person looking at the case what to do now.
	const me = frappe.session.user;
	const role = (r) => frappe.user.has_role(r) || frappe.user.has_role("System Manager");
	const todo = {
		"Waiting for Cashier": me === d.cashier ? __("Your turn: write your statement, press Save, then Sign my statement (top right).") : "",
		"Waiting for Plant Manager": role("LPG Plant Manager") && me !== d.cashier
			? __("Your turn: fill the Cause, Corrective Action and Outcome rows (they must add up to the shortage and overage), press Save, then Send for approval (top right).") : "",
		"Waiting for Head of Operations": role("LPG Head of Operations") ? __("Your turn: read the case, then Approve or Send back to Plant Manager (top right).") : "",
		"Waiting for Head of Finance": role("LPG Head of Finance") ? __("Your turn: read the case, then Approve or Send back to Plant Manager (top right).") : "",
	}[d.case_status];
	const hint = todo ? `<div style="margin-top:6px;font-weight:600" data-testid="variance-case-your-turn">${todo}</div>` : "";
	frm.set_intro(`<div data-testid="variance-case-status-bar">${closed || html}${back}${hint}</div>`, false);
}

function call(frm, method, args) {
	return frappe.call({ method: VC + method, args: Object.assign({ name: frm.doc.name }, args || {}), freeze: true,
		callback: () => frm.reload_doc() });
}

frappe.ui.form.on("POS Variance Investigation", {
	setup(frm) {
		// Patch 0055: only this till's payment types (no other plant's accounts).
		frm.set_query("mode_of_payment", "outcomes", () => ({ query: VC + "case_payment_types", filters: { case: frm.doc.name } }));
	},
	refresh(frm) {
		const d = frm.doc;
		const me = frappe.session.user;
		const isCashier = me === d.cashier;
		// Patch 0055: each Head's note is his own, open only on his turn.
		frm.set_df_property("hod_ops_notes", "read_only", d.case_status === "Waiting for Head of Operations" && frappe.user.has_role("LPG Head of Operations") ? 0 : 1);
		frm.set_df_property("hod_finance_notes", "read_only", d.case_status === "Waiting for Head of Finance" && frappe.user.has_role("LPG Head of Finance") ? 0 : 1);
		["primary_cause", "other_cause_detail", "contributing_factors", "corrective_action", "plant_manager_notes", "outcomes"]
			.forEach((f) => frm.set_df_property(f, "read_only", isCashier || d.case_status !== "Waiting for Plant Manager" && d.case_status !== "Waiting for Cashier" ? 1 : 0));
		frm.set_df_property("cashier_statement", "read_only", isCashier && !d.cashier_signed_by ? 0 : 1);
		statusBar(frm);
		// Patch 0056: a Head can add a watcher (e.g. HR) who reads the case and gets its alerts.
		if (["LPG Head of Operations", "LPG Head of Finance", "COO", "System Manager"].some((r) => frappe.user.has_role(r))) {
			frm.add_custom_button(__("Add watcher (e.g. HR)"), () =>
				frappe.prompt([{ fieldname: "user", fieldtype: "Link", options: "User", label: __("User"), reqd: 1,
					get_query: () => ({ filters: { enabled: 1, user_type: "System User" } }) }],
				(v) => call(frm, "add_watcher", { user: v.user }), __("Add watcher")));
		}
		if (d.docstatus !== 0) return;

		if (isCashier && !d.cashier_signed_by) {
			frm.add_custom_button(__("Sign my statement"), () => {
				if (frm.is_dirty()) return frappe.msgprint(__("Save your statement first."));
				frappe.confirm(__("Sign your statement? It cannot be changed after signing."), () =>
					frappe.call({ method: "sungas.overrides.pvi_rules.sign_statement", args: { name: d.name },
						callback: () => frm.reload_doc() }));
			}).addClass("btn-primary");
			return;
		}
		// Patch 0060: System Manager acts at any step only if he holds no case role himself.
		const admin = frappe.user.has_role("System Manager") && !["LPG Plant Manager", "LPG Head of Operations", "LPG Head of Finance"].some((r) => frappe.user.has_role(r));
		const pm = frappe.user.has_role("LPG Plant Manager") || admin;
		if (pm && !d.cashier_signed_by && !d.cashier_unavailable) {
			frm.add_custom_button(__("Record cashier unavailable"), () =>
				frappe.prompt([
					{ fieldname: "witness", fieldtype: "Data", label: __("Witness (full name)"), reqd: 1 },
					{ fieldname: "reason", fieldtype: "Small Text", label: __("Why she could not give a statement"), reqd: 1 },
				], (v) => frappe.call({ method: "sungas.overrides.pvi_rules.record_unavailable",
					args: { name: d.name, witness: v.witness, reason: v.reason }, callback: () => frm.reload_doc() }),
				__("Cashier unavailable (after 48 hours)")));
		}
		if (pm && d.case_status === "Waiting for Plant Manager") {
			frm.add_custom_button(__("Send for approval"), () => {
				if (frm.is_dirty()) return frappe.msgprint(__("Save the finding and outcome first."));
				frappe.confirm(__("Send this case to the Head of Operations? You cannot change it unless it is sent back."),
					() => call(frm, "send_for_approval"));
			}).addClass("btn-primary");
		}
		const turn = { "Waiting for Head of Operations": "LPG Head of Operations", "Waiting for Head of Finance": "LPG Head of Finance" }[d.case_status];
		if (turn && (frappe.user.has_role(turn) || admin)) {
			const head = turn.replace("LPG ", "");
			frm.add_custom_button(__("Approve"), () =>
				frappe.prompt([{ fieldname: "notes", fieldtype: "Small Text", label: __("Your notes as {0} (optional)", [head]) }],
					(v) => call(frm, "approve", { notes: v.notes || "" }), __("Approve {0} as {1}", [d.name, head]))).addClass("btn-primary");
			frm.add_custom_button(__("Send back to Plant Manager"), () =>
				frappe.prompt([{ fieldname: "reason", fieldtype: "Small Text", label: __("What must be corrected"), reqd: 1 }],
					(v) => call(frm, "send_back", { reason: v.reason }), __("Send back")));
		}
	},
});
