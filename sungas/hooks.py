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
    "POS Closing Shift": "public/js/pos_closing_shift.js",
    "Payroll Entry": "public/js/payroll_entry.js",
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

# Wave D-4: ensure cash_variance_pending_account is wired after fixtures
# sync (Custom Fields are installed AFTER patches.txt runs, so we drive the
# seed via after_migrate to avoid a "field-doesn't-exist-yet" silent drop).
# The seed function is idempotent, so it's safe to re-run on every migrate.
after_migrate = [
    "sungas.patches.v1.seed_cash_variance_pending_account.execute",
    # Wave HF-1: early-warning that our governance fixtures actually
    # landed. Never throws -- just log_error if anything is missing so
    # that the next dev looking at Error Log sees the gap immediately.
    "sungas.utils.verify_governance_fixtures.run",
]

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
        'validate': 'sungas.overrides.item_pricing_gate.require_tier_before_enable',
    },
    "Sales Invoice": {
        'autoname': 'sungas.controllers.sales_invoice.autoname_sales_invoice',
        'on_submit': 'sungas.controllers.sales_invoice.validate_sales_invoice',
        'before_submit': [
            'sungas.overrides.returns_approval_gate.require_manager_for_return',
            'sungas.overrides.fraud_freeze_gate.block_bank_payments_when_outlet_frozen',
        ],
    },
    "Journal Entry": {
        'on_submit': 'sungas.controllers.journal_entry.submit_journal_entry'
    },
    "POS Closing Shift": {
        'validate': 'sungas.overrides.pos_closing_shift.compute_variance_severity',
        'before_submit': [
            'sungas.overrides.pos_closing_shift.validate_variance',
            'sungas.overrides.pos_variance_investigation_integration.require_investigation_for_hard_variance',
        ],
        'on_submit': 'sungas.overrides.pos_closing_shift.post_variance_journal',
        'on_update': [
            'sungas.overrides.variance_sla.track_state_entry',
            'sungas.overrides.pos_closing_shift.post_provisional_journal',
            'sungas.overrides.pos_closing_shift.cancel_provisional_journal',
            'sungas.overrides.coo_notification.notify_coo_on_critical_approval',
            'sungas.overrides.pos_variance_investigation_integration.auto_create_variance_investigation',
        ],
    },
    "POS Invoice": {
        'before_insert': 'sungas.overrides.pos_invoice_seal.block_sale_on_sealed_shift',
        'validate': 'sungas.overrides.pos_invoice_seal.block_sale_on_sealed_shift',
        'before_submit': [
            'sungas.overrides.returns_approval_gate.require_manager_for_return',
            'sungas.overrides.fraud_freeze_gate.block_bank_payments_when_outlet_frozen',
        ],
    },
    "POS Opening Shift": {
        # Wave B-11: Cashier Lockout on Unresolved Variance.
        'before_insert': 'sungas.overrides.cashier_variance_lockout.enforce_cashier_variance_lockout',
    },
    "Purchase Receipt": {
        'on_submit': [
            'sungas.overrides.receipt_trigger_review.review_on_receipt_submit',
            'sungas.overrides.pr_auto_draft_se.spawn_git_to_plant_se',
        ],
    },
    # Wave P-1: LPG + Non-LPG PO Approval Matrix.
    "Purchase Order": {
        'validate': 'sungas.overrides.purchase_order_matrix.classify_tier',
        'before_submit': 'sungas.overrides.purchase_order_matrix.enforce_tier_approvals',
    },
}

# Scheduled Tasks
# ---------------

