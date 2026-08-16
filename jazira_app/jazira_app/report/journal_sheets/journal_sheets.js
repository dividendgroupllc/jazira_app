frappe.query_reports["Journal Sheets"] = {
    "filters": [
        {
            "fieldname": "from_date",
            "label": __("Сана дан"),
            "fieldtype": "Date",
            "default": frappe.datetime.add_months(frappe.datetime.get_today(), -1),
            "reqd": 1
        },
        {
            "fieldname": "to_date",
            "label": __("Сана гача"),
            "fieldtype": "Date",
            "default": frappe.datetime.get_today(),
            "reqd": 1
        },
        {
            "fieldname": "company",
            "label": __("Компания"),
            "fieldtype": "Link",
            "options": "Company",
            "default": frappe.defaults.get_user_default("Company")
        },
        {
            "fieldname": "voucher_type",
            "label": __("Ҳужжат тури"),
            "fieldtype": "Select",
            "options": "\nJournal Entry\nOpening Entry\nBank Entry\nCash Entry\nCredit Card Entry\nDebit Note\nCredit Note\nContra Entry\nExcise Entry\nWrite Off Entry\nDepreciation Entry\nExchange Rate Revaluation"
        },
        {
            "fieldname": "account",
            "label": __("Счёт"),
            "fieldtype": "Link",
            "options": "Account",
            "get_query": function () {
                const company = frappe.query_report.get_filter_value("company");
                return { filters: company ? { company: company, is_group: 0 } : { is_group: 0 } };
            }
        },
        {
            "fieldname": "party_type",
            "label": __("Контрагент тури"),
            "fieldtype": "Link",
            "options": "Party Type"
        },
        {
            "fieldname": "party",
            "label": __("Контрагент"),
            "fieldtype": "Dynamic Link",
            "get_options": function () {
                return frappe.query_report.get_filter_value("party_type");
            }
        },
        {
            "fieldname": "cost_center",
            "label": __("Харажат маркази"),
            "fieldtype": "Link",
            "options": "Cost Center",
            "get_query": function () {
                const company = frappe.query_report.get_filter_value("company");
                return { filters: company ? { company: company, is_group: 0 } : { is_group: 0 } };
            }
        },
        {
            "fieldname": "remarks",
            "label": __("Изоҳ бўйича қидириш"),
            "fieldtype": "Data"
        }
    ],

    "formatter": function (value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);
        // "ЖАМИ" qatorini qalin qilib ko'rsatish
        if (data && data.is_total) {
            value = `<b>${value}</b>`;
        }
        return value;
    }
}
