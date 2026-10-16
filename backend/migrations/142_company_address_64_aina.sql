-- 16 Oct 2026: the company's address is 64, Aina Street, Ojodu, Lagos (not 72). The default in code
-- is corrected; this fixes an invoice layout already saved in Setup that still carries 72.
UPDATE fin_settings
   SET invoice_layout = regexp_replace(invoice_layout::text, '\m72(,?\s*Aina\s+Str)', '64\1', 'gi')::jsonb,
       updated_at = now()
 WHERE invoice_layout IS NOT NULL
   AND invoice_layout::text ~* '\m72,?\s*Aina\s+Str';
