import frappe

no_cache = 1


def get_context(context):
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/fill"
        raise frappe.Redirect
    context.no_cache = 1
    context.show_sidebar = False
    context.user_name = frappe.db.get_value("User", frappe.session.user, "full_name") or frappe.session.user
    return context
