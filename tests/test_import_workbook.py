"""Synthetic workbook cells exercise continuation sheets without patient files."""
from pathlib import Path
from types import SimpleNamespace
from decimal import Decimal
import xlrd

from repstm.parser import APPROVED_LAYOUTS,parse_file


class Sheet:
    def __init__(self,name,layout,changed=False):
        self.name=name;self.ncols=layout['width'];self.merged_cells=[]
        self.values=[['']*self.ncols for _ in range(layout['data_start_row'])]
        headers=list(layout['header_paths'])
        if changed:headers[19]='Unverified compensation field'
        self.values[layout['header_row']-1]=headers
        row=['']*self.ncols
        row[:11]=['1','DEMO-TRAN','000001','DEMO-AN','29/09/2569','DEMO-PID','ผู้ป่วยจำลอง','1','DEMO-DRUG','DEMO-TMT','ยาจำลอง']
        row[15:22]=['2','1.125','2.250','1.000','-0.0012','','0']
        self.values[layout['data_start_row']-1]=row;self.nrows=len(self.values)
    def row_values(self,row):return self.values[row]
    def cell_value(self,row,col):return self.values[row][col]
    def cell_type(self,row,col):return xlrd.XL_CELL_TEXT if self.cell_value(row,col)!='' else xlrd.XL_CELL_EMPTY
    def cell(self,row,col):return SimpleNamespace(value=self.cell_value(row,col),ctype=self.cell_type(row,col))


class Book:
    datemode=0
    def __init__(self,sheets):
        self.sheets=sheets;self.nsheets=len(sheets)
        for sheet in sheets:sheet.book=self
    def sheet_by_index(self,index):return self.sheets[index]
    def unload_sheet(self,index):pass
    def release_resources(self):pass


def workbook(monkeypatch,changed=False):
    layout=next(l for l in APPROVED_LAYOUTS.values() if l['kind']=='rep_drug_items' and l['width']==22)
    book=Book([Sheet('Data Drug',layout,changed),Sheet('Data Drug (2)',layout,changed)])
    monkeypatch.setattr('repstm.parser.xlrd.open_workbook',lambda *a,**k:book)
    return parse_file(Path('eclaim_10929_IP_APPEAL_NHSO_25691002_010101000.xls'))


def test_drug_continuation_provenance_and_exact_signed_money(monkeypatch):
    result=workbook(monkeypatch)
    assert not [i for i in result['issues'] if i['severity']=='error']
    groups=result['groups']
    assert len(groups)==2 and {g['sheet_index'] for g in groups}=={0,1}
    assert all(g['kind']=='rep_drug_items' and len(g['rows'])==1 for g in groups)
    for group in groups:
        row=dict(zip(group['columns'],group['rows'][0]))
        assert row['hn']=='000001' and row['full_name']=='ผู้ป่วยจำลอง'
        assert Decimal(row['compensation_amount'])==Decimal('-0.0012')
        assert row['admitted_at'].startswith('2026-09-29')


def test_changed_financial_header_is_quarantined(monkeypatch):
    result=workbook(monkeypatch,True)
    assert any(i['severity']=='error' for i in result['issues'])
    assert all(g['kind']=='unmapped_rows' for g in result['groups'])
