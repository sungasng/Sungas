from . import __version__ as app_version

app_name = "sungas"
app_title = "Sungas"
app_publisher = "Manqala"
app_description = "Bundled functionality for the Sungas Brand"
app_icon = "octicon octicon-file-directory"
app_email = "dev@manqala.com"
app_license = "Proprietary"

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/sungas/css/sungas.css"
# app_include_js = "/assets/sungas/js/sungas.js"

# include js, css files in header of web template
# web_include_css = "/assets/sungas/css/sungas.css"
# web_include_js = "/assets/sungas/js/sungas.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "sungas/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {
    "Repost Item Valuation": "public/js/repost_item_valuation.js",
    "Delivery Note": "public/js/delivery_note.js",
    "Delivery Trip": "public/js/delivery_trip.js",
}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Installation
# ------------

# before_install = "sungas.install.before_install"
# after_install = "sungas.install.after_install"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "sungas.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
permission_query_conditions = {
    "POS Opening Shift": "sungas.overrides.outlet_scope.pos_opening_shift_query",
    "POS Closing Shift": "sungas.overrides.outlet_scope.pos_closing_shift_query",
    "POS Invoice": "sungas.overrides.outlet_scope.pos_invoice_query",
}

has_permission = {
    "POS Opening Shift": "sungas.overrides.outlet_scope.pos_opening_shift_has_perm",
    "POS Closing Shift": "sungas.overrides.outlet_scope.pos_closing_shift_has_perm",
    "POS Invoice": "sungas.overrides.outlet_scope.pos_invoice_has_perm",
}

# (commented stub below kept intentionally for reference)
# _permission_query_conditions = {
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

override_doctype_class = {
    "Customer": "sungas.overrides.customer.CustomerOverride",
    "POS Invoice": "sungas.overrides.pos_invoice.POSInvoiceOverride"
}

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
    "Customer": {
        'validate': 'sungas.controllers.customer.validate_customer'
    },
    "Item": {
        'autoname': 'sungas.controllers.item.item_name',
    },
    "Sales Invoice": {
        'autoname': 'sungas.controllers.sales_invoice.autoname_sales_invoice',
        'on_submit': 'sungas.controllers.sales_invoice.validate_sales_invoice'
    },
    "Journal Entry": {
        'on_submit': 'sungas.controllers.journal_entry.submit_journal_entry'
    },
    "POS Closing Shift": {
        'before_submit': 'sungas.overrides.pos_closing_shift.validate_variance',
        'on_submit': 'sungas.overrides.pos_closing_shift.post_variance_journal',
    },
}

# Scheduled Tasks
# ---------------

scheduler_events = {
    "daily": [
        "sungas.scheduled_jobs.event_digest.send_event_digest",
    ],
}

# Testing
# -------

# before_tests = "sungas.install.before_tests"

# Overriding Methods
# ------------------------------
#
override_whitelisted_methods = {
    "erpnext.accounts.doctype.pos_invoice.pos_invoice.get_stock_availability": "sungas.overrides.pos_invoice.get_stock_availability"
}
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "sungas.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]


# User Data Protection
# --------------------

user_data_fields = [
    {
        "doctype": "{doctype_1}",
        "filter_by": "{filter_by}",
        "redact_fields": ["{field_1}", "{field_2}"],
        "partial": 1,
    },
    {
        "doctype": "{doctype_2}",
        "filter_by": "{filter_by}",
        "partial": 1,
    },
    {
        "doctype": "{doctype_3}",
        "strict": False,
    },
    {
        "doctype": "{doctype_4}"
    }
]


# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"sungas.auth.validate"
# ]

fixtures = [
    {
        "dt": "Custom Field",
        "filters": [
            ["dt", "in", [
                "Journal Entry",
                "POS Closing Shift"
            ]]
        ]
    },
    {
        "dt": "Custom DocPerm",
        "filters": [
            ["parent", "in", [
                "POS Closing Shift"
            ]],
            ["role", "in", [
                "LPG Head of Operations",
                "LPG Head of Finance",
                "LPG Head of Sales",
                "Accounts Manager",
                "System Manager"
            ]]
        ]
    },
    {
        "dt": "Role",
        "filters": [
            ["name", "in", [
                "LPG Head of Operations"
            ]]
        ]
    }
]
