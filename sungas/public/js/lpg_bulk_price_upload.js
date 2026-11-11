// Patch 0030 -- download a pre-filled price template from a Bulk Price Upload.
// Patch 0030a: attaching a file fills the rows table straight away; blank rows are dropped on save.
const sungas_drop_blank_rows = (frm) => {
    const keep = (frm.doc.rows || []).filter((r) => r.item_code);
    if (keep.length !== (frm.doc.rows || []).length) {
        frm.doc.rows = keep;
        keep.forEach((r, i) => { r.idx = i + 1; });
        frm.refresh_field("rows");
    }
};

frappe.ui.form.on("LPG Bulk Price Upload", {
    onload(frm) {
        if (frm.is_new()) sungas_drop_blank_rows(frm);
    },
    validate(frm) {
        sungas_drop_blank_rows(frm);
    },
    upload_source_file(frm) {
        if (!frm.doc.upload_source_file || frm.doc.docstatus !== 0) return;
        frappe.call({
            method: "sungas.api.pricing_template.parse_template",
            args: { file_url: frm.doc.upload_source_file },
            freeze: true,
            freeze_message: __("Reading price file..."),
        }).then((r) => {
            const rows = r.message || [];
            if (!rows.length) {
                frappe.msgprint(__("No changed prices found in the file. Change new_rate on the rows you want to update."));
                return;
            }
            frm.clear_table("rows");
            rows.forEach((row) => Object.assign(frm.add_child("rows"), row));
            frm.refresh_field("rows");
            frappe.show_alert({ message: __("{0} price row(s) loaded. Click Save.", [rows.length]), indicator: "green" });
        });
    },
    refresh(frm) {
        if (frm.doc.docstatus !== 0) return;
        frm.add_custom_button(__("Download Price Template"), () => {
            const d = new frappe.ui.Dialog({
                title: __("Download Price Template"),
                fields: [
                    { fieldname: "item_code", label: __("Item (optional)"), fieldtype: "Link", options: "Item" },
                    { fieldname: "customer_group", label: __("Customer Group (optional)"), fieldtype: "Link",
                      options: "Customer Group" },
                    { fieldname: "territory", label: __("Region or Plant (optional)"), fieldtype: "Link",
                      options: "Territory" },
                    { fieldname: "help", fieldtype: "HTML", options: `<div class="text-muted small">
                        The file lists every current price (national, regional and plant) with
                        <b>new_rate</b> pre-filled with today's price.<br>
                        1. Change <b>new_rate</b> only on the rows you want to change (unchanged rows are ignored).<br>
                        2. A changed <b>national or regional</b> row also sets every plant below it,
                           unless you change that plant's row too.<br>
                        3. Add a <b>justification</b> for any change above 15%.<br>
                        4. Save as CSV, attach it in <b>Upload Source File</b> on a new upload and Save.</div>` },
                ],
                primary_action_label: __("Download"),
                primary_action(v) {
                    const q = new URLSearchParams(Object.fromEntries(Object.entries(v).filter(([k, x]) => x && k !== "help")));
                    window.open(`/api/method/sungas.api.pricing_template.download_bulk_template?${q.toString()}`);
                    d.hide();
                },
            });
            d.show();
        });
    },
});
