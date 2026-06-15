/**
 * Sungas customisation for Payroll Entry form.
 *
 * Adds a "Generate Bank Upload" button (only on submitted Payroll Entries)
 * that opens a dialog where finance can pick a bank, optionally tweak the
 * narration, and download the xlsx file directly -- no bench command needed.
 *
 * Server endpoint: sungas.payroll.bank_upload.generate_bank_upload
 */

const SUPPORTED_BANKS = [
    { value: "stanbic", label: "Stanbic IBTC" },
    { value: "fidelity", label: "Fidelity Bank" },
];

frappe.ui.form.on("Payroll Entry", {
    refresh: function (frm) {
        // Only meaningful once the entry has slips (i.e. saved or submitted).
        if (frm.doc.docstatus === 2) return;
        if (frm.is_new()) return;

        frm.add_custom_button(__("Generate Bank Upload"), function () {
            show_bank_upload_dialog(frm);
        }, __("Bank Upload"));
    },
});

function show_bank_upload_dialog(frm) {
    // Pre-compute a default narration like "PAYMENT OF MAY 2026 SALARY"
    let default_narration = "";
    if (frm.doc.start_date) {
        const d = frappe.datetime.str_to_obj(frm.doc.start_date);
        const months = ["JANUARY","FEBRUARY","MARCH","APRIL","MAY","JUNE",
                        "JULY","AUGUST","SEPTEMBER","OCTOBER","NOVEMBER","DECEMBER"];
        default_narration = `PAYMENT OF ${months[d.getMonth()]} ${d.getFullYear()} SALARY`;
    }

    const dialog = new frappe.ui.Dialog({
        title: __("Generate Bank Upload"),
        fields: [
            {
                fieldname: "bank",
                fieldtype: "Select",
                label: __("Bank"),
                options: SUPPORTED_BANKS.map(b => `${b.value}\n`).join("").trim() ||
                         SUPPORTED_BANKS.map(b => b.value).join("\n"),
                reqd: 1,
                default: "stanbic",
                description: __("Pick the bank you'll upload to. Each bank has its own column layout."),
            },
            {
                fieldname: "narration",
                fieldtype: "Data",
                label: __("Narration"),
                default: default_narration,
                description: __("Goes on each beneficiary's narration line. Fidelity clamps to 5-47 chars."),
            },
            {
                fieldname: "include_draft",
                fieldtype: "Check",
                label: __("Include Draft Slips (Dry Run)"),
                default: frm.doc.docstatus === 1 ? 0 : 1,
                description: __("Tick this if the Payroll Entry hasn't been fully submitted yet and you want to preview the file."),
            },
        ],
        primary_action_label: __("Generate"),
        primary_action: function (values) {
            frappe.dom.freeze(__("Building xlsx..."));
            frappe.call({
                method: "sungas.payroll.bank_upload.generate_bank_upload",
                args: {
                    payroll_entry: frm.doc.name,
                    bank: values.bank,
                    narration: values.narration || "",
                    include_draft: values.include_draft ? 1 : 0,
                },
                callback: function (r) {
                    frappe.dom.unfreeze();
                    if (!r.message) return;
                    dialog.hide();
                    frappe.show_alert({
                        message: __("Generated {0} ({1} rows). Downloading...",
                                    [r.message.file_name, r.message.row_count]),
                        indicator: "green",
                    }, 7);
                    // Open in new tab (private file => browser will download)
                    window.open(r.message.file_url, "_blank");
                    // Refresh the form so the new attachment shows up.
                    frm.reload_doc();
                },
                error: function () {
                    frappe.dom.unfreeze();
                },
            });
        },
    });

    dialog.show();
}
