import os, json, statistics, datetime as dt

SUPPLIERS_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'suppliers.json')
DELIVERIES_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'supplier_deliveries.json')


def _load(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return []


def _write(path, data):
    parent = os.path.dirname(path)
    if not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=2)


def compute_supplier_metrics():
    suppliers = _load(SUPPLIERS_PATH)
    deliveries = _load(DELIVERIES_PATH)
    supplier_map = {s.get('name'): s for s in suppliers}
    grouped = {}
    for d in deliveries:
        name = d.get('supplier_name')
        grouped.setdefault(name, []).append(d)

    for name, items in grouped.items():
        on_time_vals = [1 if i.get('on_time') else 0 for i in items if i.get('on_time') is not None]
        on_time_rate = sum(on_time_vals) / len(on_time_vals) if on_time_vals else None
        deltas = []
        prices = []
        for i in items:
            sa = i.get('scheduled_at')
            da = i.get('delivered_at')
            if sa and da:
                try:
                    t1 = dt.datetime.fromisoformat(sa.replace('Z',''))
                    t2 = dt.datetime.fromisoformat(da.replace('Z',''))
                    deltas.append((t2 - t1).total_seconds() / 3600.0)
                except Exception:
                    pass
            if isinstance(i.get('price'), (int, float)):
                prices.append(i.get('price'))
        avg_delivery_time = statistics.mean(deltas) if deltas else None
        price_variance = statistics.pstdev(prices) if len(prices) > 1 else 0.0
        reliability_score = (on_time_rate or 0.0) * 100
        supplier = supplier_map.get(name)
        if supplier is not None:
            supplier['reliability_score'] = reliability_score
            supplier['avg_delivery_time'] = avg_delivery_time
            supplier['price_variance_index'] = price_variance

    # write back
    if suppliers:
        _write(SUPPLIERS_PATH, suppliers)
    return True
