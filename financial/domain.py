from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import math


def number(value):
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        raise ValueError('INVALID_NUMBER')
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError('INVALID_NUMBER') from None
    if not result.is_finite():
        raise ValueError('INVALID_NUMBER')
    return result


def identifier(value):
    if value is None or value == '':
        return None
    if isinstance(value, (int, float)):
        raise ValueError('IDENTIFIER_MUST_BE_TEXT')
    return str(value).strip() or None


def fiscal_year(value: date):
    return value.year + 543 + int(value.month >= 10)


def fiscal_range(year_be):
    return date(year_be - 544, 10, 1), date(year_be - 543, 9, 30)


def age_band(years):
    if years is None:
        return None
    return '0–4' if years < 5 else '5–14' if years < 15 else '15–44' if years < 45 else '45–64' if years < 65 else '65+'


def cost(raw_cost, qty, master_cost, semantics='unverified', review=None):
    raw, amount, master = number(raw_cost), number(qty), number(master_cost)
    if semantics not in ('unverified', 'unit', 'line'):
        raise ValueError('INVALID_COST_SEMANTICS')
    if semantics != 'unverified' and not review:
        raise ValueError('COST_REVIEW_REQUIRED')
    observed = raw if semantics == 'line' else raw * amount if semantics == 'unit' and raw is not None and amount is not None else None
    estimate = master * amount if master is not None and amount is not None else None
    return {'observed_item_cost': str(observed) if observed is not None else None,
            'estimated_item_cost': str(estimate) if estimate is not None else None,
            'cost_method': semantics if observed is not None else 'unverified',
            'estimate_method': 'current_master_price' if estimate is not None else None}


def ratio(numerator, denominator, complete=True):
    if not complete or denominator is None or denominator == 0 or numerator is None:
        return None
    return str(Decimal(str(numerator)) / Decimal(str(denominator)))


def money_sum(values):
    present = [number(x) for x in values if x is not None]
    return str(sum(present, Decimal(0))) if present else None


def aging(start: date | None, as_of: date):
    if start is None:
        return {'days': None, 'bucket': 'UNKNOWN'}
    days = (as_of - start).days
    return {'days': days, 'bucket': 'FUTURE' if days < 0 else '0–30' if days <= 30 else '31–60' if days <= 60 else '61–90' if days <= 90 else '>90'}


def percentile(values, fraction):
    ordered = sorted(number(v) for v in values if v is not None)
    if not ordered:
        return None
    index = Decimal(str(fraction)) * (len(ordered) - 1)
    low = int(index)
    high = min(low + 1, len(ordered) - 1)
    return str(ordered[low] + (ordered[high] - ordered[low]) * (index - low))


def peer_summary(cases, field):
    values = [c.get(field) for c in cases if c.get(field) is not None]
    return {'count': len(cases), 'contributing_count': len(values), 'small_sample': len(cases) < 20,
            'median': percentile(values, .5), 'p75': percentile(values, .75), 'p90': percentile(values, .9)}


def scenario(volume, charge_per_case, cost_per_case, verified_recovery_per_case=None):
    n = number(volume)
    if n is None or n < 0 or n != n.to_integral_value():
        raise ValueError('INVALID_VOLUME')
    for value in (charge_per_case, cost_per_case, verified_recovery_per_case):
        if value is not None and (number(value) is None or number(value) < 0):
            raise ValueError('INVALID_SCENARIO_AMOUNT')
    return {'mode': 'scenario_not_forecast', 'volume': int(n),
            'charge_amount': str(n * number(charge_per_case)) if charge_per_case is not None else None,
            'item_cost_amount': str(n * number(cost_per_case)) if cost_per_case is not None else None,
            'potential_recovery': str(n * number(verified_recovery_per_case)) if verified_recovery_per_case is not None else None,
            'net_profit': None}


def backtest(monthly):
    """Rolling-origin comparison; historical observations only, no random split."""
    rows = sorted(monthly, key=lambda r: r['month'])
    keys = [date.fromisoformat(r['month'][:7] + '-01') for r in rows]
    if any((b.year * 12 + b.month) - (a.year * 12 + a.month) != 1 for a, b in zip(keys, keys[1:])):
        return {'status': 'NOT_READY', 'reason': 'MONTHS_NOT_CONSECUTIVE', 'prediction': None}
    if len(rows) < 24 or any(not r.get('complete') or r.get('value') is None for r in rows):
        return {'status': 'NOT_READY', 'reason': 'NEEDS_24_COMPLETE_MONTHS', 'prediction': None}
    expected = []
    naive = []
    for i in range(12, len(rows)):
        actual = number(rows[i]['value'])
        expected.append(abs(actual - number(rows[i - 12]['value'])))
        naive.append(abs(actual - number(rows[i - 1]['value'])))
    seasonal_mae = sum(expected) / len(expected)
    naive_mae = sum(naive) / len(naive)
    winner = 'seasonal_naive' if seasonal_mae <= naive_mae else 'last_month'
    next_value = number(rows[-12]['value']) if winner == 'seasonal_naive' else number(rows[-1]['value'])
    mae = min(seasonal_mae, naive_mae)
    return {'status': 'BACKTESTED_BASELINE', 'method': winner, 'test_months': len(expected),
            'seasonal_mae': str(seasonal_mae), 'last_month_mae': str(naive_mae),
            'prediction': str(next_value), 'error_band': [str(max(Decimal(0), next_value - mae)), str(next_value + mae)],
            'band_kind': 'MAE_scenario_band_not_confidence_interval'}
