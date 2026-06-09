// Purchase Invoice — item kiritishda faqat «Сырьё» (xom-ashyo) guruhidagi itemlar
frappe.ui.form.on('Purchase Invoice', {
    refresh(frm) {
        frm.set_query('item_code', 'items', () => ({
            filters: { item_group: 'Сырьё' }
        }));
    }
});
