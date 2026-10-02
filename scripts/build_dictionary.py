"""Generate dictionaries from schema metadata, never from patient rows."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from financial.config import ROOT, Settings
from financial.db import Database
from financial.queries import DATASETS

MEANING = dict(
 id='รหัสแถวภายในระบบ',source_key='Primary key ต้นทางที่แปลงเป็น text',record_hash='SHA-256 ของ payload หลัง normalize',
 hcode='รหัสสถานพยาบาล',hn='เลขทะเบียนผู้ป่วย',an='เลข admission ผู้ป่วยใน',vn='เลข visit ผู้ป่วยนอก',cid='เลขประจำตัวบุคคล',pid='เลขประจำตัวตามเอกสารเบิก',patient_hn='HN ที่บุคคลอ้างถึง',
 hos_guid='GUID ของแถวต้นทาง',snapshot_id='รหัส snapshot HIS ที่ใช้',job_id='รหัสงานที่อ่าน / นำเข้า',document_id='รหัสฉบับเอกสาร',sheet_id='รหัสชีตต้นทาง',claim_id='รหัสตัวระบุเคลมกลาง',case_id='รหัส encounter ใน snapshot',source_record_id='แถว snapshot ที่ใช้สร้างข้อมูล',rep_claim_id='แถว REP ของรอบที่อ้างถึง',stm_claim_id='แถว STM ที่จับคู่',
 tran_id='TRAN_ID เคลม รักษาศูนย์นำหน้า',rep_no='เลขรอบ REP',document_ref='เลขที่เอกสารภายใน',logical_key='คีย์เอกสารก่อนแยกฉบับ',fingerprint='Fingerprint เนื้อหา ไม่รวมการเปลี่ยนรูปแบบพิมพ์',sha256='SHA-256 ไฟล์ไบนารี',filename='ชื่อไฟล์ต้นทาง',source_path='ตำแหน่งไฟล์ต้นทาง',archive_path='ตำแหน่งไฟล์เก็บย้อนหลัง',storage_path='ตำแหน่งไฟล์ที่รับเข้าคิว',byte_size='ขนาดไฟล์',source='ชนิดต้นทาง REP หรือ STM',status='สถานะตาม state machine ของตาราง',source_row='เลขแถว Excel (1-based)',source_seq='ลำดับรายการที่รายงาน',parent_seq='ลำดับเคลมหลักที่รายการอ้างถึง',sheet_index='ลำดับชีต (0-based)',name='ชื่อรายการ / บุคคล / กฎ ตามตาราง',sheet_name='ชื่อชีต Excel',header_rows='ตำแหน่งแถวหัวตาราง',header_signature='ลายเซ็นหัวตาราง',layout_fingerprint='Fingerprint ของ layout ที่อนุมัติ',mapping_version='รุ่น mapping',row_count='จำนวนแถว',expected_counts='จำนวนรายละเอียดที่คาดจาก parser',source_counts='จำนวนแถวก่อนรวมไฟล์เนื้อหาซ้ำ',is_current='ฉบับที่ใช้ในรายงานปัจจุบัน',version='รุ่นของโครงสร้าง / กฎ',
 created_at='เวลาที่ระบบสร้างแถว',updated_at='เวลาที่แก้ไขล่าสุด',reported_at='เวลารายงานบนเอกสาร ไม่ใช่วันส่งจริง',completed_at='เวลาสร้าง snapshot เสร็จ',captured_at='เวลาที่อ่านแถว HIS พบ',committed_at='เวลาที่บันทึก batch สำเร็จ',finished_at='เวลางานสิ้นสุด',started_at='เวลาเริ่มงาน',installed_at='เวลาติดตั้ง schema',as_of='เวลาของข้อมูลที่รายงานใช้',service_date='OPD วันบริการ / IPD วันจำหน่าย ตาม mapping',statement_month='เดือน statement ไม่ใช่เดือนรับเงิน',month='เดือนตาม basis',basis='ฐานเวลา service หรือ statement',fiscal_year_be='ปีงบประมาณ พ.ศ. ตุลาคมถึงกันยายน',
 encounter_key='IP:AN หรือ OP:VN ภายในโรงพยาบาล',care_type='ชนิด encounter IP หรือ OP',patient_type='ชนิดเคลม IP หรือ OP',payer_family='กลุ่มสิทธิตาม REP/STM',pttype='รหัสสิทธิ ณ encounter',nhso_code='รหัสสิทธิส่งออก สปสช.',linked_an='AN ที่ OP visit เชื่อมไว้ ไม่รวมซ้ำเป็น OP อิสระ',ward='หอผู้ป่วย',department='แผนกบริการ',depcode='รหัสแผนก',dep_code='รหัสแผนกของรายการ',first_ward='หอผู้ป่วยแรก',main_dep='แผนกหลัก OPD',last_dep='แผนกสุดท้าย OPD',
 billed_amount='ยอดเรียกเก็บที่เอกสารรายงาน',expected_amount='ยอดชดเชยที่ REP รายงานตาม mapping',nhso_amount='ยอดชดเชยส่วน สปสช.',employer_amount='ส่วนต้นสังกัดตาม REP',compensation_amount='ชดเชยรวมตามเอกสาร',deduction_amount='รายการหักตาม mapping เก็บเครื่องหมาย',net_amount='ยอดสุทธิที่ parser ยืนยันตาม layout',statement_amount='ยอด STM สุทธิรวมแบบมีเครื่องหมาย',his_summary_charge='ค่าเรียกเก็บสรุป HIS',his_summary_uc='uc_money ตาม HIS ยังไม่เทียบเงินชดเชย',his_summary_paid='paid_money ตาม HIS ยังไม่เทียบเงินโอน',his_summary_remain='remain_money ตาม HIS ยังไม่ยืนยันฐานลูกหนี้',his_charge_amount='ค่าเรียกเก็บ HIS ตามแหล่งที่ coverage ยืนยัน',his_charge_basis='service_lines หรือ his_summary',submitted_amount='ยอดมีหลักฐานส่งล่าสุดต่อองค์ประกอบ',rep_expected_amount='ชดเชย REP ที่เชื่อมเคสได้',rep_nhso_amount='ชดเชยส่วน สปสช. สำหรับเทียบ STM',stm_net_amount='STM สุทธิของเคลมที่จับคู่ไม่คลุมเครือ',cash_received_amount='ยอดเงินรับที่ตรวจหลักฐานและจัดสรรเคส',observed_item_cost='ต้นทุนรายการที่ตรวจความหมาย unit/line แล้ว',estimated_item_cost='ต้นทุนประมาณการจากราคาทะเบียนปัจจุบัน',raw_cost='cost ต้นทาง ไม่คูณ qty จนยืนยัน',cost='cost HIS ความหมายต่อหน่วย/รายการยังไม่ยืนยัน',unitcost='ต้นทุนในทะเบียน ณ อ่านพบ ไม่ถือเป็นราคาย้อนหลัง',sum_price='ค่าเรียกเก็บรวมของรายการ HIS',unitprice='ราคาเรียกเก็บต่อหน่วย',unit_price='ราคาเรียกเก็บต่อหน่วยตามต้นทาง',qty='จำนวนที่ใช้ตามต้นทาง',quantity='จำนวนตามต้นทาง',unit='หน่วยรายการ',units='หน่วยรายการยา drugitems; query ใช้ alias unit',charge_amount='ค่าเรียกเก็บของรายการ HIS',line_charge='ผลรวมค่าเรียกเก็บรายการ ไม่รวมเมื่อมี NULL บางรายการ',cost_coverage_rate='รายการมีต้นทุนยืนยัน / รายการทั้งหมด',cost_semantics='นิยาม cost: unverified, unit, line',cost_method='วิธีต้นทุนที่ใช้กับรายการ',cost_review='เลขที่หลักฐานตรวจความหมายต้นทุน',estimate_as_of='วันที่ราคาประมาณการอ้างถึง',
 income='จำนวนเงินสรุปหรือรหัสหมวดรายได้ ขึ้นกับตาราง',uc_money='ยอดตามฟิลด์ HIS ยังไม่ตีความเป็นชดเชย',paid_money='ยอดตาม HIS ยังไม่ตีความเป็นเงินโอน สปสช.',remain_money='ยอดตาม HIS ยังไม่ยืนยันความหมายลูกหนี้',discount_money='ส่วนลดตาม HIS',paidst='สถานะการชำระตาม codebook HIS',
 rw='Relative weight ตามต้นทาง',adjrw='Adjusted relative weight ตามรุ่น grouper',drg='กลุ่ม DRG',mdc='กลุ่มโรคหลัก DRG',grouper_version='รุ่น grouper',grouper_release='รุ่นย่อย grouper',grouper_err='รหัสผิดพลาด grouper',err='รหัสข้อผิดพลาด',warn='รหัสคำเตือน',pdx='โรคหลัก ใช้เฉพาะ primary diagnosis ที่มีคู่เดียว',icd10='รหัสวินิจฉัย ICD-10',icd9='รหัสหัตถการ IPD',icd9cm='รหัสหัตถการ OPD',diagtype='ชนิดวินิจฉัย ต้องตรวจ codebook',diag_no='ลำดับวินิจฉัย',priority='ลำดับความสำคัญหัตถการ',los='วันจำหน่ายลบวันรับไว้ตามวันที่',dchtype='รหัสประเภทจำหน่าย',dchstts='รหัสสถานะจำหน่าย',nhso_dchtype='รหัสจำหน่ายที่ส่ง สปสช.',nhso_dchstts='รหัสสถานะที่ส่ง สปสช.',identity_status='ผลตรวจ uniqueness ทะเบียนผู้ป่วย',quality='รายละเอียดความผิดปกติที่ตรวจพบ',
 sex='รหัสเพศตาม HIS',birthday='วันเกิดทะเบียน patient',birthdate='วันเกิดทะเบียน person',age_years='อายุปี ณ รับบริการ',age_band='กลุ่มอายุ 0–4/5–14/15–44/45–64/65+',pname='คำนำหน้าชื่อ',fname='ชื่อผู้ป่วย',lname='นามสกุลผู้ป่วย',death='สถานะเสียชีวิตทะเบียน ต้องตรวจ codebook',deathday='วันที่เสียชีวิตทะเบียน',
 vstdate='วันที่บริการ',vsttime='เวลาบริการไทย',regdate='วันรับไว้ IPD',regtime='เวลารับไว้',dchdate='วันจำหน่าย',dchtime='เวลาจำหน่าย',admitted_at='เวลาบริการ OPD / รับไว้ IPD ไทยแปลง timestamptz',discharged_at='เวลาจำหน่าย IPD',begin_date='วันเริ่มสิทธิ',expire_date='วันสิ้นสุดสิทธิ',hospmain='หน่วยบริการหลักตามสิทธิ',hospsub='หน่วยบริการรองตามสิทธิ',project_code='โครงการสิทธิ',claim_service_type_code='ชนิดบริการส่งเบิก',auth_datetime='เวลาการอนุมัติสิทธิ',doctor='รหัสแพทย์ของ encounter',ovstist='รหัสประเภทการมา OPD',ovstost='รหัสจำหน่าย OPD',
 icode='รหัสยา / รายการ HIS',billcode='รหัสเครื่องมือ / เบิกตามต้นทาง',drug_code='รหัสยาตามรายงาน',item_code='รหัสรายการ',item_name='ชื่อรายการต้นทาง',category='กลุ่มรายงานปกติ/อุทธรณ์/รูปแบบ',record_role='หน้าที่แถว reported/result/etc ตาม parser',error_code='รหัส reject / deny ตามแหล่ง',extra_data='ข้อมูลเฉพาะ layout พร้อมตำแหน่งคอลัมน์',raw_data='เซลล์ต้นทางเพื่อย้อนตรวจ',payload='ข้อมูลต้นทางที่ normalize แล้ว / คำสั่งงานตามตาราง',metadata='ข้อมูลประกอบที่มีนิยามตามตาราง',detail='หลักฐานประเด็นที่ตรวจพบ',
 kind='ชนิดงาน / record group',actor_ref='SHA-256 Session ผู้ทำรายการ ไม่ใช่ตัวบุคคลยืนยัน',event='ชื่อเหตุการณ์ audit',object_id='รหัสสิ่งที่ทำรายการ',event_type='SUBMISSION/APPEAL_SENT/CASH_RECEIPT/DEADLINE',occurred_at='เวลาเหตุการณ์จริงตามหลักฐาน',recorded_at='เวลาที่บันทึกหลักฐานเข้าระบบ',source_ref='เลขที่หรืออ้างอิงหลักฐาน',verification='ระดับการตรวจยืนยัน',component_key='องค์ประกอบการส่ง ใช้รอบล่าสุดต่อคีย์',amount='ยอดมีเครื่องหมายตามหลักฐาน',total_amount='ยอดเงินรวมใบรับเพื่อจำกัดการจัดสรร',reason='เหตุผลติดตาม / อุทธรณ์',team='ทีมรับผิดชอบงาน',due_date='วันที่ติดตามถัดไป ไม่ใช่ deadline ตามกฎ',note='หมายเหตุปฏิบัติงาน หลีกเลี่ยงข้อมูลผู้ป่วยเกินจำเป็น',opened_at='เวลาสร้างอุทธรณ์',sent_at='เวลาส่งอุทธรณ์ตามหลักฐาน',outcome='ผลพิจารณาที่ตรวจหลักฐาน',baseline_amount='STM สุทธิที่ตรึงก่อนเปิดอุทธรณ์ของเคลม',baseline_rows='แถวและยอดฐานที่ตรึงไว้',result_rows='IDs แถว STM ที่ยืนยันเป็นผลอุทธรณ์',effect_type='DELTA หรือ REPLACEMENT',incremental_amount='เพิ่ม/ลดจากอุทธรณ์ โดยไม่รวมฐานเดิมซ้ำ',
 owner_id='worker ที่ถือ lease',lease_until='เวลา lease หมดอายุ',pause_requested='คำขอพักระหว่าง batch',progress='ความคืบหน้าที่บันทึกจากงานจริง',result='ผลตรวจจบงาน',error_code_='รหัสปัญหางานที่ไม่เปิดเผย payload',dstart='วันเริ่มขอบเขต HIS',dend='วันสิ้นสุดขอบเขต HIS',coverage='สถานะ/count/ช่วงเวลาที่อ่านแต่ละ dataset',registry_profile='จำนวนทะเบียน patient ทั้งฐาน อ่านแยกจาก encounter',records='จำนวนแถวใน batch',payload_hash='SHA-256 payload สำหรับตรวจ UUID collision',
 method='วิธีจับคู่ตามหลักฐาน',evidence='หลักฐานและ candidate count ของการจับคู่',effective_from='วันเริ่มใช้กฎ',effective_to='วันสิ้นสุดใช้กฎ',payer_code='รหัสสิทธิของกฎ ต้องตรง nhso_code',authority_url='แหล่งประกาศทางการ',authority_clause='ข้อ/หน้าที่รองรับกฎ',review_reference='หลักฐานผู้รับผิดชอบตรวจการใช้กฎ',definition='นิยามกฎและสูตรที่มีรุ่น',legacy_rate='อัตราจาก SQL ตัวอย่างปีเก่า ห้ามใช้เป็นอัตราปัจจุบัน',source_year='ปีของเอกสารต้นทาง',refreshed_at='เวลาปรับ aggregate รายงานล่าสุด',rep_count='จำนวนเคลม REP ที่ผ่านกติกาฉบับ',stm_count='จำนวนรายละเอียด STM ตามงวด',missing_amount_count='จำนวนรายการที่ยอดยังไม่ทราบ',nhso_expected_amount='ส่วนชดเชย สปสช. สำหรับเปรียบเทียบ',
 upload_datetime='เวลาที่ต้นทางระบุ upload ต้องตรวจความสำเร็จก่อนเป็นวันส่งจริง',upload_status_code='รหัสสถานะส่ง',fdh_ready='สถานะพร้อม FDH',send_date='วันที่ส่งตามต้นทาง รอจับคู่หลักฐาน',send_time='เวลาส่งตามต้นทาง',send_done='สถานะส่งสำเร็จต้องตรวจ codebook',data_ok='สถานะข้อมูลครบของต้นทาง',reply_error='ข้อผิดพลาดตอบกลับ',nhso_error_code='รหัสข้อผิดพลาด สปสช.',transaction_uid='รหัส transaction FDH',fdh_act_amt='ยอด FDH ยังไม่ตีความเป็นเงินรับ',fdh_stm_period='งวด STM ที่ FDH อ้างถึง',fdh_claim_status_datetime='เวลาสถานะ FDH',rep_eclaim_detail_rep_no='เลข REP ใน HIS',rep_eclaim_detail_tran_id='TRAN_ID text จาก HIS bridge',rep_eclaim_detail_patient_type='IP/OP ตาม HIS bridge',rep_eclaim_import_datetime='เวลานำ REP เข้า HIS ไม่ใช่วันส่งเคลม',nhso_subinscl='กลุ่มสิทธิย่อยส่งออก',export_eclaim='สถานะส่งออก eclaim',last_update='เวลาปรับต้นทางล่าสุด',last_modified='เวลาปรับรายการล่าสุด',update_datetime='เวลาปรับสถานะ / DRG ล่าสุด'
)
TABLES={
 'ingest.files':('แฟ้มไฟล์ต้นฉบับและ alias','หนึ่ง SHA-256 / ตำแหน่งไฟล์'), 'ingest.documents':('ประวัติฉบับเอกสาร','หนึ่ง logical document + content fingerprint'),
 'ingest.sheets':('mapping ชีตต้นทาง','หนึ่งชีตต่อฉบับ'), 'eclaim.claims':('ตัวระบุเคลมกลาง','HCODE + IP/OP + สิทธิ + TRAN_ID'),
 'his.snapshots':('manifest ขอบเขตการอ่าน HIS','หนึ่งช่วงอ่าน มีสถานะครบแยก dataset'), 'his.records':('แถว HIS ที่ normalize แล้ว','หนึ่ง snapshot + dataset + source PK'),
 'his.cases':('ตัวตั้ง encounter','หนึ่ง snapshot + IP:AN หรือ OP:VN'), 'his.case_lines':('รายการรักษา / ต้นทุน','หนึ่ง opitemrece.hos_guid ใน snapshot'),
 'followup.claim_links':('คู่ HIS–claim พร้อมหลักฐาน','หนึ่งเคลม–encounter ใน snapshot'), 'followup.observations':('หลักฐานเหตุการณ์การเงิน','หนึ่ง UUID เหตุการณ์ มี source_ref'),
 'followup.tasks':('งานและผู้รับผิดชอบ','HCODE + encounter + reason'), 'followup.appeals':('ฐานและผลอุทธรณ์','หนึ่งคำอุทธรณ์ต่อเคลม ไม่ใช่ทุกไฟล์ APPEAL'),
 'followup.receipts':('ยอดรวมหลักฐานโอน / ใบรับ','HCODE + source_ref'), 'followup.rule_packs':('กฎเบิกแบบมีรุ่น','ชื่อ + รุ่น + ช่วงใช้'), 'followup.instrument_catalog':('ทะเบียนเครื่องมือจาก SQL ตัวอย่าง','icode + source_ref'),
 'analytics.case_financials':('ยอดต่อ encounter ที่รวมก่อนเชื่อม','หนึ่ง his.cases.id'), 'analytics.rep_claim_observations':('REP ล่าสุดและ STM สุทธิต่อเคลม','หนึ่ง eclaim.claims.id'),
}

def meaning(name,table):
    if name=='income' and table.endswith('opitemrece'):return 'รหัสหมวดรายได้ char(2) ไม่ใช่จำนวนเงิน'
    return MEANING.get(name) or (f'รหัสแถวต้นทาง {table}' if name.endswith('_id') else f'{name} ตาม metadata ของ {table}; ความหมายทางธุรกิจยังต้องให้เจ้าของข้อมูลยืนยัน')

def field(name,typ,nullable,table,source,key='',description=None):
    financial=typ in ('numeric','decimal') or typ.startswith(('numeric','decimal'))
    unit='บาท (เก็บ signed precision ต้นทาง)' if financial and any(x in name for x in ('amount','money','cost','price','charge','rate')) and name!='cost_coverage_rate' else 'สัดส่วน 0–1' if name=='cost_coverage_rate' else 'จำนวนตามต้นทาง' if name in ('qty','quantity','records','row_count') else 'วัน' if name=='los' else 'ไม่มีหน่วย / รหัส' if typ in ('text','character varying','character') else 'ตามชนิดข้อมูล'
    sensitive=name in ('hn','cid','pid','an','vn','pname','fname','lname','birthday','birthdate','name','payload','raw_data','extra_data','note','source_path','storage_path','archive_path')
    return {'name':name,'type':typ,'nullable':nullable,'key':key,'meaning':description or meaning(name,table),'source':source,
     'unit':unit,'verification':'ยืนยัน schema; ความหมายธุรกิจตามหลักฐาน / รอตรวจข้อมูลจริง','owner':'ทีมเวชระเบียน / HIS' if table.startswith('hosxp.') else 'ทีมเรียกเก็บ / การเงิน / ผู้ดูแลข้อมูล',
     'privacy':'ข้อมูลผู้ป่วย / ข้อมูลภายใน ต้องจำกัดสิทธิ' if sensitive else 'ข้อมูลภายใน',
     'transform':'ID เป็น text; เงิน Decimal/numeric; datetime ไทย→timestamptz; ไม่เดาศูนย์แทน NULL',
     'null_zero_negative':'NULL=ยังไม่มี/ไม่ทราบ; 0=ทราบว่าเป็นศูนย์; ติดลบ=เก็บ signed adjustment เมื่อเป็นยอด',
     'acceptance':'เทียบ source PK, row counts, NULL, business key และสูตรใน DATA_USAGE_AND_KPI.md',
     'time_basis':'snapshot capture กับวันบริการ/วันรายงานเป็นคนละเวลา'}

def main():
    args=argparse.ArgumentParser();args.add_argument('--hosxp',type=Path,required=True);opts=args.parse_args()
    raw=opts.hosxp.read_bytes();metadata=json.loads(raw.decode('utf-8-sig'));tables=[]
    for dataset,(table,pk,columns,where) in DATASETS.items():
        names=[re.split(r'::|\s+AS\s+',col.strip(),flags=re.I)[0] for col in columns.split(',')]
        selected=[m for m in metadata if m['ชื่อตาราง']==table and m['ชื่อคอลัมน์'] in names]
        fields=[]
        for m in selected:
            typ=m['ประเภทข้อมูล'];precision=m.get('จำนวนหลักทั้งหมด');scale=m.get('ทศนิยม');length=m.get('ความยาวสูงสุด')
            if '(' not in typ:
                if precision and typ in ('numeric','decimal'):typ+=f'({precision},{scale or 0})'
                elif length:typ+=f'({length})'
            item=field(m['ชื่อคอลัมน์'],typ,m['รับ NULL']=='YES','hosxp.'+table,table+'.'+m['ชื่อคอลัมน์'],'PK metadata' if m['เป็น Primary Key']=='YES' else '',m.get('คำอธิบายคอลัมน์') or None)
            item.update({'precision':precision,'scale':scale,'max_length':length,'default':m.get('ค่าเริ่มต้น')})
            fields.append(item)
        tables.append({'name':'hosxp.'+table,'meaning':f'ต้นทาง dataset {dataset}','grain':f'PK metadata {pk}; ความสัมพันธ์ตาม query registry ยังต้อง profile จริง','verification':'metadata เท่านั้น; JSON ไม่มี FK ยืนยัน','fields':fields})
    db=Database(Settings.from_env().pgweb_url)
    cols=db.rows("SELECT c.table_schema,c.table_name,c.column_name,c.data_type,c.numeric_precision,c.numeric_scale,c.character_maximum_length,c.is_nullable,c.column_default,c.is_identity,coalesce((SELECT string_agg(DISTINCT tc.constraint_type||coalesce(' → '||ccu.table_schema||'.'||ccu.table_name||'.'||ccu.column_name,''),'; ') FROM information_schema.key_column_usage k JOIN information_schema.table_constraints tc USING(constraint_catalog,constraint_schema,constraint_name) LEFT JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name=tc.constraint_name AND ccu.constraint_schema=tc.constraint_schema AND tc.constraint_type='FOREIGN KEY' WHERE k.table_schema=c.table_schema AND k.table_name=c.table_name AND k.column_name=c.column_name),'') AS keys FROM information_schema.columns c WHERE c.table_schema IN ('ingest','eclaim','reporting','his','followup','analytics') ORDER BY c.table_schema,c.table_name,c.ordinal_position")
    grouped={}
    for c in cols:
        table=c['table_schema']+'.'+c['table_name'];typ=c['data_type']
        if typ=='numeric' and c['numeric_precision'] is not None:typ+=f"({c['numeric_precision']},{c['numeric_scale']})"
        elif c['character_maximum_length']:typ+=f"({c['character_maximum_length']})"
        spec=TABLES.get(table,(f"{table} ตาม schema",'ดู key และความสัมพันธ์ด้านล่าง'))
        grouped.setdefault(table,{'name':table,'meaning':spec[0],'grain':spec[1],'verification':'schema ตรวจจาก PostgreSQL จริง; ผล HIS ยังไม่ตรวจรับกับ Session จริง','fields':[]})
        source='HIS query registry → snapshot' if c['table_schema']=='his' else 'REP/STM approved layout → sheet/source_row' if c['table_schema']=='eclaim' else 'กฎระบบ / หลักฐานที่บันทึก / audit'
        f=field(c['column_name'],typ,c['is_nullable']=='YES',table,source,c['keys'])
        f['default']=c['column_default'];f['identity']=c['is_identity']=='YES';f['precision']=c['numeric_precision'];f['scale']=c['numeric_scale'];grouped[table]['fields'].append(f)
    tables+=list(grouped.values())
    result={'version':'0.1.0','source_sha256':hashlib.sha256(raw).hexdigest(),'evidence':'Schema metadata only; no clinical rows exported','tables':tables}
    (ROOT/'financial/dictionary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    head=(ROOT/'docs/DICTIONARY_INTRO.md').read_text(encoding='utf-8')
    out=[head,'\n## รายละเอียดทุกฟิลด์ในขอบเขตรุ่นแรก\n','อ้างอิง machine dictionary: `financial/dictionary.json` ซึ่งมี owner, privacy, transform, default, precision, acceptance และ time basis ต่อฟิลด์ ตาราง `hosxp.*` เป็นชื่ออธิบายต้นทาง ไม่ใช่ schema ใหม่ใน PostgreSQL\n']
    for t in tables:
        out += [f"\n### `{t['name']}` — {t['meaning']}\n",f"หน่วยแถว: {t['grain']}\n\nความเชื่อถือ: {t['verification']}\n",'| ฟิลด์ | ชนิด / NULL | ความหมาย | คีย์ / ที่มา | หน่วย |','|---|---|---|---|---|']
        for f in t['fields']:
            def cell(x):return str(x).replace('|','/').replace('\n',' ')
            out.append('| '+ ' | '.join(map(cell,[f['name'],f['type']+(' / NULL' if f['nullable'] else ' / NOT NULL'),f['meaning'],(f['key'] or '—')+'; '+f['source'],f['unit']]))+' |')
    (ROOT/'docs/DATA_DICTIONARY.md').write_text('\n'.join(out)+'\n',encoding='utf-8')
    print(f'Dictionary: {len(tables)} tables, {sum(len(t["fields"]) for t in tables)} fields; no clinical records')

if __name__=='__main__':main()
