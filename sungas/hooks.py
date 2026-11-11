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
    # Patch 0030: pre-filled price template download
    "LPG Bulk Price Upload": "public/js/lpg_bulk_price_upload.js",
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
    # Patch 0011b: ensure our canonical PR workflow is the only
    # active workflow on Purchase Receipt (defensive against the
    # stale DB workflow that outranked our fixture in 0011).
    "sungas.patches.v1.ensure_pr_workflow_active.execute",
    # Wave HF-1: early-warning that our governance fixtures actually
    # landed. Never throws -- just log_error if anything is missing so
    # that the next dev looking at Error Log sees the gap immediately.
    "sungas.utils.verify_governance_fixtures.run",
    # Patch 0020: role landing workspaces + module isolation.
    "sungas.workspaces.install",
    # Patch 0022: IFRS category defaults + backfill of blank items.
    "sungas.utils.ifrs_category.backfill",
    # Patch 0023: IOVC write-offs must post to an Expense account (8600), not 1609.
    "sungas.scheduled_jobs.variance_case_ageing.fix_iovc_writeoff_account",
    # Patch 0025: "No morning briefing" tick on User; service accounts ticked once.
    "sungas.scheduled_jobs.morning_briefing.ensure_skip_field",
    # Patch 0028: no automatic Item Price creation from typed rates.
    "sungas.overrides.price_edit_lock.ensure_no_auto_price_insert",
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
    # Patch 0028 -- selling prices change only via approved PCR / Bulk Upload.
    "LPG Outlet Price Tier": {
        'validate': 'sungas.overrides.price_edit_lock.block_direct_edit',
        'on_trash': 'sungas.overrides.price_edit_lock.block_direct_edit',
        # Patch 0031 -- live price signal to open tills.
        'on_update': 'sungas.overrides.price_edit_lock.broadcast_price_change',
    },
    "Item Price": {
        'validate': 'sungas.overrides.price_edit_lock.block_direct_edit',
        'on_trash': 'sungas.overrides.price_edit_lock.block_direct_edit',
        # Patch 0031 -- live price signal to open tills.
        'on_update': 'sungas.overrides.price_edit_lock.broadcast_price_change',
    },
    # Patch 0030 -- approved regional / national price replaces plant prices below it.
    "LPG Bulk Price Upload": {
        'on_submit': 'sungas.overrides.price_cascade.on_bulk_approved',
    },
    "LPG Price Change Request": {
        'on_submit': 'sungas.overrides.price_cascade.on_pcr_approved',
    },
    "Item": {
        'autoname': 'sungas.controllers.item.item_name',
        'validate': [
            'sungas.overrides.item_pricing_gate.require_tier_before_enable',
            # Patch 0022 -- IFRS category on every Item.
            'sungas.utils.ifrs_category.validate_item',
        ],
    },
    "Sales Invoice": {
        'autoname': 'sungas.controllers.sales_invoice.autoname_sales_invoice',
        'on_submit': 'sungas.controllers.sales_invoice.validate_sales_invoice',
        # Patch 0025 -- hard zero-price block on till (is_pos) invoices.
        'validate': 'sungas.overrides.zero_price_guard.block_zero_price',
        'before_submit': [
            'sungas.overrides.returns_approval_gate.require_manager_for_return',
            'sungas.overrides.fraud_freeze_gate.block_bank_payments_when_outlet_frozen',
        ],
    },
    "Journal Entry": {
        'on_submit': 'sungas.controllers.journal_entry.submit_journal_entry',
        # Patch 0016 -- cancelling a trip settlement JE re-opens the DLS.
        'on_cancel': 'sungas.overrides.haulage_costing.on_settlement_je_cancel',
    },
    # Patch 0016 -- IAS 2 standard haulage on GIT -> outlet receipt legs.
    "Stock Entry": {
        'before_validate': 'sungas.overrides.haulage_costing.apply_standard_haulage',
        # Patch 0019 -- a submitted receipt may complete its trip.
        'on_submit': 'sungas.overrides.trip_auto_close.on_stock_entry_submit',
    },
    "Daily Loading Schedule": {
        'validate': 'sungas.overrides.haulage_costing.validate_trip_haulage',
        'on_update': 'sungas.overrides.trip_auto_close.on_dls_update',
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
        # Patch 0025 -- hard zero-price block at the till.
        'validate': [
            'sungas.overrides.pos_invoice_seal.block_sale_on_sealed_shift',
            'sungas.overrides.zero_price_guard.block_zero_price',
        ],
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
        # Patch 0021 -- IAS 2 supplier inbound freight.
        'validate': 'sungas.overrides.inbound_freight.validate_inbound_freight',
        'before_cancel': 'sungas.overrides.inbound_freight.before_cancel_inbound_freight',
        'on_submit': [
            'sungas.overrides.inbound_freight.on_submit_inbound_freight',
            'sungas.overrides.receipt_trigger_review.review_on_receipt_submit',
            'sungas.overrides.pr_auto_draft_se.spawn_git_to_plant_se',
        ],
    },
    # Wave P-1: LPG + Non-LPG PO Approval Matrix.
    "Purchase Order": {
        'validate': 'sungas.overrides.purchase_order_matrix.classify_tier',
        'before_submit': 'sungas.overrides.purchase_order_matrix.enforce_tier_approvals',
    },
    # Patch 0013 (A) -- Transit Loss Write-Off HoF Gate: notify HoF when a
    # case flips to resolution=Written Off and is still unsigned.
    "Transit Loss Variance Case": {
        # Patch 0024 -- cases are opened by the outlet-receipt automation only.
        'before_insert': 'sungas.overrides.transit_loss_guard.require_system_opened',
        'on_update': 'sungas.overrides.transit_loss_hof_notify.notify_hof_on_writeoff_pending',
    },
    # Patch 0020 -- role landing workspace + sidebar module isolation.
    "User": {
        'validate': 'sungas.workspaces.apply_to_user',
    },
    # Patch 0018 -- in-app bell alerts.
    "ToDo": {
        'after_insert': 'sungas.utils.bell.on_todo_insert',
    },
    "*": {
        'on_update': 'sungas.utils.bell.on_workflow_change',
        'on_submit': 'sungas.utils.bell.on_workflow_change',
        'on_update_after_submit': 'sungas.utils.bell.on_workflow_change',
        'on_cancel': 'sungas.utils.bell.on_workflow_change',
    },
}

