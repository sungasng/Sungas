import frappe

no_cache = 1


def get_context(context):
    from sungas.approval_link import page_context

    context.no_cache = 1
    context.show_sidebar = False
    context.update(page_context(frappe.form_dict.get("t")))
    return context
