// Copyright (c) 2026, Jazira App and contributors
// License: MIT

// PDF tugmasi — PL hisobotlaridagi bilan bir xil naqsh (izohlar o'sha yerda).
function jazira_balance_calculation_pdf_button(report) {
    if (!report || !report.page || !report.page.inner_toolbar) return;
    report.page.inner_toolbar.removeClass("hidden-xs hidden-md");
    if (report.page.inner_toolbar.find(".btn-balance-calculation-pdf").length) return;

    const $btn = report.page.add_inner_button(__("PDF"), function () {
        const filters = frappe.query_report.get_filter_values();
        if (!filters.from_date || !filters.to_date) {
            frappe.show_alert({ message: __("Аввал 'Дан' ва 'Гача' санасини танланг"), indicator: "orange" });
            return;
        }
        window.open("/api/method/jazira_app.jazira_app.report.balance_calculation.balance_calculation_pdf.generate_balance_calculation_pdf"
            + "?filters=" + encodeURIComponent(JSON.stringify(filters)));
    });
    if ($btn && $btn.addClass) $btn.addClass("btn-balance-calculation-pdf").addClass("btn-primary");
}

frappe.query_reports["Balance Calculation"] = {
    "filters": [
        {
            "fieldname": "from_date",
            "label": __("Дан"),
            "fieldtype": "Date",
            "default": frappe.datetime.year_start(),
            "reqd": 1
        },
        {
            "fieldname": "to_date",
            "label": __("Гача"),
            "fieldtype": "Date",
            "default": frappe.datetime.year_end(),
            "reqd": 1
        },
        {
            "fieldname": "periodicity",
            "label": __("Давр"),
            "fieldtype": "Select",
            "options": "Yearly\nHalf-Yearly\nQuarterly\nMonthly",
            "default": "Monthly",
            "reqd": 1
        }
    ],

    // Bo'lim -> kompaniya/kontragent kesimi
    tree: true,
    name_field: "label",
    initial_depth: 1,

    onload: function (report) {
        jazira_balance_calculation_pdf_button(report);
    },
    after_datatable_render: function () {
        jazira_balance_calculation_pdf_button(frappe.query_report);
    },

    "formatter": function (value, row, column, data, default_formatter) {
        const rt = data ? data.row_type : null;
        if (!data || rt === "divider") return "";

        if (column.fieldname === "label") {
            let s = "white-space:nowrap;color:var(--text-color);";
            if (rt === "root") {
                s += "font-weight:700;text-transform:uppercase;letter-spacing:.3px;";
            } else if (rt === "result") {
                s += "font-weight:800;";
            } else if (rt === "sub") {
                s += "font-weight:600;";
            } else if (rt === "detail") {
                s += "font-size:12.5px;";
            }
            return `<span style="${s}">${frappe.utils.escape_html(data.label || "")}</span>`;
        }

        if (value === null || value === undefined || value === "") return "";
        const num = flt(value);
        const rounded = Math.round(num);
        const w = (rt === "root" || rt === "result") ? 800 : (rt === "sub" ? 700 : 400);

        // РАЗНИЦА qatori: 0 — yashil belgi, aks holda qizil (muammo!)
        if (data.label && data.label.indexOf("РАЗНИЦА") === 0) {
            if (rounded === 0) return `<span style="color:var(--text-muted);">0 ✓</span>`;
            return `<span style="font-weight:800;color:var(--alert-text-danger);">${rounded.toLocaleString("ru-RU")} ✗</span>`;
        }

        if (rounded < 0) {
            return `<span style="font-weight:${w};color:var(--alert-text-danger);">(${Math.abs(rounded).toLocaleString("ru-RU")})</span>`;
        }
        return `<span style="font-weight:${w};color:var(--text-color);">${rounded.toLocaleString("ru-RU")}</span>`;
    }
};
