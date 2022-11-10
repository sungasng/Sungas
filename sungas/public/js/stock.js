
const mapper = (frm) => {
    console.log('here')
    frappe.model.open_mapped_doc({
        method: "sungas.utils.utils.make_delivery_trip_",
        frm: frm,
    })
}


frappe.ui.form.on('Delivery Note', {

    refresh: function(frm, dt, dn) {
        if (frm.doc.docstatus == 1) {
            frm.add_custom_button(__('Delivery Trip'), function() {
                mapper(frm) }, __('Create'));
        }

        if (frm.doc.delivery_type === "Pick Up") {
            frm.set_df_property('items', 'read_only', 1)

        }
    },

    validate: frm => {
        if (frm.doc.delivery_type === 'Pick Up' && frm.doc.items.length > 1) {
            frappe.throw("Pick Up Delivery Document Should Only Contain one Pick Up Service items")
        }
    },

    delivery_type: frm => {
        if (frm.doc.delivery_type === "Pick Up") {
            frm.doc.items = []
            frm.set_df_property('items', 'read_only', 1)

            frappe.db.get_doc('Sungas Settings').then(settings => {
                let item = frm.add_child('items')
                item.item_code = settings.default_pick_up_item
                item.item_name = settings.default_pick_up_item_name
                item.uom = 'Nos'
                item.qty = flt(1)
                item.description = 'Pick up services for customer ' + String(frm.doc.customer_name)
                frm.refresh_field("items")
            })
        }
        if (frm.doc.delivery_type === "Delivery" || frm.doc.delivery_type === "") {
            frm.doc.items = []
            frm.set_df_property('items', 'read_only', 0)
            frm.add_child('items')
            frm.refresh_field("items")
        }
    },

    })
