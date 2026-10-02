"""Generate approved-layout BIFF fixtures. Dev-only xlwt, no patient inputs."""
from pathlib import Path
import xlwt
from repstm.parser import APPROVED_LAYOUTS


def write_rep(path, rows=500, item_sheets=2, rep_no='990001'):
    book=xlwt.Workbook()
    detail=next(x for x in APPROVED_LAYOUTS.values() if x['kind']=='rep_claims' and x['width']==59)
    drug=next(x for x in APPROVED_LAYOUTS.values() if x['kind']=='rep_drug_items' and x['width']==22)
    def sheet(name,layout):
        sh=book.add_sheet(name)
        for col,label in enumerate(layout['header_paths']):sh.write(layout['header_row']-1,col,label)
        return sh
    sh=sheet('Detail',detail)
    for n in range(1,rows+1):
        values={0:rep_no,1:str(n),2:f'SYNTHETIC-T{n:06}',3:f'{n:07}',4:f'SYNTHETIC-AN{n:06}',
                5:f'SYNTHETIC-PID{n:06}',6:'ผู้ป่วยจำลอง',7:'IP',8:'01/01/2569',9:'05/01/2569',
                10:'8.001',11:'1.999',28:'1.000',29:'10.000'}
        for col,value in values.items():sh.write(detail['data_start_row']-2+n,col,value)
    for index in range(item_sheets):
        sh=sheet('Data Drug' if index==0 else f'Data Drug ({index+1})',drug)
        for n in range(1,rows+1):
            values={0:str(n),1:f'SYNTHETIC-T{n:06}',2:f'{n:07}',3:f'SYNTHETIC-AN{n:06}',
                    4:'01/01/2569',5:f'SYNTHETIC-PID{n:06}',6:'ผู้ป่วยจำลอง',7:str(index+1),
                    8:'0000123',9:'0000456',10:'ยาจำลอง',15:'2',16:'1.125',17:'2.250',19:'-0.0012',21:''}
            for col,value in values.items():sh.write(drug['data_start_row']-2+n,col,value)
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);book.save(str(path))
    return path
