from decimal import Decimal
import pytest
from repstm.parser import timestamp,number,text,fiscal_year,cell_number,integer_count


def test_local_calendar_and_fiscal_boundary():
    assert timestamp('30/09/2569 23:59:59')=='2026-09-30T23:59:59+07:00'
    assert timestamp('01/10/2026')=='2026-10-01T00:00:00+07:00'
    assert timestamp('29/02/2563')=='2020-02-29T00:00:00+07:00'
    assert timestamp('2563-02-29')=='2020-02-29T00:00:00+07:00'
    assert fiscal_year('2026-09-30')==2569
    assert fiscal_year('2026-10-01')==2570
    assert fiscal_year(None) is None
    with pytest.raises(ValueError):timestamp('31/02/2569')

def test_exact_money_and_identifiers():
    assert text('00000123')=='00000123'
    assert number('0')=='0'
    assert number('-') is None
    assert number('') is None
    assert Decimal(number('(1,234.5678)'))==Decimal('-1234.5678')
    assert Decimal(number('0.1'))+Decimal(number('0.2'))==Decimal('0.3')
    for v in ('NaN','Infinity','C','100%'):
        with pytest.raises(ValueError):number(v)

def test_excel_errors_and_date_cells_are_not_treated_as_money():
    from types import SimpleNamespace
    import xlrd
    class Sheet:
        ncols=1
        def __init__(self,ctype,value):self.value=SimpleNamespace(ctype=ctype,value=value)
        def cell(self,row,col):return self.value
    for kind in (xlrd.XL_CELL_ERROR,xlrd.XL_CELL_DATE,xlrd.XL_CELL_BOOLEAN):
        with pytest.raises(ValueError):cell_number(Sheet(kind,7),0,0)
    assert cell_number(Sheet(xlrd.XL_CELL_NUMBER,0),0,0)=='0'
    assert cell_number(Sheet(xlrd.XL_CELL_EMPTY,''),0,0) is None
    assert integer_count('12.0')==12
    assert integer_count('') is None
    with pytest.raises(ValueError):integer_count('12.5')

def test_numeric_identifiers_respect_excel_zero_mask():
    from types import SimpleNamespace
    import xlrd
    from repstm.parser import identifier
    class Sheet:
        ncols=1
        book=SimpleNamespace(xf_list=[SimpleNamespace(format_key=0)],format_map={0:SimpleNamespace(format_str='000000')})
        def cell(self,row,col):return SimpleNamespace(ctype=xlrd.XL_CELL_NUMBER,value=123.0)
        def cell_xf_index(self,row,col):return 0
    assert identifier(Sheet(),0,0)=='000123'