scheduler_events = {
    "daily": [
        "sungas.scheduled_jobs.event_digest.send_event_digest",
    ],
    # Wave P-2: GIT Ageing. Hourly. Opens ToDo on Draft Material Receipt
    # SEs that have been sitting in GIT past Sungas Procurement Policy
    # git_stale_hours (default 72). Idempotent via existing-Open-ToDo
    # check so re-runs are safe.
    "hourly": [
        "sungas.scheduled_jobs.git_ageing.run",
    ],
    # Wave D-2: Open Shift Age escalation. Runs 07:00 UTC = 08:00 WAT (before
    # shop open) so it never overlaps with POS load. Single indexed query per
    # day, idempotent via escalation_level_sent on POS Opening Shift.
    "cron": {
        "0 7 * * *": [
            "sungas.scheduled_jobs.shift_age_escalation.run",
        ],
        # Wave D-3: Variance approval SLA breach. Runs 08:30 UTC = 09:30 WAT,
        # 90 min after the open-shift cron. Single indexed query/day,
        # idempotent via variance_sla_escalation_level.
        "30 8 * * *": [
            "sungas.scheduled_jobs.variance_sla_breach.run",
        ],
        # Wave B-11: Monthly Escalation Digest. Runs 09:00 UTC on the 1st of
        # every month — emails HOD Ops + HOD Finance a summary of the prior
        # month's D-2/D-3 escalations + current backlog snapshot.
        "0 9 1 * *": [
            "sungas.scheduled_jobs.monthly_escalation_digest.run",
        ],
    },
}

# Testing
# -------

# before_tests = "sungas.install.before_tests"

