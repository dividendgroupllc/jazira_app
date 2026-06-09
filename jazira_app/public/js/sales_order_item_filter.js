// Sales Order — item kiritishda «Полуфабрикат» va «Сырьё» guruhidagi itemlar
frappe.ui.form.on('Sales Order', {
    refresh(frm) {
        frm.set_query('item_code', 'items', () => ({
            filters: { item_group: ['in', ['Полуфабрикат', 'Сырьё']] }
        }));
    }
});
