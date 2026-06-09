app_name = "jazira_app"
app_title = "Jazira App"
app_publisher = "Abdulla Abdukulov"
app_description = "Jazira Custom App"
app_email = "abduqulovabdulla3108@gmail.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# =============================================================================
# FIXTURES
# =============================================================================
app_name = "jazira_app"
app_title = "Jazira App"
app_publisher = "Abdulla Abdukulov"
app_description = "Jazira Custom App"
app_email = "abduqulovabdulla3108@gmail.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# =============================================================================
# FIXTURES
# =============================================================================
fixtures = [
    {
        "dt": "Custom Field",
        "filters": [
            ["dt", "in", [
                "Sales Invoice",
                "Journal Entry",
                "Stock Entry",
                "Item",
                "BOM"
            ]],
            ["fieldname", "like", "custom_%"]
        ]
    },
    {
        "dt": "Property Setter",
        "filters": [
            ["doc_type", "in", [
                "Jazira App Daily Sales Import",
                "Sales Invoice",
                "Stock Entry",
                "POS Invoice"
            ]]
        ]
    },
    {
        "dt": "Party Type",
        "filters": [["party_type", "in", ["Расходы"]]]
    },
    {
        "dt": "Custom Field",
        "filters": [
            ["dt", "in", ["Employee", "Employee Checkin"]],
            ["fieldname", "in", [
                "hourly_rate",
                "dahua_event_id",
                "dahua_attendance_state",
                "checkin_source",
                "checkin_reason"
            ]]
        ]
    },
    {
        "dt": "Custom DocPerm",
        "filters": [
            ["parent", "=", "Employee"]
        ]
    }
]

after_migrate = [
    # "jazira_app.jazira_app.setup.kassa_setup.create_party_types",
    # "jazira_app.jazira_app.setup.manager_setup.run_manager_setup"
    # Har bir sozlama alohida try/except bilan chaqiriladi (bittasi xato bersa
    # ham qolganlari ishlaydi) — qarang setup/after_migrate.py
    "jazira_app.jazira_app.setup.after_migrate.run",
]

# Document Events
# ---------------
doc_events = {
    "POS Invoice": {
        # To'lov qilinganda (submit) URY Table occupied flagini tozalash
        # Counter-service model: stiker raqamlari qayta ishlatilishi uchun
        "on_submit": "jazira_app.jazira_app.overrides.pos_invoice.on_submit",
    },
    # Sales Order inter-company avtomatlashtirish ury app'ga ko'chirildi
    # (ury.ury.hooks.sklad_sales_order) — double-invoicing oldini olish uchun.
    "Sales Invoice": {
        # Amended inter-company SI: yangi narx hisoblash va PI amend qilish
        "validate": "jazira_app.overrides.sales_invoice.on_validate",
        "on_submit": "jazira_app.overrides.sales_invoice.on_submit",
    },
    "Purchase Order": {
        # Submit bo'lganda company guruhiga Telegram xabari yuboriladi,
        # cancel bo'lganda o'sha xabarga reply qilib "бекор қилинди" yuboriladi
        "on_submit": "jazira_app.jazira_app.overrides.purchase_order.on_submit",
        "on_cancel": "jazira_app.jazira_app.overrides.purchase_order.on_cancel",
    },
}
# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "jazira_app",
# 		"logo": "/assets/jazira_app/logo.png",
# 		"title": "Jazira App",
# 		"route": "/jazira_app",
# 		"has_permission": "jazira_app.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/jazira_app/css/jazira_app.css"
# app_include_js = "/assets/jazira_app/js/jazira_app.js"

# include js, css files in header of web template
# web_include_css = "/assets/jazira_app/css/jazira_app.css"
# web_include_js = "/assets/jazira_app/js/jazira_app.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "jazira_app/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {
    "Employee": "public/js/employee.js",
    "Purchase Invoice": "public/js/purchase_invoice_item_filter.js",
    "Purchase Order": "public/js/purchase_order_item_filter.js",
    "Sales Order": "public/js/sales_order_item_filter.js",
}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "jazira_app/public/icons.svg"

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

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "jazira_app.utils.jinja_methods",
# 	"filters": "jazira_app.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "jazira_app.install.before_install"
# after_install = "jazira_app.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "jazira_app.uninstall.before_uninstall"
# after_uninstall = "jazira_app.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "jazira_app.utils.before_app_install"
# after_app_install = "jazira_app.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "jazira_app.utils.before_app_uninstall"
# after_app_uninstall = "jazira_app.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "jazira_app.notifications.get_notification_config"

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

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"jazira_app.tasks.all"
# 	],
# 	"daily": [
# 		"jazira_app.tasks.daily"
# 	],
# 	"hourly": [
# 		"jazira_app.tasks.hourly"
# 	],
# 	"weekly": [
# 		"jazira_app.tasks.weekly"
# 	],
# 	"monthly": [
# 		"jazira_app.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "jazira_app.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "jazira_app.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "jazira_app.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["jazira_app.utils.before_request"]
# after_request = ["jazira_app.utils.after_request"]

# Job Events
# ----------
# before_job = ["jazira_app.utils.before_job"]
# after_job = ["jazira_app.utils.after_job"]

# User Data Protection
# --------------------

user_data_fields = [
    {
        "doctype": "{doctype_1}",
        "filter_by": "{filter_by}",
        "redact_fields": ["{field_1}", "{field_2}"],
        "partial": 1,
    },
]
# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"jazira_app.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []
