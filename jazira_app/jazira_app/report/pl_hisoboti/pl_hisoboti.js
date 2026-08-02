// Copyright (c) 2026, Jazira App and contributors
// For license information, please see license.txt

frappe.query_reports["PL Hisoboti"] = {
	"filters": [
		{
			"fieldname": "company",
			"label": __("Компания"),
			"fieldtype": "Link",
			"options": "Company",
			"default": frappe.defaults.get_user_default("Company"),
			"reqd": 1
		},
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
			"default": "Yearly",
			"reqd": 1
		}
	],

	// Sodda oq-qora dizayn: fon rangi yo'q, faqat asosiy (root/result/sub)
	// qatorlar bold, tafsilot qatorlari oddiy vazn bilan ajratiladi.
	tree: true,
	name_field: "label",
	initial_depth: 0,

	onload: function (report) {
		if (report.page.inner_toolbar.find(".btn-pl-hisoboti-pdf").length) return;
		report.page
			.add_inner_button(__("PDF"), function () {
				const filters = frappe.query_report.get_filter_values();
				if (!filters.company) {
					frappe.show_alert({ message: __("Аввал компанияни танланг"), indicator: "orange" });
					return;
				}
				if (!filters.from_date || !filters.to_date) {
					frappe.show_alert({ message: __("Аввал 'Дан' ва 'Гача' сanasini tanlang"), indicator: "orange" });
					return;
				}
				// Serverga fayl sifatida saqlanmaydi — to'g'ridan-to'g'ri
				// brauzerga "download" qilib yuboriladi.
				const url = "/api/method/jazira_app.jazira_app.report.pl_hisoboti.pl_hisoboti_pdf.generate_pl_pdf"
					+ "?filters=" + encodeURIComponent(JSON.stringify(filters));
				window.open(url);
			})
			.addClass("btn-pl-hisoboti-pdf");
	},

	"formatter": function (value, row, column, data, default_formatter) {
		const rt = data ? data.row_type : null;

		// ── Chap ustun (Кўрсаткич) — ierarxiya bo'yicha ajratilgan ──────────────
		if (column.fieldname === "label") {
			if (!data || rt === "divider") return "";
			const level = data.indent_level || 0;
			const pad = 6 + level * 22;
			let s = `padding-left:${pad}px;white-space:nowrap;color:#000;`;
			if (rt === "root") {
				s += "font-weight:700;text-transform:uppercase;letter-spacing:.3px;";
			} else if (rt === "result") {
				s += "font-weight:800;";
			} else if (rt === "sub") {
				s += "font-weight:600;";
			} else if (rt === "detail") {
				s += "font-size:12.5px;";
			} else if (rt === "percent" || rt === "ratio") {
				s += "font-style:italic;font-size:11.5px;";
			}
			const label = frappe.utils.escape_html(data.label || "");
			return `<div style="${s}">${label}</div>`;
		}

		// ── Qiymat ustunlari ────────────────────────────────────────────────────
		if (!data || rt === "divider") return "";
		if (value === null || value === undefined || value === "") return "";
		const num = flt(value);

		// Foiz qatorlari
		if (rt === "percent") {
			const v = Math.round(num);
			return `<span style="font-style:italic;font-weight:600;">${v}%</span>`;
		}

		// Nisbat (ўртача чек) — 2 xonali
		if (rt === "ratio") {
			const v = num.toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
			return `<span style="font-style:italic;">${v}</span>`;
		}

		// Oddiy summalar — kasrsiz (.00 yo'q), mingliklar probel bilan.
		// Avval yaxlitlanadi, keyin manfiy/musbatligi shundan aniqlanadi —
		// aks holda -0.24 kabi juda kichik qoldiqlar "(0)" bo'lib chalkash
		// ko'rinib qolardi.
		const rounded = Math.round(num);
		const w = (rt === "root" || rt === "result") ? 800 : (rt === "sub" ? 700 : 400);

		if (rounded < 0) {
			const absTxt = Math.abs(rounded).toLocaleString("ru-RU");
			return `<span style="font-weight:${w};">(${absTxt})</span>`;
		}
		return `<span style="font-weight:${w};">${rounded.toLocaleString("ru-RU")}</span>`;
	}
};
