from __future__ import annotations

from datetime import date
from decimal import Decimal
from .domain import number


def evaluate(case, lines, rules, lines_complete=False):
    """Only reviewed applicable policy can establish a claim denominator."""
    service = case.get('service_date')
    if not service:
        return {'status':'REVIEW','reason':'SERVICE_DATE_MISSING','required':None,'expected_amount':None}
    applicable = [r for r in rules if r.get('verification')=='applicability_verified'
                  and r.get('review_reference') and r.get('authority_url') and r.get('authority_clause')
                  and r.get('care_type')==case.get('care_type') and r.get('payer_code')==case.get('nhso_code')
                  and str(r['effective_from'])[:10]<=str(service)[:10]<=str(r['effective_to'])[:10]]
    if not applicable:
        return {'status':'REVIEW','reason':'NO_VERIFIED_APPLICABLE_RULE','required':None,'expected_amount':None}
    if len(applicable)!=1:
        return {'status':'REVIEW','reason':'RULE_OVERLAP','required':None,'expected_amount':None}
    rule=applicable[0]
    definition=rule['definition']
    if isinstance(definition,str):
        import json
        definition=json.loads(definition)
    requirement=definition.get('claim_requirement')
    if requirement not in ('SEPARATE_REQUIRED','BUNDLED','NOT_APPLICABLE'):
        return {'status':'REVIEW','reason':'CLAIM_REQUIREMENT_UNVERIFIED','required':None,'expected_amount':None}
    result={'status':'APPLICABLE','rule_id':str(rule['id']),'required':requirement=='SEPARATE_REQUIRED',
            'payment_basis':requirement,'expected_amount':None,'deadline':definition.get('deadline'),
            'submission_channel':definition.get('submission_channel')}
    if requirement!='SEPARATE_REQUIRED':return result
    model=definition.get('amount_model')
    if model=='FIXED_ENCOUNTER':
        result['expected_amount']=str(number(definition['amount']))
    elif model=='UNIT_RATE' and lines_complete:
        rates=definition.get('rates',{})
        components=[]
        for line in lines:
            rate=rates.get(line.get('billcode'))
            if rate is None:continue
            qty=number(line.get('quantity'))
            if qty is None:
                result['amount_reason']='QUANTITY_MISSING';return result
            components.append(qty*number(rate))
        if components:
            result['expected_amount']=str(sum(components,Decimal(0)))
    elif model=='DRG' and definition.get('grouper_version')==case.get('grouper_version') and case.get('adjrw') is not None:
        if definition.get('base_rate') is not None and definition.get('k_factor') is not None:
            result['expected_amount']=str(number(case['adjrw'])*number(definition['base_rate'])*number(definition['k_factor']))
    return result
