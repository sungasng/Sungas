// Patch 0057 -- choosing the plant lays out one row per dispenser and per tank.
frappe.ui.form.on("Sungas Plant Reading", {
	plant(frm) {
		if (!frm.doc.plant) return;
		frappe.db.get_doc("Sungas Plant Setup", frm.doc.plant).then((p) => {
			frm.clear_table("dispensers");
			for (let i = 1; i <= (p.dispenser_count || 1); i++) frm.add_child("dispensers", { dispenser_no: i });
			frm.clear_table("tanks");
			(p.tanks || []).forEach((t) => frm.add_child("tanks", { tank_name: t.tank_name, instrument: t.instrument }));
			if (!frm.doc.taken_by && p.reading_supervisor) frm.set_value("taken_by", p.reading_supervisor);
			frm.refresh_fields();
		});
	},
	refresh(frm) {
		if (frm.doc.docstatus === 0 && !frm.is_new())
			frm.set_intro(__("Platform Supervisor (or cover) enters the readings and saves; the Plant Manager checks them and presses Submit to confirm."));
	},
});
