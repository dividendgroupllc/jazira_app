// Jazira — biznes paneli (savdo · tovarlar · filiallar · moliya · buxgalteriya)
//
// IIFE ichida: Frappe sahifa skriptlarini global kontekstda eval qiladi.
// Bu yerda hisob-kitob YO'Q — frontend faqat ko'rsatadi.
(function () {
	const API = "jazira_app.jazira_app.page.jazira_dashboard.jazira_dashboard";

	// Har tab qaysi bo'limlarni talab qiladi — faqat kerakli yuklanadi
	const TABS = [
		{ id: "overview", label: __("Обзор"), sections: ["health", "kpi", "daily", "companies", "products"] },
		{ id: "sales", label: __("Савдо"), sections: ["daily", "weekdays", "best_days", "monthly"] },
		{ id: "products", label: __("Товарлар"), sections: ["products", "categories"] },
		{ id: "branches", label: __("Филиаллар"), sections: ["companies", "company_products"] },
		{ id: "finance", label: __("Молия"), sections: ["pnl", "expenses", "monthly", "owners"] },
		{ id: "accounting", label: __("Бухгалтерия"), sections: ["cash", "health"] },
	];

	// ── Formatlash ───────────────────────────────────────────────────────
	function exact(v) {
		if (v === null || v === undefined || v === "") return "—";
		const r = Math.round(Number(v) || 0);
		const t = Math.abs(r).toLocaleString("ru-RU");
		return r < 0 ? `(${t})` : t;
	}
	function compact(v) {
		if (v === null || v === undefined || v === "") return "—";
		const n = Number(v) || 0, a = Math.abs(n);
		let t;
		if (a >= 1e9) t = (a / 1e9).toFixed(2) + " млрд";
		else if (a >= 1e6) t = (a / 1e6).toFixed(a >= 1e8 ? 0 : 1) + " млн";
		else if (a >= 1e3) t = Math.round(a / 1e3) + " минг";
		else t = Math.round(a).toLocaleString("ru-RU");
		return n < 0 ? `(${t})` : t;
	}
	function money(v) {
		if (v === null || v === undefined || v === "") return `<span class="jzd-num">—</span>`;
		return `<span class="jzd-num ${(Number(v) || 0) < 0 ? "jzd-neg" : ""}" title="${exact(v)} UZS">${compact(v)}</span>`;
	}
	function qty(v) {
		if (v === null || v === undefined) return "—";
		return `<span class="jzd-num">${Math.round(Number(v) || 0).toLocaleString("ru-RU")}</span>`;
	}
	function pct(v, d) {
		if (v === null || v === undefined || isNaN(v)) return "—";
		return Number(v).toFixed(d === undefined ? 1 : d) + "%";
	}
	function esc(s) {
		return frappe.utils.escape_html(s === null || s === undefined ? "" : String(s));
	}
	function tone(name, fb) {
		const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
		return v || fb;
	}
	const ICON = {
		up: '<svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true"><path d="M6 2.5 10 8H2z" fill="currentColor"/></svg>',
		down: '<svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true"><path d="M6 9.5 2 4h8z" fill="currentColor"/></svg>',
		refresh: '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M13.6 8a5.6 5.6 0 1 1-1.7-4M13.5 2v3.5H10" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
		info: '<svg viewBox="0 0 14 14" width="12" height="12" aria-hidden="true"><circle cx="7" cy="7" r="5.6" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M7 6.2v3.4M7 4.3v.9" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
		alert: '<svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true"><path d="M8 2.2 14.6 13H1.4z" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><path d="M8 6.4v3M8 11.2v.8" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>',
		check: '<svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true"><path d="M3.2 8.4 6.4 11.6 12.8 4.8" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
		arrow: '<svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true"><path d="M4 2.5 7.5 6 4 9.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
	};
	function tip(text) {
		if (!text) return "";
		return `<span class="jzd-tip" tabindex="0" role="button" aria-label="${esc(text)}" data-tip="${esc(text)}">${ICON.info}</span>`;
	}
	// Δ: `invert` — xarajat kabi ko'rsatkichlar uchun (o'sish yomon)
	function delta(p, abs, invert, unit) {
		let up, body;
		if (p !== null && p !== undefined && !isNaN(p)) { up = p >= 0; body = pct(Math.abs(p)); }
		else if (abs !== null && abs !== undefined && abs !== 0) {
			up = abs >= 0; body = unit === "pp" ? Math.abs(abs).toFixed(1) + " п.п." : compact(Math.abs(abs));
		} else return `<span class="jzd-delta jzd-flat">—</span>`;
		const good = invert ? !up : up;
		return `<span class="jzd-delta ${good ? "jzd-up" : "jzd-down"}">${up ? ICON.up : ICON.down}${body}</span>`;
	}
	function palette() {
		return [
			tone("--jzd-c1", "#3b7bd4"), tone("--jzd-c2", "#2f9e68"), tone("--jzd-c3", "#e0a020"),
			tone("--jzd-c4", "#7a5cc4"), tone("--jzd-c5", "#d9705b"), tone("--jzd-c6", "#3aa6b9"),
			tone("--jzd-c7", "#98a2b3"), tone("--jzd-c8", "#c76fb0"),
		];
	}

	// ═════════════════════════════════════════════════════════════════════
	class Dashboard {
		constructor(wrapper, page) {
			this.page = page;
			this.$root = $(page.main);   // TOZALANMAYDI — Frappe filtr paneli shu yerda
			this.charts = {};
			this._token = 0;
			this.data = {};
			this.tab = "overview";
			this.state = { scope: "all", preset: "last_month", from_date: null, to_date: null };
			this.view = { products: "amount", daily: "all", pnl: "table" };
			this.build_shell();
			this.boot();
		}

		call(method, args) {
			const token = ++this._token;
			return frappe.call({ method: `${API}.${method}`, args: args || {} })
				.then((r) => (token === this._token ? r.message : Promise.reject("stale")));
		}

		build_shell() {
			this.$root.find(".jazira-dashboard").remove();
			this.$root.append(`
				<div class="jazira-dashboard">
					<header class="jazira-header">
						<div class="jazira-header-id">
							<h1>Jazira Group</h1>
							<p class="jazira-header-sub"></p>
						</div>
						<div class="jazira-header-meta">
							<span class="jazira-updated"></span>
							<button class="jazira-refresh" type="button">${ICON.refresh}<span>${__("Янгилаш")}</span></button>
						</div>
					</header>
					<nav class="jazira-tabs" role="tablist"></nav>
					<div class="jazira-status"></div>
					<div class="jazira-body"></div>
				</div>`);
			this.$page = this.$root.find(".jazira-dashboard");
			this.$sub = this.$root.find(".jazira-header-sub");
			this.$updated = this.$root.find(".jazira-updated");
			this.$tabs = this.$root.find(".jazira-tabs");
			this.$status = this.$root.find(".jazira-status");
			this.$body = this.$root.find(".jazira-body");

			this.$tabs.html(TABS.map((t) =>
				`<button type="button" role="tab" data-tab="${t.id}">${esc(t.label)}</button>`).join(""));
			this.$tabs.on("click", "[data-tab]", (e) => this.show_tab($(e.currentTarget).data("tab")));
			this.$root.find(".jazira-refresh").on("click", () => this.reload(true));

			this.$page.on("mouseenter focus", ".jzd-tip", (e) => this.show_tip(e.currentTarget));
			this.$page.on("mouseleave blur", ".jzd-tip", () => this.hide_tip());
			this.$page.on("click", "[data-report]", (e) => this.drill($(e.currentTarget)));
		}

		show_tip(el) {
			this.hide_tip();
			const text = $(el).data("tip"); if (!text) return;
			const $t = $(`<div class="jazira-tooltip"></div>`).text(text).appendTo(document.body);
			const r = el.getBoundingClientRect(), w = $t.outerWidth();
			$t.css({ top: r.bottom + window.scrollY + 8,
				left: Math.max(12, Math.min(r.left + window.scrollX + r.width / 2 - w / 2, window.innerWidth - w - 12)) });
			this.$tip = $t;
		}
		hide_tip() { if (this.$tip) { this.$tip.remove(); this.$tip = null; } }

		boot() {
			this.skeleton();
			this.call("get_meta").then((meta) => {
				this.meta = meta;
				this.state.from_date = meta.default.from_date;
				this.state.to_date = meta.default.to_date;
				this.setup_filters();
				this.show_tab("overview");
			}).catch((e) => { if (e !== "stale") this.fatal(); });
		}

		fatal() {
			this.$body.html(`<div class="jazira-fatal"><div class="jazira-fatal-icon">${ICON.alert}</div>
				<h3>${__("Маълумотни юклаб бўлмади")}</h3><p>${__("Сервер жавоб бермади ёки хатолик юз берди.")}</p>
				<button type="button" class="jazira-btn jazira-btn-primary">${__("Қайта уриниш")}</button></div>`);
			this.$body.find("button").on("click", () => this.boot());
		}

		// ── Filtrlar (Frappe'ning o'z paneli) ──────────────────────────
		setup_filters() {
			const F = (this.F = {});
			const add = (df) => (F[df.fieldname] = this.page.add_field(df));
			add({ fieldname: "scope", label: __("Компания"), fieldtype: "Select", default: "all",
				options: [{ value: "all", label: __("Барча компаниялар") }]
					.concat((this.meta.companies || []).map((c) => ({ value: c.name, label: c.label }))),
				change: () => { this.state.scope = F.scope.get_value() || "all"; this.reload(); } });
			add({ fieldname: "preset", label: __("Давр"), fieldtype: "Select", default: "last_month",
				options: [
					{ value: "last_month", label: __("Ўтган ой") },
					{ value: "this_month", label: __("Жорий ой") },
					{ value: "last_7", label: __("Охирги 7 кун") },
					{ value: "last_30", label: __("Охирги 30 кун") },
					{ value: "last_90", label: __("Охирги 90 кун") },
					{ value: "custom", label: __("Қўлда") },
				], change: () => this.apply_preset() });
			add({ fieldname: "from_date", label: __("Дан"), fieldtype: "Date", change: () => this.manual_dates() });
			add({ fieldname: "to_date", label: __("Гача"), fieldtype: "Date", change: () => this.manual_dates() });
			F.from_date.set_input(this.state.from_date);
			F.to_date.set_input(this.state.to_date);
		}

		apply_preset() {
			const p = this.F.preset.get_value(); if (p === "custom") return;
			const today = frappe.datetime.get_today();
			let from, to;
			if (p === "last_month") { from = this.meta.default.from_date; to = this.meta.default.to_date; }
			else if (p === "this_month") { from = frappe.datetime.month_start(); to = frappe.datetime.month_end(); }
			else if (p === "last_7") { from = frappe.datetime.add_days(today, -6); to = today; }
			else if (p === "last_30") { from = frappe.datetime.add_days(today, -29); to = today; }
			else if (p === "last_90") { from = frappe.datetime.add_days(today, -89); to = today; }
			this.state.from_date = from; this.state.to_date = to;
			this.F.from_date.set_input(from); this.F.to_date.set_input(to);
			this.reload();
		}
		manual_dates() {
			const from = this.F.from_date.get_value(), to = this.F.to_date.get_value();
			if (!from || !to || (from === this.state.from_date && to === this.state.to_date)) return;
			this.state.from_date = from; this.state.to_date = to;
			if (this.F.preset.get_value() !== "custom") this.F.preset.set_input("custom");
			this.reload();
		}
		filters(refresh) {
			return { scope: this.state.scope, from_date: this.state.from_date,
				to_date: this.state.to_date, refresh: refresh ? 1 : 0 };
		}

		// ── Yuklash: faqat tab uchun kerakli bo'limlar ──────────────────
		reload(refresh) {
			this.data = {};
			this.show_tab(this.tab, refresh);
		}

		show_tab(id, refresh) {
			this.tab = id;
			this.$tabs.find("[data-tab]").removeClass("on").filter(`[data-tab="${id}"]`).addClass("on");
			const tab = TABS.find((t) => t.id === id);
			const missing = refresh ? tab.sections : tab.sections.filter((s) => !this.data[s]);
			this.hide_tip();
			if (!missing.length) return this.render_tab(id);
			this.skeleton();
			this.call("get_dashboard", {
				filters: JSON.stringify(this.filters(refresh)),
				sections: JSON.stringify(missing),
			}).then((d) => {
				Object.assign(this.data, d);
				this.ctx = d.context;
				this.render_tab(id);
				if (refresh) frappe.show_alert({ message: __("Янгиланди"), indicator: "green" }, 3);
			}).catch((e) => { if (e !== "stale") { console.error("[jazira-dashboard]", e); this.fatal(); } });
		}

		render_tab(id) {
			const c = this.ctx || {};
			this.$sub.text(`${c.label || ""} · ${this.scope_label()}`);
			this.$updated.text(`${__("Янгиланди")} ${(c.computed_at || "").slice(11)}`);
			this.render_status();
			this.kill_charts();
			this.$body.empty();
			this.safe(() => this["tab_" + id]());
		}

		scope_label() {
			if (this.state.scope === "all") return __("Барча компаниялар");
			const c = (this.meta.companies || []).find((x) => x.name === this.state.scope);
			return c ? c.label : this.state.scope;
		}

		safe(fn, host) {
			try { fn(); } catch (e) {
				console.error("[jazira-dashboard]", e);
				(host || this.$body).append(`<div class="jazira-inline-error">${ICON.alert}<span>${__("Бу бўлимни чизишда хатолик")}</span></div>`);
			}
		}

		skeleton() {
			const bar = (w) => `<div class="jzd-sk" style="width:${w}"></div>`;
			this.$body.html(`
				<div class="jazira-kpi-grid">${Array(5).fill(`<div class="jazira-kpi-card">${bar("50%")}${bar("72%")}${bar("36%")}</div>`).join("")}</div>
				<div class="jazira-card" style="margin-top:16px"><div class="jazira-card-body"><div class="jzd-sk jzd-sk-chart"></div></div></div>`);
		}

		// ── Umumiy qismlar ──────────────────────────────────────────────
		card(o) {
			return `<article class="jazira-card ${o.cls || ""}">
				<header class="jazira-card-head">
					<div class="jazira-card-title"><h3>${esc(o.title)}${o.tip ? tip(o.tip) : ""}</h3>${o.sub ? `<p>${o.sub}</p>` : ""}</div>
					<div class="jazira-card-tools">${o.tools || ""}</div>
				</header>
				<div class="jazira-card-body">${o.body}</div></article>`;
		}
		grid(cols, html) { return `<div class="jazira-grid jazira-grid-${cols}">${html}</div>`; }
		seg(name, options, active) {
			return `<div class="jazira-seg" data-seg="${name}">${options.map((o) =>
				`<button type="button" data-v="${esc(o.v)}" class="${String(o.v) === String(active) ? "on" : ""}">${esc(o.label)}</button>`).join("")}</div>`;
		}
		bind_seg($el, name, fn) {
			$el.find(`[data-seg="${name}"] button`).off("click").on("click", (e) => fn($(e.currentTarget).data("v")));
		}
		link(drill, label) {
			if (!drill || !this.can_drill(drill.report)) return "";
			return `<button type="button" class="jazira-link" data-report="${esc(drill.report)}" data-filters="${esc(JSON.stringify(drill.filters || {}))}">${esc(label || __("Ҳисобот"))} ${ICON.arrow}</button>`;
		}
		can_drill(r) { return !!(this.meta && this.meta.can_drill && this.meta.can_drill[r]); }
		drill($b) {
			const report = $b.data("report"); if (!this.can_drill(report)) return;
			let f = {}; try { f = JSON.parse($b.attr("data-filters") || "{}"); } catch (e) { /* noop */ }
			if (!f.from_date) f.from_date = this.state.from_date;
			if (!f.to_date) f.to_date = this.state.to_date;
			frappe.route_options = f; frappe.set_route("query-report", report);
		}
		empty(t) { return `<div class="jazira-empty">${esc(t || __("Бу давр учун маълумот йўқ"))}</div>`; }
		err(s) { return `<div class="jazira-inline-error">${ICON.alert}<span>${esc(s.error)}</span></div>`; }
		kill_charts() {
			Object.values(this.charts).forEach((c) => { try { c.destroy && c.destroy(); } catch (e) { /* noop */ } });
			this.charts = {};
		}
		chart(key, el, opts) {
			if (!el) return; el.innerHTML = "";
			this.charts[key] = new frappe.Chart(el, Object.assign({ animate: 0, truncateLegends: 1 }, opts));
		}
		// HTML gorizontal bar — uzun tovar nomlari uchun grafikdan qulayroq
		hbars(rows, opts) {
			const o = opts || {};
			const max = Math.max.apply(null, rows.map((r) => Math.abs(r.value)).concat([1]));
			return `<ol class="jazira-hbars">${rows.map((r, i) => `
				<li>
					<span class="jazira-hbar-rank">${i + 1}</span>
					<span class="jazira-hbar-name" title="${esc(r.label)}">${esc(r.label)}</span>
					<span class="jazira-hbar-track"><i style="width:${Math.max(1.5, Math.abs(r.value) / max * 100).toFixed(1)}%"></i></span>
					<span class="jazira-hbar-val">${o.fmt ? o.fmt(r) : money(r.value)}</span>
					${o.extra ? `<span class="jazira-hbar-extra">${o.extra(r)}</span>` : ""}
				</li>`).join("")}</ol>`;
		}

		// ── Holat lentasi (ixcham, faqat muammo bo'lsa) ─────────────────
		render_status() {
			const h = this.data.health;
			const bits = [];
			if (h && !h.error) {
				const fresh = (h.chips || []).find((c) => c.id === "fresh");
				if (fresh && fresh.tone !== "ok") {
					bits.push(`<div class="jazira-status-banner jzd-tone-${esc(fresh.tone)}">${ICON.alert}
						<span><b>${__("Сотув маълумоти кечикмоқда")}</b> — ${esc(fresh.text)}${
							h.last_sale ? ` (${__("охирги сотув")} ${esc(h.last_sale)})` : ""}</span></div>`);
				}
			}
			this.$status.html(bits.join(""));
		}
	}

	// ═════════════════════════════════════════════════════════════════════
	// TABLAR
	// ═════════════════════════════════════════════════════════════════════
	Object.assign(Dashboard.prototype, {

		// ── ОБЗОР ────────────────────────────────────────────────────────
		tab_overview() {
			const d = this.data;
			this.$body.append(this.block_kpi(d.kpi));
			this.$body.append(this.block_daily(d.daily, { compact: true }));
			this.$body.append(this.grid(2,
				this.block_companies_chart(d.companies) + this.block_products_top(d.products, 8)));
			this.after_render();
		},

		// ── САВДО ────────────────────────────────────────────────────────
		tab_sales() {
			const d = this.data;
			this.$body.append(this.block_daily(d.daily, { compare: true }));
			this.$body.append(this.grid(2, this.block_weekdays(d.weekdays) + this.block_best_days(d.best_days)));
			this.$body.append(this.block_monthly(d.monthly, "sales"));
			this.after_render();
		},

		// ── ТОВАРЛАР ─────────────────────────────────────────────────────
		tab_products() {
			const d = this.data;
			this.$body.append(this.grid(2, this.block_products_top(d.products, 15) + this.block_categories(d.categories)));
			this.$body.append(this.grid(2, this.block_movers(d.products, "rising") + this.block_movers(d.products, "falling")));
			this.$body.append(this.block_turnover(d.products));
			this.after_render();
		},

		// ── ФИЛИАЛЛАР ────────────────────────────────────────────────────
		tab_branches() {
			const d = this.data;
			this.$body.append(this.block_companies_table(d.companies));
			this.$body.append(this.grid(2, this.block_companies_chart(d.companies, true) + this.block_company_products(d.company_products)));
			this.after_render();
		},

		// ── МОЛИЯ ────────────────────────────────────────────────────────
		tab_finance() {
			const d = this.data;
			this.$body.append(this.grid(2, this.block_pnl(d.pnl) + this.block_monthly(d.monthly, "finance")));
			this.$body.append(this.block_expenses(d.expenses));
			this.$body.append(this.block_owners(d.owners));
			this.after_render();
		},

		// ── БУХГАЛТЕРИЯ ──────────────────────────────────────────────────
		tab_accounting() {
			const d = this.data;
			this.$body.append(this.grid(2, this.block_cash(d.cash) + this.block_debt(d.cash)));
			this.$body.append(this.grid(2, this.block_balance_misc(d.cash) + this.block_health(d.health)));
			this.after_render();
		},

		// Chizilgandan keyin: grafiklar va tugmalar
		after_render() {
			const pending = this._pending || [];
			this._pending = [];
			pending.forEach((fn) => this.safe(fn));
		},
		defer(fn) { (this._pending = this._pending || []).push(fn); },

		// ═══ BLOKLAR ═════════════════════════════════════════════════════

		block_kpi(k) {
			if (!k) return ""; if (k.error) return this.err(k);
			const tiles = (k.tiles || []).map((t) => {
				let value, d;
				if (t.kind === "pct") { value = pct(t.value); d = delta(null, t.delta_abs, false, "pp"); }
				else if (t.kind === "qty") { value = qty(t.value); d = delta(t.delta_pct, null); }
				else { value = money(t.value); d = delta(t.delta_pct, null); }
				return `<div class="jazira-kpi-card ${t.lead ? "jzd-lead" : ""}">
					<div class="jazira-kpi-label">${esc(t.label)}</div>
					<div class="jazira-kpi-value">${value}</div>
					<div class="jazira-kpi-foot">${d}<span class="jzd-dim">${t.sub ? esc(t.sub) : __("ўтган даврга")}</span></div>
				</div>`;
			}).join("");
			return `<div class="jazira-kpi-grid">${tiles}</div>`;
		},

		block_daily(d, o) {
			if (!d) return ""; if (d.error) return this.err(d);
			o = o || {};
			const days = d.days || [], cos = d.companies || [];
			const pick = this.view.daily;
			const has = days.some((x) => x.total !== null);
			const sub = d.best ? `${__("Энг зўр кун")}: <b>${esc(d.best.label)}</b> ${money(d.best.total)} · ${__("энг заиф")}: <b>${esc(d.worst.label)}</b> ${money(d.worst.total)}` : "";
			const tools = cos.length > 1 ? this.seg("daily", [{ v: "all", label: __("Барчаси") }].concat(cos.map((c) => ({ v: c.company, label: c.label }))), pick) : "";
			const id = "daily-" + (o.compact ? "c" : "f");
			this.defer(() => {
				const $el = this.$body.find(`[data-chart="${id}"]`); if (!$el.length || !has) return;
				let datasets;
				if (pick === "all" && cos.length > 1) datasets = cos.map((c) => ({ name: c.label, values: days.map((x) => x.by_company[c.company] ?? null) }));
				else if (pick !== "all") datasets = [{ name: (cos.find((c) => c.company === pick) || {}).label || pick, values: days.map((x) => x.by_company[pick] ?? null) }];
				else datasets = [{ name: __("Сотув"), values: days.map((x) => x.total) }];
				if (o.compare && d.prev_series) datasets.push({ name: __("Ўтган давр"), values: d.prev_series });
				const colors = palette();
				if (o.compare) colors.splice(datasets.length - 1, 0, tone("--jzd-c7", "#98a2b3"));
				this.chart(id, $el[0], {
					type: "line", height: o.compact ? 240 : 300, colors,
					data: { labels: days.map((x) => x.label), datasets },
					lineOptions: { hideDots: days.length > 40 ? 1 : 0, regionFill: datasets.length === 1 ? 1 : 0, spline: 0 },
					axisOptions: { xAxisMode: "tick", shortenYAxisNumbers: 1, xIsSeries: 1 },
					tooltipOptions: { formatTooltipY: (v) => compact(v) },
				});
				this.bind_seg(this.$body, "daily", (v) => { this.view.daily = String(v); this.render_tab(this.tab); });
			});
			return this.card({ title: __("Кунлик сотув"), sub, tools,
				tip: __("Бўш кун — маълумот йўқ дегани, нол сотув эмас."),
				body: has ? `<div class="jazira-chart" data-chart="${id}"></div>` : this.empty() });
		},

		block_companies_chart(c, withTable) {
			if (!c) return ""; if (c.error) return this.err(c);
			const rows = (c.rows || []).filter((r) => r.has_data);
			this.defer(() => {
				const $b = this.$body.find('[data-chart="co-bar"]'), $p = this.$body.find('[data-chart="co-pie"]');
				if ($b.length && rows.length) this.chart("co-bar", $b[0], {
					type: "bar", height: 220, colors: [tone("--jzd-c1", "#3b7bd4")],
					data: { labels: rows.map((r) => r.label), datasets: [{ name: __("Тушум"), values: rows.map((r) => r.revenue) }] },
					barOptions: { spaceRatio: 0.5 }, axisOptions: { xAxisMode: "tick", shortenYAxisNumbers: 1 },
					tooltipOptions: { formatTooltipY: (v) => compact(v) } });
				if ($p.length && rows.length) this.chart("co-pie", $p[0], {
					type: "donut", height: 220, colors: palette(),
					data: { labels: rows.map((r) => r.label), datasets: [{ values: rows.map((r) => r.revenue) }] },
					tooltipOptions: { formatTooltipY: (v) => compact(v) } });
			});
			const list = rows.map((r) => `<li><span><i class="jazira-dot"></i>${esc(r.label)}${r.is_sklad ? ` <span class="jazira-tag">${__("ташқи")}</span>` : ""}</span>${money(r.revenue)}<em>${pct(r.share, 0)}</em></li>`).join("");
			return this.card({ title: __("Филиаллар улуши"), tools: this.link(c.drill, "PL Hisoboti"),
				tip: __("Ҳар компаниянинг ТАШҚИ сотуви. Складнинг филиалларга сотуви бу ерга кирмайди — гуруҳ даромадини икки марта санамаслик учун."),
				body: rows.length ? `<div class="jazira-two"><div class="jazira-chart" data-chart="co-pie"></div>
					<ul class="jazira-minilist jazira-minilist-share">${list}</ul></div>
					<div class="jazira-chart" data-chart="co-bar"></div>` : this.empty() });
		},

		block_products_top(p, n) {
			if (!p) return ""; if (p.error) return this.err(p);
			const mode = this.view.products;
			const list = (mode === "qty" ? p.by_qty : p.by_amount) || [];
			const rows = list.slice(0, n).map((r) => ({ label: r.item, value: mode === "qty" ? r.qty : r.amount, r }));
			this.defer(() => this.bind_seg(this.$body, "products", (v) => { this.view.products = String(v); this.render_tab(this.tab); }));
			return this.card({ title: __("Энг кўп сотилган товарлар"), sub: `${p.count || 0} ${__("хил товар")} · ${money(p.total)}`,
				tools: this.seg("products", [{ v: "amount", label: __("Сумма") }, { v: "qty", label: __("Дона") }], mode) + this.link(p.drill, __("Сотув")),
				tip: __("Товар бўйича маржа кўрсатилмайди — филиал омбори текширилмагани учун таннарх ишончсиз."),
				body: rows.length ? this.hbars(rows, {
					fmt: (x) => mode === "qty" ? qty(x.value) : money(x.value),
					extra: (x) => `${pct(x.r.share, 0)} · ${delta(x.r.delta_pct, x.r.delta_abs)}`,
				}) : this.empty() });
		},

		block_categories(c) {
			if (!c) return ""; if (c.error) return this.err(c);
			const pie = c.pie || [];
			this.defer(() => {
				const $el = this.$body.find('[data-chart="cat-pie"]'); if (!$el.length || !pie.length) return;
				this.chart("cat-pie", $el[0], { type: "donut", height: 260, colors: palette(),
					data: { labels: pie.map((x) => x.group), datasets: [{ values: pie.map((x) => x.amount) }] },
					tooltipOptions: { formatTooltipY: (v) => compact(v) } });
			});
			const rows = (c.rows || []).map((x) => `<tr><td class="jzd-name">${esc(x.group)}</td><td class="jzd-r">${qty(x.qty)}</td><td class="jzd-r">${money(x.amount)}</td><td class="jzd-r jzd-dim">${pct(x.share)}</td></tr>`).join("");
			return this.card({ title: __("Категориялар"), sub: `${(c.rows || []).length} ${__("гуруҳ")}`,
				body: pie.length ? `<div class="jazira-chart" data-chart="cat-pie"></div>
					<table class="jazira-table jazira-table-sm"><thead><tr><th>${__("Гуруҳ")}</th><th class="jzd-r">${__("Дона")}</th><th class="jzd-r">${__("Сумма")}</th><th class="jzd-r">${__("Улуш")}</th></tr></thead><tbody>${rows}</tbody></table>` : this.empty() });
		},

		block_movers(p, kind) {
			if (!p) return ""; if (p.error) return "";
			const list = p[kind] || [];
			const rising = kind === "rising";
			const rows = list.map((r) => `<tr><td class="jzd-name">${esc(r.item)}</td><td class="jzd-r jzd-dim">${money(r.prev_amount)}</td><td class="jzd-r">${money(r.amount)}</td><td class="jzd-r">${delta(r.delta_pct, r.delta_abs)}</td></tr>`).join("");
			const gone = !rising && (p.gone || []).length ? `<p class="jazira-note">${__("Сотилмай қолганлар")}: ${p.gone.map((g) => `<b>${esc(g.item)}</b> (${compact(g.prev_amount)})`).join(", ")}</p>` : "";
			return this.card({ title: rising ? __("Ўсаётган товарлар") : __("Тушаётган товарлар"),
				sub: `${__("ўтган даврга нисбатан")} (${esc((this.ctx || {}).prev_label || "")})`, cls: rising ? "jzd-edge-ok" : "jzd-edge-danger",
				body: rows ? `<table class="jazira-table jazira-table-sm"><thead><tr><th>${__("Товар")}</th><th class="jzd-r">${__("Олдин")}</th><th class="jzd-r">${__("Ҳозир")}</th><th class="jzd-r">Δ</th></tr></thead><tbody>${rows}</tbody></table>${gone}` : this.empty(__("Сезиларли ўзгариш йўқ")) + gone });
		},

		block_turnover(p) {
			if (!p) return ""; if (p.error) return "";
			const rows = (p.turnover || []).map((r, i) => `<tr><td class="jzd-rank">${i + 1}</td><td class="jzd-name">${esc(r.item)}<span class="jzd-dim jzd-small">${esc(r.group || "")}</span></td><td class="jzd-r">${qty(r.qty)}</td><td class="jzd-r"><b>${r.per_day === null ? "—" : r.per_day.toLocaleString("ru-RU")}</b></td><td class="jzd-r">${money(r.amount)}</td><td class="jzd-r jzd-dim">${pct(r.share)}</td><td class="jzd-r">${delta(r.delta_pct, r.delta_abs)}</td></tr>`).join("");
			return this.card({ title: __("Товар айланмаси"), sub: __("кун бошига сотилган дона — қайси товар қанчалик тез кетади"),
				body: rows ? `<table class="jazira-table"><thead><tr><th>#</th><th>${__("Товар")}</th><th class="jzd-r">${__("Дона")}</th><th class="jzd-r">${__("Кунига")}</th><th class="jzd-r">${__("Сумма")}</th><th class="jzd-r">${__("Улуш")}</th><th class="jzd-r">Δ</th></tr></thead><tbody>${rows}</tbody></table>` : this.empty() });
		},

		block_weekdays(w) {
			if (!w) return ""; if (w.error) return this.err(w);
			const rows = (w.rows || []).filter((x) => x.avg);
			this.defer(() => {
				const $el = this.$body.find('[data-chart="wd"]'); if (!$el.length || !rows.length) return;
				this.chart("wd", $el[0], { type: "bar", height: 240, colors: [tone("--jzd-c1", "#3b7bd4")],
					data: { labels: (w.rows || []).map((x) => x.short), datasets: [{ name: __("Ўртача"), values: (w.rows || []).map((x) => x.avg) }] },
					barOptions: { spaceRatio: 0.4 }, axisOptions: { xAxisMode: "tick", shortenYAxisNumbers: 1 },
					tooltipOptions: { formatTooltipY: (v) => compact(v) } });
			});
			const sub = w.best ? `${__("энг кучли")}: <b>${esc(w.best.label)}</b> ${money(w.best.avg)} · ${__("энг заиф")}: <b>${esc(w.worst.label)}</b> ${money(w.worst.avg)}` : "";
			const list = (w.rows || []).map((x) => `<li><span>${esc(x.label)}<em class="jzd-dim">${x.days} ${__("кун")}</em></span>${money(x.avg)}<em class="${(x.vs_avg_pct || 0) >= 0 ? "jzd-up" : "jzd-down"}">${x.vs_avg_pct === null ? "" : (x.vs_avg_pct >= 0 ? "+" : "") + pct(x.vs_avg_pct, 0)}</em></li>`).join("");
			return this.card({ title: __("Ҳафта кунлари"), sub, tip: __("Ҳар бир ҳафта кунининг ўртача сотуви. Фоиз — умумий ўртачага нисбатан."),
				body: rows.length ? `<div class="jazira-chart" data-chart="wd"></div><ul class="jazira-minilist jazira-minilist-share">${list}</ul>` : this.empty() });
		},

		block_best_days(b) {
			if (!b) return ""; if (b.error) return this.err(b);
			const row = (x) => `<tr><td class="jzd-name">${esc(x.label)} <span class="jzd-dim">${esc(x.weekday)}</span></td><td class="jzd-r">${money(x.total)}</td><td class="jzd-dim">${Object.keys(x.by_company).length > 1 ? Object.entries(x.by_company).map(([k, v]) => `${esc(k)} ${compact(v)}`).join(" · ") : ""}</td></tr>`;
			const best = (b.best || []).map(row).join(""), worst = (b.worst || []).map(row).join("");
			return this.card({ title: __("Энг зўр ва энг заиф кунлар"),
				body: best ? `<h4 class="jazira-subhead jzd-up">${__("Энг зўр")}</h4><table class="jazira-table jazira-table-sm"><tbody>${best}</tbody></table>
					${worst ? `<h4 class="jazira-subhead jzd-down">${__("Энг заиф")}</h4><table class="jazira-table jazira-table-sm"><tbody>${worst}</tbody></table>` : ""}` : this.empty() });
		},

		block_monthly(m, mode) {
			if (!m) return ""; if (m.error) return this.err(m);
			const rows = m.rows || [];
			const id = "monthly-" + mode;
			this.defer(() => {
				const $el = this.$body.find(`[data-chart="${id}"]`); if (!$el.length || !rows.length) return;
				const labels = rows.map((r) => r.short + (r.complete ? "" : "*"));
				if (mode === "finance") this.chart(id, $el[0], { type: "axis-mixed", height: 280,
					colors: [tone("--jzd-c1", "#3b7bd4"), tone("--jzd-c2", "#2f9e68"), tone("--jzd-c4", "#7a5cc4")],
					data: { labels, datasets: [
						{ name: __("Тушум"), chartType: "bar", values: rows.map((r) => r.revenue) },
						{ name: __("Ялпи фойда"), chartType: "line", values: rows.map((r) => r.marginal) },
						{ name: __("Операцион фойда"), chartType: "line", values: rows.map((r) => r.profit) }] },
					barOptions: { spaceRatio: 0.45 }, lineOptions: { hideDots: 0, regionFill: 0 },
					axisOptions: { xAxisMode: "tick", shortenYAxisNumbers: 1 }, tooltipOptions: { formatTooltipY: (v) => compact(v) } });
				else this.chart(id, $el[0], { type: "axis-mixed", height: 280,
					colors: [tone("--jzd-c1", "#3b7bd4"), tone("--jzd-c3", "#e0a020")],
					data: { labels, datasets: [
						{ name: __("Тушум"), chartType: "bar", values: rows.map((r) => r.revenue) },
						{ name: __("Дона"), chartType: "line", values: rows.map((r) => r.qty) }] },
					barOptions: { spaceRatio: 0.45 }, lineOptions: { hideDots: 0, regionFill: 0 },
					axisOptions: { xAxisMode: "tick", shortenYAxisNumbers: 1 }, tooltipOptions: { formatTooltipY: (v) => compact(v) } });
			});
			const tbl = rows.map((r) => `<tr class="${r.complete ? "" : "jzd-dim"}"><td class="jzd-name">${esc(r.label)}${r.complete ? "" : " *"}</td><td class="jzd-r">${money(r.revenue)}</td><td class="jzd-r">${qty(r.qty)}</td><td class="jzd-r">${money(r.marginal)}</td><td class="jzd-r jzd-dim">${pct(r.margin_pct)}</td><td class="jzd-r">${money(r.profit)}</td></tr>`).join("");
			return this.card({ title: __("Ойлик динамика"), sub: rows.some((r) => !r.complete) ? `* — ${__("тўлиқ бўлмаган ой")}` : "",
				body: rows.length ? `<div class="jazira-chart" data-chart="${id}"></div>
					<table class="jazira-table jazira-table-sm"><thead><tr><th>${__("Ой")}</th><th class="jzd-r">${__("Тушум")}</th><th class="jzd-r">${__("Дона")}</th><th class="jzd-r">${__("Ялпи фойда")}</th><th class="jzd-r">${__("Маржа")}</th><th class="jzd-r">${__("Опер. фойда")}</th></tr></thead><tbody>${tbl}</tbody></table>` : this.empty() });
		},
	});

	Object.assign(Dashboard.prototype, {

		// ── ФИЛИАЛЛАР ────────────────────────────────────────────────────
		block_companies_table(c) {
			if (!c) return ""; if (c.error) return this.err(c);
			const rows = (c.rows || []).map((r) => `
				<tr data-report="PL Hisoboti" data-filters="${esc(JSON.stringify({ company: r.company, periodicity: "Monthly" }))}" class="${r.selected ? "jzd-selected" : ""} ${r.has_data ? "" : "jzd-dim"}">
					<td class="jzd-name">${esc(r.label)}${r.is_sklad ? ` <span class="jazira-tag">${__("ташқи сотуви")}</span>` : ""}</td>
					<td class="jzd-r">${money(r.revenue)}</td>
					<td class="jzd-r">${qty(r.qty)}</td>
					<td class="jzd-r jzd-dim">${pct(r.margin_pct)}</td>
					<td class="jzd-r">${r.daily_avg ? money(r.daily_avg) : "—"}</td>
					<td class="jzd-r jzd-dim">${r.days}</td>
					<td class="jzd-r">${pct(r.share, 0)}</td>
					<td class="jzd-r">${delta(r.delta_pct, null)}</td>
				</tr>`).join("");
			return this.card({ title: __("Филиаллар таққослаши"), sub: `${__("жами")} ${money(c.total)}`,
				tools: this.link(c.drill, "PL Hisoboti"),
				tip: __("Склад қатори — унинг ташқи сотуви. Филиалларга етказиб бериш гуруҳ даромади эмас."),
				body: `<table class="jazira-table jazira-table-hover"><thead><tr>
					<th>${__("Компания")}</th><th class="jzd-r">${__("Тушум")}</th><th class="jzd-r">${__("Дона")}</th>
					<th class="jzd-r">${__("Маржа")}</th><th class="jzd-r">${__("Кунлик ўртача")}</th><th class="jzd-r">${__("Кун")}</th>
					<th class="jzd-r">${__("Улуш")}</th><th class="jzd-r">Δ</th></tr></thead><tbody>${rows}</tbody></table>` });
		},

		block_company_products(cp) {
			if (!cp) return ""; if (cp.error) return this.err(cp);
			const blocks = (cp.rows || []).filter((c) => c.items.length).map((c) => `
				<div class="jazira-co-block">
					<h4>${esc(c.label)}${c.is_sklad ? ` <span class="jazira-tag">${__("етказиб бериш")}</span>` : ""}</h4>
					${this.hbars(c.items.map((i) => ({ label: i.item, value: i.amount, r: i })), { extra: (x) => pct(x.r.share, 0) })}
				</div>`).join("");
			return this.card({ title: __("Ҳар филиалнинг топ товарлари"), body: blocks || this.empty() });
		},

		// ── МОЛИЯ ────────────────────────────────────────────────────────
		block_pnl(p) {
			if (!p) return ""; if (p.error) return this.err(p);
			const rows = (p.lines || []).map((l) => `
				<tr class="jzd-row-${l.kind}">
					<td>${esc(l.label)}</td>
					<td class="jzd-r">${money(l.value)}</td>
					<td class="jzd-r jzd-dim">${l.pct_of_revenue === null ? "" : pct(l.pct_of_revenue, 0)}</td>
					<td class="jzd-r jzd-dim">${money(l.prev)}</td>
					<td class="jzd-r">${delta(l.delta_pct, l.delta_abs, l.is_cost)}</td>
				</tr>`).join("");
			const sub = `${__("маржа")} <b>${pct(p.margin_pct)}</b> · ${__("рентабеллик")} <b>${pct(p.profit_pct)}</b>`;
			return this.card({ title: __("Фойда ва зарар"), sub, tools: this.link(p.drill, p.drill && p.drill.report),
				tip: __("Мавжуд P&L ҳисоботи билан айнан мос. Ички айланма тушумдан ҳам, таннархдан ҳам чиқарилган."),
				body: `<table class="jazira-table jazira-table-pnl"><thead><tr><th></th><th class="jzd-r">${esc((this.ctx || {}).label || "")}</th><th class="jzd-r">%</th><th class="jzd-r">${__("Олдинги")}</th><th class="jzd-r">Δ</th></tr></thead><tbody>${rows}</tbody></table>` });
		},

		block_expenses(x) {
			if (!x) return ""; if (x.error) return this.err(x);
			const list = (x.operating || []).slice(0, 12).map((r) => ({ label: r.label, value: r.value, r }));
			const adm = x.show_admin && (x.admin || []).length ? `<h4 class="jazira-subhead">${__("Маъмурий")} <span class="jzd-dim">${__("гуруҳ бўйича, тақсимлашдан олдин")} · ${money(x.admin_total)}</span></h4>
				${this.hbars(x.admin.slice(0, 8).map((r) => ({ label: r.label, value: r.value, r })), { extra: (y) => delta(y.r.delta_pct, y.r.delta_abs, true) })}` : "";
			return this.card({ title: __("Харажатлар"), sub: `${__("операцион жами")} ${money(x.operating_total)}`, tools: this.link(x.drill, "Expense Analysis"),
				body: list.length ? this.hbars(list, { extra: (y) => delta(y.r.delta_pct, y.r.delta_abs, true) }) + adm : this.empty() });
		},

		block_owners(o) {
			if (!o) return ""; if (o.error) return this.err(o);
			const cards = (o.owners || []).map((w) => `
				<div class="jazira-owner">
					<h4>${esc(w.label)}</h4>
					<div class="jazira-owner-share">${money(w.share)}</div>
					<span class="jzd-dim">${__("давр фойдасидаги улуши")}</span>
					<dl class="jazira-owner-rows">
						<div><dt>${__("Олган")}</dt><dd>${money(w.taken)}</dd></div>
						<div><dt>${__("Киритган")}</dt><dd>${money(w.added)}</dd></div>
						<div class="jzd-sep"><dt>${__("Давр ичида, соф")}</dt><dd>${money(w.net)}</dd></div>
						<div><dt>${__("Ҳисоб-варақ қолдиғи")}${tip(__("Мусбат — эга кўпроқ олган, манфий — кўпроқ киритган."))}</dt><dd>${money(w.cumulative)}</dd></div>
					</dl></div>`).join("");
			const rows = (o.by_company || []).map((r) => `<tr><td class="jzd-name">${esc(r.label)}</td><td class="jzd-r">${money(r.profit)}</td><td class="jzd-r">${money(r.akmal)}</td><td class="jzd-r">${money(r.elyor)}</td><td class="jzd-c jzd-dim">${esc(r.rule)}</td></tr>`).join("");
			return this.card({ title: __("Эгалар"), tools: this.link(o.drill, "PL Calculation"), tip: esc(o.rule),
				body: `<div class="jazira-owner-grid">${cards}</div>
					<table class="jazira-table jazira-table-sm"><thead><tr><th>${__("Компания")}</th><th class="jzd-r">${__("Фойда")}</th><th class="jzd-r">Акмал</th><th class="jzd-r">Элёр</th><th class="jzd-c">${__("Қоида")}</th></tr></thead><tbody>${rows}</tbody></table>` });
		},

		// ── БУХГАЛТЕРИЯ ──────────────────────────────────────────────────
		block_cash(m) {
			if (!m) return ""; if (m.error) return this.err(m);
			const c = m.cash || {};
			const byco = (c.by_company || []).map((x) => `<li><span>${esc(x.label)}</span>${money(x.value)}</li>`).join("");
			const byacc = (c.by_account || []).map((x) => ({ label: x.name, value: x.value }));
			return this.card({ title: __("Касса ва терминаллар"), sub: `${esc(m.as_of)} ${__("ҳолатига")}`, tools: this.link(m.drill, "Balance Obshi"),
				tip: __("Банк ҳисоблари ишлатилмайди — барча пул касса ва терминал ҳисобларида."),
				body: `<div class="jazira-figure"><div class="jazira-figure-value">${money(c.total)}</div>
					<div class="jazira-figure-foot">${delta(c.delta_pct, null)}<span class="jzd-dim">${__("ўтган давр охирига нисбатан")}</span></div></div>
					${byco && (c.by_company || []).length > 1 ? `<ul class="jazira-minilist">${byco}</ul><div class="jazira-divider"></div>` : ""}
					<h4 class="jazira-subhead">${__("Ҳисоблар кесимида")}</h4>
					${byacc.length ? this.hbars(byacc) : this.empty()}` });
		},

		block_debt(m) {
			if (!m) return ""; if (m.error) return "";
			const d = m.supplier_debt || {};
			const cov = d.coverage_pct;
			const top = (d.top || []).map((x) => ({ label: x.party, value: x.value }));
			return this.card({ title: __("Таъминотчиларга қарз"), sub: `${esc(m.as_of)} ${__("ҳолатига")}`,
				tip: __("Бош китобдаги таъминотчи қолдиғи. Муддат бўйича бўлиш мумкин эмас — тўловлар фактураларга боғланмаган."),
				body: `<div class="jazira-figure"><div class="jazira-figure-value jzd-neg">${money(d.total)}</div>
					<div class="jazira-figure-foot">${delta(d.delta_pct, null, true)}<span class="jzd-dim">${__("ўтган давр охирига нисбатан")}</span></div></div>
					${cov === null || cov === undefined ? "" : `<div class="jazira-coverage"><div class="jazira-coverage-bar"><span style="width:${Math.max(1, Math.min(100, cov)).toFixed(1)}%"></span></div>
					<p>${__("Касса қарзнинг")} <b>${pct(cov)}</b> ${__("қисмини қоплайди")}</p></div>`}
					<h4 class="jazira-subhead">${__("Энг катта кредиторлар")}</h4>
					${top.length ? this.hbars(top, { cls: "danger" }) : this.empty()}` });
		},

		block_balance_misc(m) {
			if (!m) return ""; if (m.error) return "";
			const inv = m.inventory || {};
			return this.card({ title: __("Захира, дебитор, кредитор"), sub: `${esc(m.as_of)} ${__("ҳолатига")}`,
				body: `<div class="jazira-stat-grid">
					<div><span>${__("Захиралар (омбор)")}${tip(__("Бош китобдан. Филиалларда текширилмаган инвентаризациялар бор."))}</span>${money(inv.value)}
						${(inv.drafts || inv.negative) ? `<em class="jzd-warn-note">${inv.drafts} ${__("черновик")} · ${inv.negative} ${__("манфий қолдиқ")}</em>` : ""}</div>
					<div><span>${__("Учинчи томон дебитори")}</span>${money(m.receivable)}</div>
					<div><span>${__("Учинчи томон кредитори")}</span>${money(m.payable)}</div>
					<div><span>${__("Захира ўзгариши")}</span>${delta(null, (inv.value || 0) - (inv.prev || 0))}</div>
				</div>` });
		},

		block_health(h) {
			if (!h) return ""; if (h.error) return this.err(h);
			const icon = (t) => (t === "ok" ? ICON.check : ICON.alert);
			const cards = (h.chips || []).map((c) => `
				<button type="button" class="jazira-quality-card jzd-tone-${esc(c.tone)}" data-chip="${esc(c.id)}">
					<span class="jazira-quality-icon">${icon(c.tone)}</span>
					<span class="jazira-quality-body"><b>${esc(c.label)}</b><span>${esc(c.text)}</span></span></button>`).join("");
			this.defer(() => {
				this.$body.find("[data-chip]").off("click").on("click", (e) => {
					const chip = (h.chips || []).find((x) => x.id === $(e.currentTarget).data("chip")); if (!chip) return;
					if (chip.drill && this.can_drill(chip.drill.report)) { frappe.route_options = chip.drill.filters || {}; return frappe.set_route("query-report", chip.drill.report); }
					if (chip.route) return frappe.set_route.apply(frappe, chip.route);
					if (chip.detail) frappe.msgprint({ title: chip.label, indicator: chip.tone === "ok" ? "green" : "orange",
						message: `<ul>${chip.detail.map((d) => `<li>${esc(d.label)} — ${esc(d.last_date || __("йўқ"))}${d.days !== null && d.days !== undefined ? ` (${d.days} ${__("кун олдин")})` : ""}</li>`).join("")}</ul>` });
				});
			});
			return this.card({ title: __("Маълумот ишончлилиги"), tip: __("Қизил бўлса — юқоридаги рақамларга тўлиқ ишониб бўлмайди."),
				body: `<div class="jazira-quality-grid">${cards}</div>` });
		},
	});

	frappe.pages["jazira-dashboard"].on_page_load = function (wrapper) {
		const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Jazira — Бизнес панели"), single_column: true });
		$(wrapper).find(".container").css({ "max-width": "100%", "padding-left": "22px", "padding-right": "22px" });
		wrapper.__jzd = new Dashboard(wrapper, page);
	};
	frappe.pages["jazira-dashboard"].on_page_show = function (wrapper) {
		if (wrapper.__jzd && wrapper.__jzd.meta) wrapper.__jzd.reload();
	};
})();
