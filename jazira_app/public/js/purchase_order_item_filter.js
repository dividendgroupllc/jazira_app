// Purchase Order — item kiritishda «Полуфабрикат» va «Сырьё» guruhidagi itemlar
frappe.ui.form.on('Purchase Order', {
    refresh(frm) {
        frm.set_query('item_code', 'items', () => ({
            filters: { item_group: ['in', ['Полуфабрикат', 'Сырьё']] }
        }));
    }
});
