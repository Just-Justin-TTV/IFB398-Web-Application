from typing import Any, Dict

def _to_num(x):
    try:
        return float(str(x))
    except Exception:
        return None

def metric_get(metrics: Dict[str, Any], key: str):
    """
    Supports raw keys like 'gifa_m2' and derived ratios like 'external_openings_m2/external_wall_area_m2'.
    Accepts either a dict (values() from your Metrics model) or a model instance with attributes.
    """
    if "/" in key:
        num_key, den_key = key.split("/", 1)
        num = _to_num(getattr(metrics, num_key, None) if hasattr(metrics, num_key) else metrics.get(num_key))
        den = _to_num(getattr(metrics, den_key, None) if hasattr(metrics, den_key) else metrics.get(den_key))
        if num is None or den in (None, 0):
            return None
        return num / den
    # normal field
    return getattr(metrics, key, None) if hasattr(metrics, key) else metrics.get(key)

def _cmp(val, op: str, target_raw: str):
    op = op.lower()
    # booleans
    if isinstance(val, bool):
        tgt = str(target_raw).strip().lower() in ("true","1","yes","y")
        return (val == tgt) if op in ("eq","=") else (val != tgt)

    # strings (building_type contains)
    if isinstance(val, str):
        v = val.lower().strip()
        t = str(target_raw).lower().strip()
        if op in ("contains",):
            return t in v
        if op in ("eq","="):
            return v == t
        if op in ("neq","!="):
            return v != t
        # try numeric compare if both look numeric
        try:
            val = float(v); target = float(t)
        except Exception:
            return False
    else:
        target = _to_num(target_raw)

    if val is None or target is None:
        return False

    if op == "gt":  return val >  target
    if op == "gte": return val >= target
    if op == "lt":  return val <  target
    if op == "lte": return val <= target
    if op in ("eq","="):  return val == target
    if op in ("neq","!="):return val != target
    return False

def matches_intervention(metrics_obj_or_dict, rules):
    """
    All rules must be satisfied (AND semantics).
    """
    for r in rules:
        key, op, val = r.metric_key, r.operator, r.value
        current = metric_get(metrics_obj_or_dict, key)
        if not _cmp(current, op, val):
            return False
    return True
