// Copyright (c) 2026, Jazira App and contributors
// For license information, please see license.txt

// PDF tugmasi.
//
// Frappe'ning add_inner_button() bir xil yorliqli tugma allaqachon bo'lsa
// YANGI handler bog'lamaydi — shunchaki eskisini qaytaradi. Bundan tashqari
// Frappe onload'dan keyin ham inner toolbar'ni tozalashi mumkin, shunda
// tugma yo'qolib qoladi. Shuning uchun tugma ikkita nuqtada — onload'da va
// jadval chizilgandan keyin — qayta qo'yiladi. Qo'yish idempotent: o'z
// belgisi (btn-pl-obshi-pdf) bo'lsa qaytadan qo'shilmaydi.
function jazira_pl_obshi_pdf_button(report) {
	if (!report || !report.page || !report.page.inner_toolbar) return;

	// Frappe'ning page.html'ida inner toolbar shunday e'lon qilingan:
	//     <div class="custom-actions hide hidden-xs hidden-md">
	// va .hidden-md 992px dan TOR oynada uni butunlay yashiradi. Ya'ni
	// tugma qo'shilgan bo'lsa ham ko'rinmay qolardi. Hisobot desktop uchun
	// mo'ljallangani sababli shu yashirishni bekor qilamiz.
	report.page.inner_toolbar.removeClass("hidden-xs hidden-md");

	if (report.page.inner_toolbar.find(".btn-pl-obshi-pdf").length) return;

	const $btn = report.page.add_inner_button(__("PDF"), function () {
		const filters = frappe.query_report.get_filter_values();
		if (!filters.from_date || !filters.to_date) {
			frappe.show_alert({ message: __("Аввал 'Дан' ва 'Гача' санасини танланг"), indicator: "orange" });
			return;
		}
		// PDF serverda saqlanmaydi — to'g'ridan-to'g'ri yuklab olinadi.
		window.open("/api/method/jazira_app.jazira_app.report.pl_obshi.pl_obshi_pdf.generate_pl_obshi_pdf"
			+ "?filters=" + encodeURIComponent(JSON.stringify(filters)));
	});

	if ($btn && $btn.addClass) $btn.addClass("btn-pl-obshi-pdf").addClass("btn-primary");
}

frappe.query_reports["PL Obshi"] = {
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
		},
		{
			"fieldname": "add_back_owner_salary",
			"label": __("Эгалар маошини фойдага қайтариб қўшиш"),
			"fieldtype": "Check",
			"default": 1
		},
		{
			"fieldname": "eliminate_internal",
			"label": __("Ички айланмани чиқариб ташлаш"),
			"fieldtype": "Check",
			"default": 1
		}
	],

	// Qatorlar yoyiladi: 0-daraja jami, 1-daraja kompaniya kesimi,
	// 2-daraja hisob (schet) tafsiloti.
	tree: true,
	name_field: "label",
	initial_depth: 1,

	onload: function (report) {
		jazira_pl_obshi_pdf_button(report);
	},

	// Jadval har chizilganda tugma joyidaligi qayta tekshiriladi.
	after_datatable_render: function () {
		jazira_pl_obshi_pdf_button(frappe.query_report);
	},

	"formatter": function (value, row, column, data, default_formatter) {
		const rt = data ? data.row_type : null;

		// ── Chap ustun (Кўрсаткич) ──────────────────────────────────────────
		if (column.fieldname === "label") {
			if (!data || rt === "divider") return "";
			// Rang qattiq kodlanmaydi — Frappe temasi o'zgaruvchisi ishlatiladi,
			// shunda light va dark rejimda ham o'qiladi.
			let s = "white-space:nowrap;color:var(--text-color);";
			if (rt === "root") {
				s += "font-weight:700;text-transform:uppercase;letter-spacing:.3px;";
			} else if (rt === "result") {
				s += "font-weight:800;";
			} else if (rt === "sub") {
				s += "font-weight:600;";
			} else if (rt === "detail") {
				s += "font-size:12.5px;";
			} else if (rt === "percent") {
				s += "font-style:italic;font-size:11.5px;color:var(--text-muted);";
			}
			const label = frappe.utils.escape_html(data.label || "");
			return `<span style="${s}">${label}</span>`;
		}

		// ── Qiymat ustunlari ────────────────────────────────────────────────
		if (!data || rt === "divider") return "";
		if (value === null || value === undefined || value === "") return "";
		const num = flt(value);

		if (rt === "percent") {
			return `<span style="font-style:italic;font-weight:600;color:var(--text-muted);">${Math.round(num)}%</span>`;
		}

		// Summalar kasrsiz, mingliklar probel bilan. Avval yaxlitlanadi —
		// aks holda -0.24 kabi qoldiqlar "(0)" bo'lib chalkash ko'rinardi.
		const rounded = Math.round(num);
		const w = (rt === "root" || rt === "result") ? 800 : (rt === "sub" ? 700 : 400);

		if (rounded < 0) {
			const absTxt = Math.abs(rounded).toLocaleString("ru-RU");
			return `<span style="font-weight:${w};color:var(--alert-text-danger);">(${absTxt})</span>`;
		}
		return `<span style="font-weight:${w};color:var(--text-color);">${rounded.toLocaleString("ru-RU")}</span>`;
	}
};
