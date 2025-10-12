# app1/matching.py
from decimal import Decimal

def _get_attr(metrics_obj, field):
    # allows nested like "project_type"
    return getattr(metrics_obj, field, None)

def _coerce(lhs, rhs):
    # best-effort numeric coercion where possible
    def num(x):
        try:
            if x is None or x == '':
                return None
            return Decimal(str(x))
        except Exception:
            return None
    nl, nr = num(lhs), num(rhs)
    if nl is not None and nr is not None:
        return nl, nr
    return str(lhs).lower() if lhs is not None else None, str(rhs).lower() if rhs is not None else None

def matches_intervention(metrics_row, rules):
    """
    Return True if ALL rules for the intervention pass for this metrics row.
    """
    if not rules:
        return True

    for r in rules:
        lhs = _get_attr(metrics_row, r.field_name)
        op  = r.operator
        rhs_raw = r.value or ''
        # pre-parse RHS lists for in/nin
        rhs_list = [v.strip().lower() for v in rhs_raw.split(',')] if op in ('in','nin') else None

        # booleans / emptiness
        if op == 'true':   ok = bool(lhs) is True
        elif op == 'false': ok = bool(lhs) is False
        elif op == 'empty':  ok = (lhs in (None, '', 0))
        elif op == 'nempty': ok = (lhs not in (None, '', 0))

        # string contains (case-insensitive)
        elif op == 'contains':    ok = (str(rhs_raw).lower() in (str(lhs or '').lower()))
        elif op == 'ncontains':   ok = (str(rhs_raw).lower() not in (str(lhs or '').lower()))

        # set membership
        elif op == 'in':   ok = (str(lhs).lower() in rhs_list if lhs is not None else False)
        elif op == 'nin':  ok = (str(lhs).lower() not in rhs_list if lhs is not None else True)

        else:
            L, R = _coerce(lhs, rhs_raw)
            if op == 'eq':   ok = (L == R)
            elif op == 'neq': ok = (L != R)
            elif op == 'gt':  ok = (L is not None and R is not None and L >  R)
            elif op == 'gte': ok = (L is not None and R is not None and L >= R)
            elif op == 'lt':  ok = (L is not None and R is not None and L <  R)
            elif op == 'lte': ok = (L is not None and R is not None and L <= R)
            else:             ok = True  # fail-open for unknown op to avoid hiding items silently

        if not ok:
            return False

    return True
