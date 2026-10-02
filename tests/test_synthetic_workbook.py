from scripts.synthetic_workbook import write_rep
from repstm.parser import parse_file
from decimal import Decimal


def test_real_biff_continuation_fixture(tmp_path):
    path=write_rep(tmp_path/'eclaim_10929_IP_25690108_010101000.xls',25)
    parsed=parse_file(path)
    assert not [x for x in parsed['issues'] if x['severity']=='error']
    assert sum(len(g['rows']) for g in parsed['groups'])==75
    for group in parsed['groups']:
        row=dict(zip(group['columns'],group['rows'][0]))
        assert row['hn']=='0000001'
        if group['kind']=='rep_drug_items':
            assert row['item_code']=='0000123' and Decimal(row['compensation_amount'])==Decimal('-0.0012')
