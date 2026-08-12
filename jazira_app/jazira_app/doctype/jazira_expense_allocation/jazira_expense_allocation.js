const JAZIRA_ALLOCATION_COMPANIES = [
    'Jazira Sklad',
    'Jazira Smart',
    'Jazira Saripul',
    'Jazira Xalq Banki'
];

const JAZIRA_AUTO_CALCULATE_DELAY = 700;

function get_calculation_key(frm) {
    return [
        frm.doc.from_date,
        frm.doc.to_date,
        frm.doc.expense_source_company || '',
        frm.doc.create_source_reversal ? 1 : 0,
        frm.doc.profit_source,
        (frm.doc.companies || []).map((row) => row.company).join(',')
    ].join('|');
}

function is_full_month_period(frm) {
    if (!frm.doc.from_date || !frm.doc.to_date) {
        return false;
    }

    const from_date = moment(frm.doc.from_date, 'YYYY-MM-DD', true);
    const to_date = moment(frm.doc.to_date, 'YYYY-MM-DD', true);
    if (!from_date.isValid() || !to_date.isValid()) {
        return false;
    }

    return from_date.isSame(from_date.clone().startOf('month'), 'day')
        && to_date.isSame(from_date.clone().endOf('month'), 'day');
}

function can_calculate(frm, show_message) {
    const missing = !frm.doc.from_date
        || !frm.doc.to_date
        || !frm.doc.expense_source_company;

    if (!missing) {
        return true;
    }

    if (show_message) {
        frappe.msgprint({
            title: __('Ma\'lumot yetarli emas'),
            indicator: 'orange',
            message: __('Period boshi, period oxiri va xarajat manba kompaniyasini kiriting.')
        });
    }

    return false;
}

function run_jazira_calculation(frm, automatic=false) {
    if (frm.doc.docstatus !== 0) {
        return;
    }

    if (frm.__auto_calculating) {
        if (automatic) {
            return;
        }
        // Foydalanuvchi Hisoblash bosdi, lekin avtomatik hisob hali ketmoqda.
        // Avval bosish INDAMAY tashlab yuborilardi ("tugma ishlamayapti"
        // degan taassurot). Endi: kutib turamiz-da, tugagach qayta urinamiz.
        clearTimeout(frm.__auto_calculation_timer);
        (frm.__calc_promise || Promise.resolve()).finally(() => {
            run_jazira_calculation(frm);
        });
        return;
    }

    if (!automatic) {
        // Qo'lda bosilganda navbatda turgan avtomatik hisobni bekor qilamiz —
        // ikki marta ketmasin.
        clearTimeout(frm.__auto_calculation_timer);
    }

    if (!can_calculate(frm, !automatic)) {
        return;
    }

    if (automatic && !is_full_month_period(frm)) {
        return;
    }

    const calculation_key = get_calculation_key(frm);
    if (automatic && frm.__last_auto_calculation_key === calculation_key) {
        return;
    }

    frm.__auto_calculating = true;
    if (automatic) {
        frm.__last_auto_calculation_key = calculation_key;
    }

    return frm.__calc_promise = frm.call({
        doc: frm.doc,
        method: 'calculate',
        args: {
            save: false
        },
        freeze: true,
        freeze_message: automatic ? __('Journal Entrylar olinmoqda...') : __('Hisoblanmoqda...')
    })
        .then(() => {
            frm.refresh_fields();
            frm.dirty();
        })
        .catch((error) => {
            if (automatic) {
                frm.__last_auto_calculation_key = null;
            } else {
                throw error;
            }
        })
        .finally(() => {
            frm.__auto_calculating = false;
        });
}

function schedule_jazira_auto_calculation(frm) {
    if (frm.doc.docstatus !== 0) {
        return;
    }

    clearTimeout(frm.__auto_calculation_timer);
    frm.__auto_calculation_timer = setTimeout(() => {
        run_jazira_calculation(frm, true);
    }, JAZIRA_AUTO_CALCULATE_DELAY);
}

