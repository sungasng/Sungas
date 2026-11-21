// Patch 0065 -- source outlet = the user's own plant(s); no past schedule dates.
frappe.ui.form.on("Daily Loading Schedule", {
	onload(frm) {
		frappe.call("sungas.overrides.dls_guard.my_plants").then((r) => {
			const plants = r.message || [];
			if (!plants.length) return;
			frm.set_query("source_outlet", () => ({ filters: { name: ["in", plants] } }));
			if (frm.is_new() && !frm.doc.source_outlet && plants.length === 1) frm.set_value("source_outlet", plants[0]);
		});
	},
	refresh(frm) {
		const f = frm.fields_dict.schedule_date;
		if (frm.is_new() && f && f.datepicker) f.datepicker.update({ minDate: new Date(frappe.datetime.get_today()) });
	},
});
