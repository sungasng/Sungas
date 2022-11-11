from . import __version__ as app_version

app_name = "sungas"
app_title = "Sungas"
app_publisher = "Manqala"
app_description = "Bundled functionality for the Sungas Brand"
app_icon = "octicon octicon-file-directory"
app_color = "grey"
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
doctype_js = {"Repost Item Valuation" : "public/js/repost.js",
			  "Delivery Note":	"public/js/stock.js",
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
#	"Role": "home_page"
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
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Customer": {
		"validate": "sungas.utils.utils.validate_customer",
		# "on_cancel": "method",
		# "on_trash": "method"
	},
	"Item":{
		'autoname':'sungas.utils.utils.item_name',
	},
	"Sales Invoice":{
		'autoname':'sungas.utils.utils.autoname_sales_invoice',
		'on_submit':'sungas.utils.utils.validate_sales_invoice'
	},
	'Journal Entry':{
		'on_submit':"sungas.utils.utils.submit_je"
	}
}

# Scheduled Tasks
# ---------------

scheduler_events = {
# 	"all": [
# 		"sungas.tasks.all"
# 	],
	"daily": [
		"sungas.utils.utils.send_event_digest",
	],
# 	"hourly": [
# 		"sungas.tasks.hourly"
# 	],
# 	"weekly": [
# 		"sungas.tasks.weekly"
# 	]
# 	"monthly": [
# 		"sungas.tasks.monthly"
# 	]
}

# Testing
# -------

# before_tests = "sungas.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "sungas.event.get_events"
# }
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
	{"dt":"Custom Field", "filters": [
			["dt", "in", [
				"Journal Entry",
			]]
		]
	}
]
