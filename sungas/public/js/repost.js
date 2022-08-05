frappe.ui.form.on("Repost Item Valuation",{
    refresh:frm=>{
       if(!frm.doc.__islocal){
            frm.add_custom_button("Repost",()=>{
                frappe.call({
                    args:{'doc':frm.doc.name},
                    method:'sungas.utils.utils.repost_entry',
                    callback:(r)=>{
                        frappe.show_alert({
                            indicator: 'green',
                            message: __('Repost Initiated')
                        });
                    }
                })
            })
       }
    }
})