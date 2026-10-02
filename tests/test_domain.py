from datetime import date
from decimal import Decimal
import pytest
from financial.domain import number, identifier, cost, fiscal_year, fiscal_range, money_sum, ratio, aging, scenario, backtest
from financial.normalize import normalize
from financial.rules import evaluate
from financial.db import literal, canonical

@pytest.mark.parametrize('value',[True,'NaN','Infinity','abc'])
def test_invalid_decimal(value):
    with pytest.raises(ValueError):number(value)

def test_decimal_blank_zero_negative():
    assert number('') is None and number('0')==0
    assert money_sum([None,None]) is None
    assert money_sum(['1.123456','-0.123456',None])=='1.000000'
    assert identifier('000001')=='000001'
    with pytest.raises(ValueError):identifier(1)

def test_cost_needs_definition():
    assert cost('10','2','8')['observed_item_cost'] is None
    assert cost('10','2','8')['estimated_item_cost']=='16'
    assert cost('10','2',None,'unit','review')['observed_item_cost']=='20'
    assert cost('10','2',None,'line','review')['observed_item_cost']=='10'
    assert cost('0','2',None,'line','review')['observed_item_cost']=='0'
    with pytest.raises(ValueError):cost('10','2',None,'unit')

def test_fy_and_unknown_denominator():
    assert fiscal_year(date(2026,10,1))==2570
    assert fiscal_year(date(2026,9,30))==2569
    assert fiscal_range(2570)==(date(2026,10,1),date(2027,9,30))
    assert ratio(1,0) is None and ratio(1,None) is None and ratio(1,2,False) is None
    assert aging(None,date.today())['bucket']=='UNKNOWN'

def test_normalize_preserves_income_category_and_invalid_time():
    row=normalize('lines',{'source_key':'x','hn':'00001','income':'02','cost':'1.001','qty':'0'})
    assert row['payload']['income']=='02' and row['payload']['cost']=='1.001'
    bad=normalize('ip',{'source_key':'x','an':'000001','regdate':'2026-01-01','regtime':'garbage'})
    assert bad['payload']['_admitted_at'] is None and bad['payload']['_issues']
    good=normalize('op',{'source_key':'x','vn':'000123','vstdate':'2026-01-01','vsttime':'12:00:00'})
    assert good['payload']['_admitted_at'].endswith('+07:00')

def test_rule_applicability_never_inferred():
    case={'service_date':'2026-01-01','care_type':'OP','nhso_code':'SYNTHETIC','adjrw':'1','grouper_version':'1'}
    assert evaluate(case,[],[])['required'] is None
    rule={'id':'r','verification':'applicability_verified','review_reference':'SIMULATED','authority_url':'https://example.invalid/rule','authority_clause':'1','care_type':'OP','payer_code':'SYNTHETIC','effective_from':'2026-01-01','effective_to':'2026-12-31','definition':{'claim_requirement':'BUNDLED'}}
    assert evaluate(case,[],[rule])['required'] is False
    assert evaluate(case,[],[rule,rule])['required'] is None
    rule['definition']={'claim_requirement':'SEPARATE_REQUIRED','amount_model':'UNIT_RATE','rates':{'X':'1.25'}}
    assert evaluate(case,[{'billcode':'X','quantity':'2'}],[rule],True)['expected_amount']=='2.50'
    assert evaluate(case,[{'billcode':'X','quantity':'2'}],[rule],False)['expected_amount'] is None

def test_forecast_gates_and_backtest():
    rows=[{'month':f'{2024+i//12}-{i%12+1:02}','value':str(100+i%12),'complete':True} for i in range(24)]
    assert backtest(rows[:23])['prediction'] is None
    assert backtest(rows)['method']=='seasonal_naive'
    assert backtest(rows)['seasonal_mae']=='0'
    assert backtest(rows[:12]+rows[13:])['reason']=='MONTHS_NOT_CONSECUTIVE'
    rows[5]['complete']=False
    assert backtest(rows)['prediction'] is None

def test_sql_literal_and_json_are_safe():
    assert "' DROP" not in literal("' DROP TABLE test; --")
    assert canonical({'เงิน':Decimal('0.001')})=='{"เงิน":"0.001"}'
    with pytest.raises(TypeError):canonical(object())

def test_scenario_explicit_unknowns():
    assert scenario('10','2.25',None)['charge_amount']=='22.50'
    assert scenario('10',None,None)['item_cost_amount'] is None
    with pytest.raises(ValueError):scenario('1.5','1','2')
    with pytest.raises(ValueError):scenario('1','-1','2')
def test_unavailable_his_is_unknown_not_zero():
    from financial.repository import protect_denominators
    counts=dict(encounters=0,patients=0,op_visits=0,linked_admission_visits=0,ip_admissions=0,missing_hn=0,missing_pdx=0,total_adjrw=None,avg_los=None,cmi=None)
    result=protect_denominators(counts,{'coverage':{'op':{'state':'unavailable'},'ip':{'state':'unavailable'}}})
    assert result['encounters'] is None and result['op_visits'] is None and result['ip_admissions'] is None
    assert result['observed_counts']['encounters']==0
    full=dict(counts);full.update(result['observed_counts'])
    assert protect_denominators(full,{'coverage':{'op':{'state':'complete'},'ip':{'state':'complete'}}})['encounters']==0

def test_readmission_requires_admission_scope_and_local_time_window():
    from financial.repository import Repository
    from financial.config import Settings
    from types import SimpleNamespace
    import uuid
    repo=Repository(Settings());repo.db=lambda:SimpleNamespace(rows=lambda _:[])
    snap={'dend':'2026-09-29','coverage':{'ip':{'state':'complete','read_started_at':'2026-10-01T00:00:00+00:00','admission_dates_covered':True}}}
    repo.snapshot=lambda _:snap
    case={'id':1,'care_type':'IP','identity_status':'unique','discharged_at':'2026-09-01 18:00:00+00:00','hn':'DEMO-HN','hcode':'10929','snapshot_id':str(uuid.uuid4())}
    assert repo.readmission(case)['observed'] is None # Window ends Sep 30 in Bangkok.
    snap['dend']='2026-09-30'
    assert repo.readmission(case)['observed'] is False
    snap['coverage']['ip']['read_started_at']='2026-09-29T17:00:00+00:00'
    assert repo.readmission(case)['observed'] is None # Midnight is before 01:00 end.
    snap['coverage']['ip'].update(read_started_at='2026-10-01T00:00:00+00:00',admission_dates_covered=False)
    assert repo.readmission(case)['observed'] is None # Discharge-only datasets miss later discharges.
