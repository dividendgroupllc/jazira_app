// Copyright (c) 2026, Jazira App and contributors
// For license information, please see license.txt

frappe.query_reports["Intercompany Sverka"] = {
    "filters": [
        {
            "fieldname": "from_date",
            "label": __("Сана дан"),
            "fieldtype": "Date",
            "default": frappe.datetime.month_start(),
            "reqd": 1
        },
        {
            "fieldname": "to_date",
            "label": __("Сана гача"),
            "fieldtype": "Date",
            "default": frappe.datetime.month_end(),
            "reqd": 1
        },
        {
            "fieldname": "seller",
            "label": __("Сотувчи компания"),
            "fieldtype": "Link",
            "options": "Company",
            "get_query": function () {
                return { filters: { is_group: 0 } };
            }
        },
        {
            "fieldname": "buyer",
            "label": __("Олувчи компания"),
            "fieldtype": "Link",
            "options": "Company",
            "get_query": function () {
                return { filters: { is_group: 0 } };
            }
        },
        {
            "fieldname": "only_differences",
            "label": __("Фақат фарқи борларини кўрсатиш"),
            "fieldtype": "Check",
            "default": 0
        }
    ],

    // Йўналиш -> ой -> жуфтсиз ҳужжат
    tree: true,
    name_field: "label",
    initial_depth: 1,

    "formatter": function (value, row, column, data, default_formatter) {
        const rt = data ? data.row_type : null;

        if (!data || rt === "divider") return "";

        // ── Чап устун ────────────────────────────────────────────────────
        if (column.fieldname === "label") {
            let s = "white-space:nowrap;color:var(--text-color);";
            if (rt === "root") {
                s += "font-weight:700;letter-spacing:.2px;";
            } else if (rt === "result") {
                s += "font-weight:800;text-transform:uppercase;";
            } else if (rt === "sub") {
                s += "font-weight:600;";
            } else if (rt === "detail") {
                s += "font-size:12.5px;";
            } else if (rt === "warn") {
                // Жуфтсиз ҳужжат — диққатни тортсин
                s += "font-size:12.5px;color:var(--alert-text-danger);";
            }

            return `<span style="${s}">${frappe.utils.escape_html(data.label || "")}</span>`;
        }

        // ── Ҳужжат устунлари — ном БОСИЛАДИГАН ҳавола ────────────────────
        if (column.fieldname === "sales_invoice" || column.fieldname === "purchase_invoice") {
            if (!value) return "";
            const doc = column.fieldname === "sales_invoice" ? data.si_doc : data.pi_doc;
            if (doc) {
                const dt = column.fieldname === "sales_invoice" ? "sales-invoice" : "purchase-invoice";
                const clr = rt === "warn" ? "var(--alert-text-danger)" : "var(--text-color)";
                return `<a href="/app/${dt}/${encodeURIComponent(doc)}" style="color:${clr};text-decoration:underline;font-size:12.5px;">${frappe.utils.escape_html(doc)}</a>`;
            }
            // Гуруҳ қатори — ҳужжатлар сони
            return `<span style="color:var(--text-muted);font-size:12px;">${frappe.utils.escape_html(String(value))}</span>`;
        }

        if (value === null || value === undefined || value === "") return "";
        const num = flt(value);

        const rounded = Math.round(num);
        const w = (rt === "root" || rt === "result") ? 800 : (rt === "sub" ? 600 : 400);

        // ── ФАРҚ устуни — 0 бўлса яшил белги, акс ҳолда қизил сумма ──────
        if (column.fieldname === "diff") {
            if (rounded === 0) {
                return `<span style="color:var(--text-muted);">—</span>`;
            }
            const txt = Math.abs(rounded).toLocaleString("ru-RU");
            const sign = rounded < 0 ? "−" : "+";
            return `<span style="font-weight:700;color:var(--alert-text-danger);">${sign}${txt}</span>`;
        }

        if (rounded < 0) {
            return `<span style="font-weight:${w};color:var(--alert-text-danger);">(${Math.abs(rounded).toLocaleString("ru-RU")})</span>`;
        }
        return `<span style="font-weight:${w};color:var(--text-color);">${rounded.toLocaleString("ru-RU")}</span>`;
    }
};