# Scheduled Tasks
# ---------------

scheduler_events = {
    "daily": [
        # Patch 0023 -- open TLVC / IOVC older than 13 days -> HoO + HoF.
        "sungas.scheduled_jobs.variance_case_ageing.run",
        "sungas.scheduled_jobs.event_digest.send_event_digest",
        # Patch 0013 (B) -- Governance fixture drift audit. Compares each
        # git-tracked fixture against a fresh DB export and logs any
        # mismatch (plus ToDos the System Manager). Read-only -- never
        # fixes drift, only reports it.
        "sungas.scheduled_jobs.fixture_drift_audit.run",
    ],
    # Wave P-2: GIT Ageing. Hourly. Opens ToDo on Draft Material Receipt
    # SEs that have been sitting in GIT past Sungas Procurement Policy
    # git_stale_hours (default 72). Idempotent via existing-Open-ToDo
    # check so re-runs are safe.
    "hourly": [
        "sungas.scheduled_jobs.git_ageing.run",
        # Patch 0019 -- close reconciled trips, flag trips open > 24h to HoO.
        "sungas.overrides.trip_auto_close.sweep",
    ],
    # Wave D-2: Open Shift Age escalation. Runs 07:00 UTC = 08:00 WAT (before
    # shop open) so it never overlaps with POS load. Single indexed query per
    # day, idempotent via escalation_level_sent on POS Opening Shift.
    "monthly": [
        # Patch 0021 -- draft own-truck freight true-up for last month.
        "sungas.overrides.inbound_freight.month_end_fleet_true_up",
    ],
    "cron": {
        "0 7 * * *": [
            "sungas.scheduled_jobs.shift_age_escalation.run",
            # Patch 0024 -- 7 AM manager morning briefing (bell + email).
            "sungas.scheduled_jobs.morning_briefing.run",
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

# Governance fixtures -- Patch 0027 aligned with live (live wins). Run
# `python3 scripts/build_patch_0027_align.py` (agent) or `bench export-fixtures --app sungas`.
# Governance fixtures -- Patch 0027 aligned with live (live wins). Run
# `python3 scripts/build_patch_0027_align.py` (agent) or `bench export-fixtures --app sungas`.
fixtures = [
    {
        "dt": "Custom Field",
        "or_filters": [
            [
                "dt",
                "in",
                [
                    "Company",
                    "Customer",
                    "Customer Asset Custody",
                    "Daily Loading Schedule",
                    "Employee Advance",
                    "Expense Claim",
                    "Inter-Outlet Standing Agreement",
                    "Inter-Outlet Variance Case",
                    "Item",
                    "Item Group",
                    "Journal Entry",
                    "Material Request",
                    "Payment Entry",
                    "POS Closing Shift",
                    "POS Invoice",
                    "POS Opening Shift",
                    "POS Profile",
                    "Purchase Invoice",
                    "Purchase Order",
                    "Purchase Receipt",
                    "Stock Entry",
                    "Sungas Close Policy",
                    "Sungas Procurement Policy",
                    "Transit Loss Variance Case",
                    "Warehouse"
                ]
            ],
            [
                "name",
                "in",
                [
                    "Bank-bank_category",
                    "Bank-nibss_code",
                    "Employee-custom_role_key",
                    "Employee-custom_role_key_col_break",
                    "Employee-custom_role_notes",
                    "Employee-eligible_for_13th_month",
                    "Employee-grade_level",
                    "Employee-hmo_column_break",
                    "Employee-hmo_coverage_type",
                    "Employee-hmo_monthly_premium_company_paid",
                    "Employee-hmo_monthly_topup_staff_paid",
                    "Employee-hmo_plan_name",
                    "Employee-hmo_section_break",
                    "Employee-lmd_role_section",
                    "Employee-rent_paid_annually",
                    "Employee-state_of_residence",
                    "Leave Application-workflow_state",
                    "Payroll Entry-workflow_state",
                    "Purchase Receipt Item-source_weighbridge_qty",
                    "Purchase Receipt Item-supplier_shortload_qty",
                    "Purchase Receipt Item-waybill_line_qty",
                    "Purchase Receipt Item-weighbridge_ticket_number",
                    "Sales Invoice-place_of_supply",
                    "Sales Order-custom_lmd_delivered_at",
                    "Sales Order-custom_lmd_order_code",
                    "Sales Order-custom_lmd_payment_status",
                    "Sales Order-custom_lmd_status",
                    "Sales Order-custom_lmd_track_url",
                    "Sales Order-custom_lmd_track_url_internal",
                    "Sales Order-lmd_column_break",
                    "Sales Order-lmd_section_break"
                ]
            ]
        ]
    },
    {
        "dt": "Custom DocPerm",
        "filters": [
            [
                "role",
                "in",
                [
                    "Academics User",
                    "Accounts Manager",
                    "Accounts User",
                    "Administrator",
                    "Agent",
                    "Agent Manager",
                    "All",
                    "Auditor",
                    "COO",
                    "Delivery Manager",
                    "Delivery User",
                    "Desk User",
                    "Employee",
                    "Employee Self Service",
                    "Expense Approver",
                    "Fleet Manager",
                    "Fulfillment User",
                    "HD Customer",
                    "HD Customer Manager",
                    "HR Manager",
                    "HR User",
                    "Inbox User",
                    "Internal Control",
                    "Item Manager",
                    "LPG Head of Finance",
                    "LPG Head of Operations",
                    "LPG Head of Sales",
                    "LPG POS User",
                    "LPG Plant Manager",
                    "Leave Approver",
                    "Maintenance Manager",
                    "Maintenance User",
                    "Manufacturing Manager",
                    "Manufacturing User",
                    "Projects Manager",
                    "Projects User",
                    "Purchase Manager",
                    "Purchase Master Manager",
                    "Purchase User",
                    "Quality Manager",
                    "Sales Manager",
                    "Sales Master Manager",
                    "Sales User",
                    "Stock Manager",
                    "Stock User",
                    "Support Team",
                    "System Manager",
                    "Website Manager"
                ]
            ],
            [
                "parent",
                "in",
                [
                    "Account",
                    "Activity Type",
                    "Additional Salary",
                    "Address",
                    "Assignment Rule",
                    "Attendance",
                    "Attendance Request",
                    "Bin",
                    "Branch",
                    "Comment",
                    "Communication",
                    "Company",
                    "Compensatory Leave Request",
                    "Contact",
                    "Cost Center",
                    "Country",
                    "Currency",
                    "Customer",
                    "Daily Loading Schedule",
                    "Delivery Trip",
                    "Department",
                    "Designation",
                    "DocType",
                    "Email Account",
                    "Email Template",
                    "Employee",
                    "Employee Advance",
                    "Employee Benefit Application",
                    "Employee Checkin",
                    "Employee Grade",
                    "Employee Grievance",
                    "Employee Health Insurance",
                    "Employee Referral",
                    "Employee Tax Exemption Category",
                    "Employee Tax Exemption Declaration",
                    "Employee Tax Exemption Proof Submission",
                    "Employee Tax Exemption Sub Category",
                    "Employment Type",
                    "Expense Claim",
                    "Expense Claim Type",
                    "File",
                    "Finance Book",
                    "Gender",
                    "Grievance Type",
                    "HD Ticket",
                    "Holiday List",
                    "Identification Document Type",
                    "Inter-Outlet Variance Case",
                    "Job Applicant",
                    "Journal Entry",
                    "LPG Outlet Price Tier",
                    "LPG Price Change Request",
                    "Leave Allocation",
                    "Leave Application",
                    "Leave Type",
                    "Letter Head",
                    "Mode of Payment",
                    "POS Closing Shift",
                    "POS Invoice",
                    "POS Opening Shift",
                    "Payment Terms Template",
                    "Payroll Entry",
                    "Payroll Period",
                    "Project",
                    "Purchase Order",
                    "Purchase Receipt",
                    "Purpose of Travel",
                    "Role",
                    "Salary Component",
                    "Salary Slip",
                    "Salary Structure",
                    "Salary Withholding",
                    "Sales Invoice",
                    "Salutation",
                    "Shift Request",
                    "Shift Type",
                    "Stock Entry",
                    "Sungas Region",
                    "Supplier",
                    "Supplier Depot Mapping",
                    "Task",
                    "Terms and Conditions",
                    "Timesheet",
                    "Training Event",
                    "Training Feedback",
                    "Training Program",
                    "Transit Loss Variance Case",
                    "Travel Request",
                    "User",
                    "User Invitation",
                    "Vehicle Log",
                    "Warehouse",
                    "Website Settings"
                ]
            ]
        ]
    },
    {
        "dt": "Property Setter",
        "or_filters": [
            [
                "doc_type",
                "in",
                [
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
                    "Stock Entry",
                    "Inter-Outlet Variance Case",
                    "Transit Loss Variance Case"
                ]
            ],
            [
                "name",
                "in",
                [
                    "Budget-budget_against-options",
                    "Contact-main-search_fields",
                    "Destination Allocation-destination_outlet-ignore_user_permissions",
                    "LPG Outlet Price Tier-main-allow_import",
                    "Material Request Item-from_warehouse-ignore_user_permissions",
                    "Purchase Receipt Item-cost_center-default",
                    "Purchase Receipt Item-warehouse-default",
                    "Purchase Receipt Item-warehouse-read_only",
                    "Sales Invoice-tax_id-label",
                    "Stock Entry Detail-s_warehouse-ignore_user_permissions",
                    "Stock Entry Detail-t_warehouse-ignore_user_permissions"
                ]
            ]
        ]
    },
    {
        "dt": "Role",
        "filters": [
            [
                "name",
                "in",
                [
                    "LPG POS User",
                    "LPG Plant Manager",
                    "LPG Head of Operations",
                    "LPG Head of Finance",
                    "LPG Head of Sales",
                    "Accounts Manager",
                    "Purchase Manager",
                    "Sales User",
                    "Stock User",
                    "COO",
                    "Internal Control",
                    "LPG Deputy Head of Sales",
                    "LPG Head of HR",
                    "LPG Sales Executive"
                ]
            ]
        ]
    },
    {
        "dt": "Client Script",
        "filters": [
            [
                "name",
                "in",
                [
                    "Inter-Outlet Variance Auto-Calc",
                    "PR Discharge Dashboard",
                    "PR Get-Items Remaining Qty Hint",
                    "PR Hide Close Menu",
                    "PR User Stamps on Workflow",
                    "PR Variance Auto-Calc",
                    "PR Weighbridge Live Preview",
                    "Sungas - Cashier Customer Restrictions",
                    "Sungas DLS — Drop Table Guards",
                    "Sungas MR — Client Enhancements",
                    "Sungas SE — Material Transfer Auto-populate",
                    "PR - GIT Suppliers Cost Center Auto-populate",
                    "Transit Loss HoF Write-Off UI",
                    "PO Approval Matrix UI",
                    "IOVC HoF Write-Off Gate UI",
                    "DLS Force Close Trip UI",
                    "DLS Haulage Costing UI",
                    "SE Auto-Fill From User And PR"
                ]
            ]
        ]
    },
    {
        "dt": "Dashboard",
        "filters": [
            [
                "name",
                "in",
                [
                    "Transit Loss"
                ]
            ]
        ]
    },
    {
        "dt": "Dashboard Chart",
        "filters": [
            [
                "name",
                "in",
                [
                    "Transit Loss by Hauler (90d)",
                    "Transit Loss by Outlet (90d)",
                    "Transit Loss by In-House Driver (90d)",
                    "Transit Loss Trend (12mo)",
                    "Held Qty per Supplier",
                    "Sungas Ops · Tank Volume by Outlet"
                ]
            ]
        ]
    },
    {
        "dt": "Number Card",
        "filters": [
            [
                "name",
                "in",
                [
                    "Transit Loss — Open Cases (90d)",
                    "Transit Loss — Hauler Liable (90d)",
                    "Transit Loss — Written Off (90d)",
                    "LPG in Supplier GIT (kg)",
                    "Oldest Supplier-Held PR (days)",
                    "Total Supplier-Held Qty (kg)",
                    "Sungas Ops · Draft Loading Schedules",
                    "Sungas Ops · Emergency Overrides This Month",
                    "Sungas Ops · GIT Inter-Outlet",
                    "Sungas Ops · GIT Supplier to Outlet",
                    "Sungas Ops · Network Tank Volume",
                    "Sungas Ops · Open TLVC",
                    "Sungas Ops · Pending HoO Approvals",
                    "Sungas Ops · Post-Hoc Pending",
                    "Sungas Ops · Today's Dispatched",
                    "Sungas Ops · Trucks Pending Assignment"
                ]
            ]
        ]
    },
    {
        "dt": "Report",
        "filters": [
            [
                "name",
                "in",
                [
                    "Transit Loss Recovery Aging",
                    "IFRS Stock Classification",
                    "Inter-Outlet Transit Aging",
                    "PR Discharge Reconciliation"
                ]
            ]
        ]
    },
    {
        "dt": "Server Script",
        "filters": [
            [
                "name",
                "in",
                [
                    "Sungas POS Close · variance_amount Backfill",
                    "Sungas POS Close · Block-Tier Auto-Route",
                    "Sungas - Block Customer Edits By Cashier",
                    "Sungas - Force Retail Group On Customer Insert",
                    "Sungas SE — Material Receipt Guard",
                    "Sungas SE — Auto Accounting Dimensions",
                    "Sungas SE — Row-Level Permission (PM outlet scope)",
                    "SE Inter-Outlet SoD Guard",
                    "SE Inter-Outlet SoD Guard V2",
                    "SE Single-Drop Spawn",
                    "SE Multi-Drop Spawn",
                    "SE Sync PR Discharge Totals",
                    "SE Sync PR Discharge Totals On Cancel",
                    "MR Auto-Approve Rules",
                    "MR Attach To Loading Schedule",
                    "Sungas MR — Auto Status On Receipt",
                    "Sungas MR — Share With Source PM",
                    "Sungas MR — Auto Accounting Dimensions",
                    "Sungas MR — Row-Level Permission (PM outlet scope)",
                    "Sungas DLS — Drop Integrity Guard",
                    "Sungas DLS — Row-Level Permission (PM outlet scope)",
                    "DLS Dispatch → Outward SE Spawn",
                    "LS Capacity Check",
                    "LS Truck-Return Guard",
                    "Outlet SE Open Transit Loss Case",
                    "Transit Loss Case Resolve",
                    "Inter-Outlet Open Variance Case on Receipt",
                    "Inter-Outlet Variance Case Resolve",
                    "Inter-Outlet Variance Enforce",
                    "Inter-Outlet Auto-Receipt and Notify",
                    "Inter-Outlet Clear COGS Expense",
                    "SE Transit Posting-Time Collision Guard",
                    "IOVC Workflow Auto-Stamp Sign-Offs",
                    "GIT Aged Stock Daily Alert",
                    "LMD MR Append Note",
                    "LMD MR Approve",
                    "LMD MR PostHoc Signoff",
                    "LMD MR Reject",
                    "LMD SE Confirm Receipt",
                    "lmd_designation_role_sync",
                    "PR Auto-Route to Supplier GIT",
                    "PR Auto-Spawn Outlet Receipt SE",
                    "PR Close Reconcile",
                    "PR Guard Qty From Plant Manager Edit",
                    "PR Notify On Submit",
                    "PR Validate Final Destination",
                    "PR Weighbridge Auto-Reconcile",
                    "TLVC Auto-Sign HOD Ops"
                ]
            ]
        ]
    },
    {
        "dt": "Workflow",
        "filters": [
            [
                "name",
                "in",
                [
                    "POS Closing Shift Variance",
                    "Sungas Purchase Receipt Approval",
                    "Sungas Inter-Outlet Variance Approval",
                    "LPG Bulk Price Upload Approval",
                    "LPG Price Change Approval",
                    "Sungas Expense Claim Approval",
                    "Sungas Leave Approval",
                    "Sungas Payroll Approval",
                    "Sungas TLVC Approval"
                ]
            ]
        ]
    },
    {
        "dt": "Workflow State",
        "filters": [
            [
                "name",
                "in",
                [
                    "Draft",
                    "Pending Plant Manager",
                    "Pending HOD Operations",
                    "Pending HOD Finance",
                    "Pending COO",
                    "Approved",
                    "Rejected",
                    "HoO Approved",
                    "Submitted",
                    "Under Investigation",
                    "Pending HoF Approval",
                    "COO Review",
                    "HOD Ops Signed",
                    "HR Manager Review",
                    "Head of Finance Review",
                    "Internal Control Review",
                    "Line Manager Review",
                    "Pending Head of Finance",
                    "Pending Head of Sales"
                ]
            ]
        ]
    },
    {
        "dt": "Workflow Action Master",
        "filters": [
            [
                "name",
                "in",
                [
                    "Submit for Approval",
                    "Approve",
                    "Escalate to Finance",
                    "Reject",
                    "Reopen",
                    "Submit to Finance",
                    "Start Investigation",
                    "Request HoF Write-Off Approval",
                    "Approve & Submit",
                    "Forward to COO",
                    "Forward to HR",
                    "Forward to Head of Finance",
                    "Forward to Internal Control",
                    "HOD Ops Sign-off",
                    "Reject with Query",
                    "Resume Investigation",
                    "Submit"
                ]
            ]
        ]
    },
    {
        "dt": "Role Profile",
        "filters": [
            [
                "name",
                "in",
                [
                    "LPG Head of Finance",
                    "LPG Head of Sales",
                    "LPG Plant Manager",
                    "LPG POS User"
                ]
            ]
        ]
    },
    {
        "dt": "Print Format",
        "filters": [
            [
                "name",
                "in",
                [
                    "NTAA 2025 - Sungas SI",
                    "Sungas Payslip",
                    "Sungas Thermal 58mm"
                ]
            ]
        ]
    },
    {
        "dt": "DocType",
        "filters": [
            [
                "custom",
                "=",
                1
            ]
        ]
    }
]
