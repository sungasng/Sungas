
const mapCurrentDoc = (frm, doctype, method_path) => {
    frm.add_custom_button(__(doctype), function() {
        erpnext.utils.map_current_doc({
            method: method_path,
            source_doctype: doctype,
            target: frm,
            date_field: "posting_date",
            setters: {
                customer_name: frm.doc.customer_name,
                customer_address: frm.doc.customer_address
            },
            get_query_filters: {
                docstatus: 1,
                company: frm.doc.company,
            }
        })
    }, __("Get customers from"))
}


frappe.ui.form.on('Delivery Trip', {

    before_load: frm => {
        frm.events.clear_delivery_stop_for_new_delivery_trip(frm);
    },

    refresh: frm => {
        
        if (frm.doc.docstatus == 0) {  
            frm.remove_custom_button(__('Delivery Note'), __("Get customers from"))
            frm.remove_custom_button(__('Sales Order'), __("Get customers from"))

            mapCurrentDoc(frm, "Sales Order", "sungas.api.delivery_trip.make_delivery_trip_from_sales_order")
            mapCurrentDoc(frm, 'Delivery Note', "sungas.api.delivery_trip.make_delivery_trip_")
        }
    },

    clear_delivery_stop_for_new_delivery_trip: frm => {
        if (frm.is_new()) {
            frm.doc.delivery_stops = [];
            frm.refresh_field('delivery_stops');
        }
    }
})