# Overriding Methods
# ------------------------------
#
override_whitelisted_methods = {
    "erpnext.accounts.doctype.pos_invoice.pos_invoice.get_stock_availability": "sungas.overrides.pos_invoice.get_stock_availability",
    "posawesome.posawesome.doctype.pos_closing_shift.pos_closing_shift.submit_closing_shift": "sungas.overrides.pos_closing_shift_api.submit_closing_shift",
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
                "Company",
                "Customer",
                "Customer Asset Custody",
                "Daily Loading Schedule",
                "Inter-Outlet Standing Agreement",
                "Inter-Outlet Variance Case",
                "Item",
                "Journal Entry",
                "Material Request",
                "POS Closing Shift",
                "POS Invoice",
                "POS Opening Shift",
                "POS Profile",
                "Purchase Order",
                "Purchase Receipt",
                "Stock Entry",
                "Sungas Close Policy",
                "Sungas Procurement Policy",
                "Transit Loss Variance Case"
            ]]
        ]
    },
    {
        "dt": "Custom DocPerm",
        "filters": [
            ["parent", "in", [
                "POS Closing Shift",
                "Purchase Receipt"
            ]],
            ["role", "in", [
                "Stock User",
                "LPG Plant Manager",
                "LPG Head of Operations",
                "LPG Head of Finance",
                "LPG Head of Sales",
                "Accounts Manager",
                "System Manager"
            ]]
        ]
    },
    {
        "dt": "Property Setter",
        "filters": [
            ["doc_type", "in", [
                "Company",
                "Customer",
                "Daily Loading Schedule",
                "Item",
                "Material Request",
                "POS Closing Shift",
                "POS Invoice",
                "POS Opening Shift",
                "POS Profile",
                "Purchase Order",
                "Purchase Receipt",
                "Stock Entry"
            ]]
        ]
    },
    {
        "dt": "Role",
        "filters": [
            ["name", "in", [
                "LPG POS User",
                "LPG Plant Manager",
                "LPG Head of Operations",
                "LPG Head of Finance",
                "LPG Head of Sales",
                "Accounts Manager",
                "Purchase Manager",
                "Sales User",
                "Stock User"
            ]]
        ]
    },
    # Wave HF-2: extended coverage -- Client Scripts, Dashboards, Charts,
    # Cards and Reports that were previously DB-only.
    {
        "dt": "Client Script",
        "filters": [
            ["name", "in", [
                "Inter-Outlet Variance Auto-Calc",
                "PR Discharge Dashboard",
                "PR Get-Items Remaining Qty Hint",
                "PR Hide Close Menu",
                "PR User Stamps on Workflow",
                "PR Variance Auto-Calc",
                "PR Weighbridge Live Preview",
                "Sungas - Cashier Customer Restrictions",
                "Sungas DLS \u2014 Drop Table Guards",
                "Sungas MR \u2014 Client Enhancements",
                "Sungas SE \u2014 Material Transfer Auto-populate"
            ]]
        ]
    },
    {
        "dt": "Dashboard",
        "filters": [
            ["name", "in", [
                "Transit Loss"
            ]]
        ]
    },
    {
        "dt": "Dashboard Chart",
        "filters": [
            ["name", "in", [
                "Transit Loss by Hauler (90d)",
                "Transit Loss by Outlet (90d)",
                "Transit Loss by In-House Driver (90d)",
                "Transit Loss Trend (12mo)"
            ]]
        ]
    },
    {
        "dt": "Number Card",
        "filters": [
            ["name", "in", [
                "Transit Loss \u2014 Open Cases (90d)",
                "Transit Loss \u2014 Hauler Liable (90d)",
                "Transit Loss \u2014 Written Off (90d)"
            ]]
        ]
    },
    {
        "dt": "Report",
        "filters": [
            ["name", "in", [
                "Transit Loss Recovery Aging"
            ]]
        ]
    },
    # Wave HF-1: harden ERPNext-DB-resident governance artifacts into git.
    # Without these fixtures, a site rebuild would silently lose the
    # Sungas / SE / MR / DLS / LS server scripts, the POS Closing Shift
    # variance workflow, and every workflow state / action our approvers
    # rely on.
    {
        "dt": "Server Script",
        "filters": [
            ["name", "in", [
                # POS variance workflow
                "Sungas POS Close \u00b7 variance_amount Backfill",
                "Sungas POS Close \u00b7 Block-Tier Auto-Route",
                # Customer guards
                "Sungas - Block Customer Edits By Cashier",
                "Sungas - Force Retail Group On Customer Insert",
                # Stock Entry pack (inter-outlet, receipts, spawns, dims)
                "Sungas SE \u2014 Material Receipt Guard",
                "Sungas SE \u2014 Auto Accounting Dimensions",
                "Sungas SE \u2014 Row-Level Permission (PM outlet scope)",
                "SE Inter-Outlet SoD Guard",
                "SE Inter-Outlet SoD Guard V2",
                "SE Single-Drop Spawn",
                "SE Multi-Drop Spawn",
                "SE Sync PR Discharge Totals",
                "SE Sync PR Discharge Totals On Cancel",
                # Material Request pack (auto-approve, dims, permissions)
                "MR Auto-Approve Rules",
                "MR Attach To Loading Schedule",
                "Sungas MR \u2014 Auto Status On Receipt",
                "Sungas MR \u2014 Share With Source PM",
                "Sungas MR \u2014 Auto Accounting Dimensions",
                "Sungas MR \u2014 Row-Level Permission (PM outlet scope)",
                # Daily Loading Schedule pack
                "Sungas DLS \u2014 Drop Integrity Guard",
                "Sungas DLS \u2014 Row-Level Permission (PM outlet scope)",
                "DLS Dispatch \u2192 Outward SE Spawn",
                "LS Capacity Check",
                "LS Truck-Return Guard",
                # HF-2: Transit Loss subsystem
                "Outlet SE Open Transit Loss Case",
                "Transit Loss Case Resolve",
                # HF-2: Inter-Outlet Variance subsystem
                "Inter-Outlet Open Variance Case on Receipt",
                "Inter-Outlet Variance Case Resolve",
                "Inter-Outlet Variance Enforce",
                "Inter-Outlet Auto-Receipt and Notify",
                "Inter-Outlet Clear COGS Expense"
            ]]
        ]
    },
    {
        "dt": "Workflow",
        "filters": [
            ["name", "in", [
                "POS Closing Shift Variance",
                "Purchase Receipt Sungas"
            ]]
        ]
    },
    {
        "dt": "Workflow State",
        "filters": [
            ["name", "in", [
                "Draft",
                "Pending Plant Manager",
                "Pending HOD Operations",
                "Pending HOD Finance",
                "Pending COO",
                "Approved",
                "Rejected",
                "HoO Approved",
                "Submitted"
            ]]
        ]
    },
    {
        "dt": "Workflow Action Master",
        "filters": [
            ["name", "in", [
                "Submit for Approval",
                "Approve",
                "Escalate to Finance",
                "Reject",
                "Reopen",
                "Submit to Finance"
            ]]
        ]
    }
]