frappe.ui.form.on('Jazira Expense Allocation', {
    setup(frm) {
        // Guruh kompaniyasi ("Jazira") manba bo'la olmaydi — unda operatsiya
        // yo'q, tanlansa hamma raqam 0 chiqib chalg'itardi.
        frm.set_query('expense_source_company', () => ({
            filters: { is_group: 0 }
        }));

        frm.fields_dict.companies.grid.get_field('expense_account').get_query = function(doc, cdt, cdn) {
            const row = locals[cdt][cdn];
            return {
                filters: {
                    company: row.company,
                    root_type: 'Expense',
                    is_group: 0
                }
            };
        };

        frm.fields_dict.companies.grid.get_field('offset_account').get_query = function(doc, cdt, cdn) {
            const row = locals[cdt][cdn];
            return {
                filters: {
                    company: row.company,
                    is_group: 0
                }
            };
        };

        frm.fields_dict.companies.grid.get_field('cost_center').get_query = function(doc, cdt, cdn) {
            const row = locals[cdt][cdn];
            return {
                filters: {
                    company: row.company,
                    is_group: 0
                }
            };
        };

        frm.set_query('source_offset_account', () => ({
            filters: {
                company: frm.doc.expense_source_company,
                is_group: 0
            }
        }));
    },

    onload(frm) {
        frm.trigger('set_default_companies');
        frm.trigger('fill_default_clearing_account');
    },

    refresh(frm) {
        frm.trigger('set_default_companies');
        frm.trigger('fill_default_clearing_account');
        frm.trigger('lock_companies_grid');

        if (frm.doc.docstatus === 0) {
            frm.add_custom_button(__('Hisoblash'), () => {
                run_jazira_calculation(frm);
            }).addClass('btn-primary');
        }
    },

    from_date(frm) {
        frm.trigger('clear_calculation');
        schedule_jazira_auto_calculation(frm);
    },

    to_date(frm) {
        if (frm.doc.to_date) {
            frm.set_value('posting_date', frm.doc.to_date);
        }
        frm.trigger('clear_calculation');
        schedule_jazira_auto_calculation(frm);
    },

    expense_source_company(frm) {
        frm.set_value('source_offset_account', '');
        frm.trigger('fill_default_clearing_account');
        frm.trigger('clear_calculation');
        schedule_jazira_auto_calculation(frm);
    },

    // Clearing account'ni foydalanuvchi qo'lda tanlamasin — kompaniya
    // tanlangan zahoti standart hisob avtomatik qo'yiladi (kerak bo'lsa
    // keyin o'zgartirsa bo'ladi).
    fill_default_clearing_account(frm) {
        if (!frm.doc.expense_source_company || frm.doc.docstatus !== 0) {
            return;
        }
        if (frm.doc.source_offset_account) {
            return;
        }
        frappe.call({
            method: 'jazira_app.jazira_app.doctype.jazira_expense_allocation.jazira_expense_allocation.get_default_clearing_account',
            args: { company: frm.doc.expense_source_company },
            callback(r) {
                if (r.message && !frm.doc.source_offset_account) {
                    frm.set_value('source_offset_account', r.message);
                }
            }
        });
    },

    create_source_reversal(frm) {
        frm.trigger('clear_calculation');
        schedule_jazira_auto_calculation(frm);
    },

    profit_source(frm) {
        frm.trigger('clear_calculation');
        schedule_jazira_auto_calculation(frm);
    },

    set_default_companies(frm) {
        if (!frm.is_new()) {
            return;
        }

        const current_companies = (frm.doc.companies || []).map((row) => row.company);
        const already_set = current_companies.length === JAZIRA_ALLOCATION_COMPANIES.length
            && JAZIRA_ALLOCATION_COMPANIES.every((company, index) => current_companies[index] === company);

        if (already_set) {
            return;
        }

        frm.clear_table('companies');
        JAZIRA_ALLOCATION_COMPANIES.forEach((company) => {
            frm.add_child('companies', { company });
        });
        frm.refresh_field('companies');
    },

    lock_companies_grid(frm) {
        const grid = frm.fields_dict.companies && frm.fields_dict.companies.grid;
        if (!grid) {
            return;
        }

        grid.cannot_add_rows = true;
        grid.df.cannot_add_rows = true;
        grid.df.cannot_delete_rows = true;
        grid.refresh();
    },

    clear_calculation(frm) {
        if (frm.doc.docstatus !== 0 || frm.is_new()) {
            return;
        }

        frm.set_value('status', 'Draft');
    }
});

frappe.ui.form.on('Jazira Expense Allocation Company', {
    company(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        row.expense_account = '';
        row.offset_account = '';
        row.cost_center = '';
        frm.refresh_field('companies');
    }
});
