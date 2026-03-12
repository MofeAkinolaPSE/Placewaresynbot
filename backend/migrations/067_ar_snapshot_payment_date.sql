-- Migration 067: Add payment_date column to sage_ar_snapshot
-- Enables invoice-to-payment cycle calculation when a Sage AR export
-- includes actual payment dates.  Populated as NULL initially; filled
-- when the CSV contains a paid_date field.

ALTER TABLE public.sage_ar_snapshot
  ADD COLUMN IF NOT EXISTS payment_date date;
