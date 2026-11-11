// Patch 0030 -- download a pre-filled price template from a Bulk Price Upload.
frappe.ui.form.on("LPG Bulk Price Upload", {
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
