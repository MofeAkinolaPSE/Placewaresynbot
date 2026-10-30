/** "Ship via" on every invoice form - Sage's list (Airborne, Courier, Hand Delivery, Cust. Pickup, UPS Ground ...),
 *  kept in Maintain -> Shipping methods. A value already on an invoice that is no longer listed still shows. */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";

const FALLBACK = ["Airborne", "Courier", "Hand Delivery", "Cust. Pickup", "UPS Ground", "UPS Red", "UPS Blue", "US Mail", "Fed-EX", "Best Way"];

export function useShipMethods(): string[] {
  const { data } = useQuery({ queryKey: ["ship-methods"], queryFn: () => api.frontdesk.shipMethods(), staleTime: 5 * 60_000 });
  return data?.methods?.length ? data.methods : FALLBACK;
}

export function ShipViaSelect({ value, onChange, className = "" }: { value: string; onChange: (v: string) => void; className?: string }) {
  const methods = useShipMethods();
  const opts = value && !methods.includes(value) ? [value, ...methods] : methods;
  return (
    <select aria-label="Ship via" className={`h-10 w-full rounded-md px-3 text-sm ${className}`} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">Choose…</option>
      {opts.map((m) => <option key={m} value={m}>{m}</option>)}
    </select>
  );
}
