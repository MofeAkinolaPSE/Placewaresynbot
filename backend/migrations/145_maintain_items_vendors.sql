-- 27 Oct 2026: Maintain (as Sage's Maintain menu) - the item and vendor fields Sage keeps that ACE
-- Books did not: Maintain Inventory Items (reorder quantity, preferred vendor, UPC / SKU, part number,
-- location, weight, price levels) and Maintain Vendors (account number, expense account, second
-- telephone, fax, web site). Registering an incoming batch now records its supplier and the
-- supplier's invoice number, so the batch and the supplier bill finance records are one delivery.
ALTER TABLE fin_products ADD COLUMN IF NOT EXISTS reorder_qty           numeric(18,4);
ALTER TABLE fin_products ADD COLUMN IF NOT EXISTS preferred_supplier_id uuid;
ALTER TABLE fin_products ADD COLUMN IF NOT EXISTS upc                   text;
ALTER TABLE fin_products ADD COLUMN IF NOT EXISTS part_number           text;
ALTER TABLE fin_products ADD COLUMN IF NOT EXISTS location              text;
ALTER TABLE fin_products ADD COLUMN IF NOT EXISTS weight                numeric(14,3);
ALTER TABLE fin_products ADD COLUMN IF NOT EXISTS price_levels          jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE fin_products ADD COLUMN IF NOT EXISTS updated_at            timestamptz;

ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS account_number        text;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS expense_account_code  text;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS telephone_2           text;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS fax                   text;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS website               text;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS updated_at            timestamptz;

ALTER TABLE nafdac_batch_registry ADD COLUMN IF NOT EXISTS supplier_id              uuid;
ALTER TABLE nafdac_batch_registry ADD COLUMN IF NOT EXISTS supplier_invoice_number  text;
ALTER TABLE nafdac_batch_registry ADD COLUMN IF NOT EXISTS unit_cost                numeric(20,4);
ALTER TABLE nafdac_batch_registry ADD COLUMN IF NOT EXISTS manufacture_date         date;

-- Ship via (Sage's list), offered on every invoice form; finance adds or removes methods in Maintain.
ALTER TABLE fin_settings ADD COLUMN IF NOT EXISTS ship_methods jsonb NOT NULL
    DEFAULT '["Airborne","Courier","Hand Delivery","Cust. Pickup","UPS Ground","UPS Red","UPS Blue","US Mail","Fed-EX","Best Way"]'::jsonb;
