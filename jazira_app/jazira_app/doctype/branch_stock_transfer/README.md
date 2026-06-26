# Branch Stock Transfer (Filial Tovar O'tkazmasi)

Filial **kompaniyalar** o'rtasida tovarni **TAN NARXDA (ustamasiz)** ko'chiradi va
orqada inter-company hujjatlarni avtomatik yaratadi.

## Oqim

```
Branch Stock Transfer (submit)
        │
        ├─► Sales Invoice   (from_company, update_stock=1)  → from_warehouse'dan CHIQIM
        │        │  customer = Internal Customer (represents to_company)
        │        ▼
        └─► Purchase Invoice (to_company,  update_stock=1)  → to_warehouse'ga KIRIM
                 supplier = Internal Supplier (represents from_company)
                 make_inter_company_purchase_invoice(SI) orqali bog'lanadi
```

- Narx **doimo valuation rate (tan narx)**, **ustamasiz** → SI va PI summalari teng.
- Bu DocType **faqat filial→filial** uchun. Markaziy *Sklad → filial* (15% ustamali)
  oqimi alohida (`ury.ury.hooks.sklad_sales_order`).

## O'rnatish

```bash
bench --site <sayt> migrate          # DocType'lar yuklanadi
bench --site <sayt> clear-cache
bench build --app jazira_app         # client JS uchun (ixtiyoriy)
```

## Talab qilinadigan sozlama (bir martalik)

Har bir kompaniya uchun:
- **Internal Customer**: `is_internal_customer=1`, `represents_company=<kompaniya>`,
  va "Allowed To Transact With" da sotuvchi kompaniyalar.
- **Internal Supplier**: `is_internal_supplier=1`, `represents_company=<kompaniya>`,
  va "Allowed To Transact With" da xaridor kompaniyalar.

Bular bo'lmasa, submit'da aniq xato beradi.

## Foydalanish

1. **Branch Stock Transfer → New**.
2. `from_company` / `from_warehouse` (sotuvchi), `to_company` / `to_warehouse` (xaridor).
3. Qator qo'shing:
   - **Item**: oddiy tovar — `item_code`, `qty`.
   - **BOM**: yarim tayyor — `bom`, `bom_qty`. Submit'da (yoki *"BOM'larni portlat"*
     tugmasida) komponentlariga **bir pog'onali** yoyiladi.
4. **Save** → narxlar (tan narx) avtomatik to'ladi.
5. **Submit** → SI + PI yaratiladi va submit qilinadi.
6. **Cancel** → avval PI, keyin SI bekor qilinadi.

## Maydonlar (asosiy)

| Maydon | Izoh |
|--------|------|
| `price_basis` | Valuation Rate (default) / Last Purchase Rate / Manual |
| `items[].source_type` | Item yoki BOM |
| `items[].from_bom` | Portlatilgan qator qaysi BOM'dan kelgani |
| `sales_invoice` / `purchase_invoice` | Yaratilgan hujjatlar (read-only) |
| `status` | Draft / Completed / Cancelled |

## Test

```bash
bench --site jazira.local2 run-tests --module \
  "jazira_app.jazira_app.doctype.branch_stock_transfer.test_branch_stock_transfer"
```

Testlar mavjud kompaniyalar/stok/internal partiyalarga tayanadi; topilmasa SKIP bo'ladi.
