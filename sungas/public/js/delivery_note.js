
const mapper = (frm) => {
    
}


frappe.ui.form.on('Delivery Note', {

    onload_post_render: frm => {
        frm.events.update_creat_delivery_trip_button(frm);
    },

    timeline_refresh: frm => {
        frm.events.update_creat_delivery_trip_button(frm);
    },

    update_creat_delivery_trip_button: frm => {
        if (frm.doc.docstatus == 1) {
            frm.remove_custom_button(__('Delivery Trip'), __('Create'))

            frm.add_custom_button(__('Delivery Trip'), function() {
                frappe.model.open_mapped_doc({
                    method: "sungas.api.delivery_trip.make_delivery_trip_",
                    frm: frm,
                })
            }, __('Create'));
        }
    },

})
