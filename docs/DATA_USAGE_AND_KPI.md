# วิธีใช้ข้อมูลและนิยามตัวชี้วัด

## 1. ใช้งานตั้งแต่ต้นทางถึงงานติดตาม

1. เชื่อม BMS Session ของโรงพยาบาล 10929 ในหน้าเข้าใช้ Backend ตรวจ hospital, URL allowlist, อายุ และ PostgreSQL ก่อนออก cookie ของเว็บ
2. เปิด **ข้อมูล HIS** อ่านช่วงสั้นเพื่อตรวจ profile แล้วขยายย้อนหลัง เวลาที่อ่านแต่ละ dataset, expected/actual counts และ coverage อยู่ใน snapshot
3. เปิด **นำเข้า REP / STM** เลือก `.xls` ตรวจ layout/ยอดก่อน กดนำเข้าที่ผ่านตรวจ อื่น ๆ พักไว้ในคุณภาพข้อมูล ทุกไฟล์มี SHA archive และ manifest
4. เปิด **ภาพรวม** เลือกปีงบประมาณ/วันที่/snapshot หากไม่ครอบคลุมจะมีข้อความแจ้ง ไม่ประกาศยอดทั้งโรงพยาบาลเป็นศูนย์
5. เลือกขั้นตอน HIS/REP/STM หรือกลุ่มคิวเพื่อกรองแฟ้ม เปิด HN แล้วอ่านยอดแต่ละชนิด หลักฐาน source row รายการรักษาและกลุ่มเปรียบเทียบ
6. บันทึกทีม วันติดตาม สถานะและหมายเหตุ ใช้วันบริการเพื่อจัดลำดับค้างทั่วไป วันส่งจริงและ deadline ต้องมาจากหลักฐานแยก
7. เงินรับ: บันทึกหลักฐานโอนจริง ยอดใบรับรวมและ allocation ต่อ encounter; reviewed allocations รวมกันเกินยอดใบรับไม่ได้
8. อุทธรณ์: เปิดต่อเคลมที่คู่ชัดเจน ตรึงฐานก่อนอุทธรณ์ ระบุแถวผลใหม่ใน STM และเลือก DELTA หรือ REPLACEMENT ตามเอกสารที่ตรวจแล้ว

ทุก API รายงานระบุ snapshot, as_of และ scope พร้อม decimal string. ตัวเลขส่วนที่ทราบอาจเป็นยอดบางส่วน ต้องอ่าน contributing_count และ coverage เสมอ. HIS snapshot ไม่ใช่ transaction snapshot ของต้นทาง: BMS API เป็นหลายคำขอ มี read_started/read_finished ของแต่ละ dataset. REP/STM ใช้ฉบับปัจจุบันและสามารถเปลี่ยนหลังมีไฟล์ใหม่; source timeline ระบุวันเอกสารและวันที่อ่านแยกกัน.

## 2. ตัวตั้งจำนวนคนและบริการ

| KPI | สูตร / หน่วย | ข้อจำกัดและการตรวจรับ |
|---|---|---|
| ทะเบียนผู้ป่วยทั้งหมด | COUNT patient / COUNT DISTINCT NULLIF(hn,'') อ่าน profile ทั้งฐาน | รายงานจำนวนแถวกับ HN แยกกัน; HN ซ้ำ/ว่างเป็น issue |
| ผู้มารับบริการ | DISTINCT HN จาก encounter ในช่วง | คนเดียวหลาย encounter นับคนครั้งเดียว; missing HN แสดงจำนวน |
| OPD visits อิสระ | COUNT ovst VN ที่ unique และไม่เชื่อม AN | OP visit เชื่อม admission แสดงอีกช่องเพื่อเลี่ยงนับบริการซ้ำ |
| IPD admissions จำหน่าย | COUNT unique AN อิง dchdate | ยังไม่ลงโรคยังอยู่; ยังนอนมีวันบริการ NULL แสดงแยก ไม่จัดปีจากวันที่รับไว้แทน |
| วินิจฉัย/หัตถการ | COUNT รายการต่อ VN/AN | ไม่คูณ denominator encounter |
| CMI | SUM adjrw ของรุ่นที่รายงาน / จำนวน IPD จำหน่ายใน cohort | รุ่นปัจจุบันของ ipt เป็น observed; ถ้า adjRW ขาดแสดง contributor, ห้ามเปรียบเทียบข้าม grouper โดยไม่ปรับ |
| LOS | dchdate − regdate | รายงาน mean/median และ negative LOS issue; ไม่ใช้บอกคุณภาพรักษาโดยลำพัง |
| กลับ admit 28 วัน | AN ใหม่ HCODE/HN เดียวหลัง discharged_at ไม่เกิน 28 วัน | โรงพยาบาลนี้และข้อมูลที่อ่านพบเท่านั้น; ไม่มีคู่แต่ window อ่านไม่ครบให้ unknown; ไม่ตีความ unplanned |

ปีงบประมาณเริ่ม 1 ต.ค. ถึง 30 ก.ย.; FY2570 คือ 1 ต.ค. 2569–30 ก.ย. 2570. เทียบปีก่อนถึงช่วงเวลาที่ผ่านไปเท่ากัน ต้องมี snapshot ครอบคลุมทั้งสองช่วง. ตัวตั้งอ่านไม่ครบให้แสดง observed counts และช่วงที่ขาด แทนการสร้างอัตราทั้งโรงพยาบาล.

## 3. ความครบถ้วนการเบิก: นิยามและเงื่อนไขเปิด KPI

| KPI | ตัวหาร | ตัวตั้ง | สถานะรุ่นแรก |
|---|---|---|---|
| ส่งเบิกครบ | องค์ประกอบ HIS ที่ verified rule กำหนด SEPARATE_REQUIRED | มีหลักฐานส่งจริงผูก component นั้น | ยังไม่รับรองทั้งโรงพยาบาลจนมี rule และ source event coverage |
| REP ตอบกลับครบ | รายการส่งที่ระบุเคลม/องค์ประกอบได้ | พบผล REP ของรอบที่ส่ง | ไม่ใช้จำนวนแถว REP แทนรายการส่ง |
| STM ครบ | เคลม/ส่วนผู้จ่ายในขอบเขต STM และช่วงควรได้รับผล | มี STM current ที่จับคู่ชัดเจน | สิทธินอกขอบเขตเป็น NOT_COVERED ไม่ใช่ตกหล่น |
| อุปกรณ์ครบ | actual items ที่กฎยืนยันว่าเบิกแยกได้ | item code/quantity ที่ส่งและ REP ตอบในเอกสารเดียวกัน | ทะเบียนเครื่องมือ 2566 observed_only; ยังไม่เปิด complete rate จากอัตราเก่า |
| เงินรับครบ | receivable ที่หลักฐานยืนยันถึงกำหนดรับ | reviewed receipt allocations | STM ไม่ใช่ receipt; ไม่มี allocation เป็น NULL |
| ต้นทุนครอบคลุม | COUNT service lines | COUNT observed_item_cost NOT NULL | coverage ตามจำนวน ไม่ใช่มูลค่า; 0 cost นับว่า known |

OPD มีทั้งเหมาจ่าย จ่ายตามบริการและเฉพาะโครงการ ไม่ถือว่าทุก visit ต้องมี REP/STM แยก. `BUNDLED` / `NOT_APPLICABLE` ไม่เข้า denominator การเบิกแยก. กฎซ้อนกันหรือยังไม่มี rule ใช้ REVIEW. ข้อมูลช่องเวลารายงาน/ส่งที่พบใน HIS ยังเก็บใน snapshot เพื่อสำรวจ; ไม่ถูก promote เป็นหลักฐานส่งจริงโดยไม่มีการยืนยัน.

### Rule registry

เก็บ care_type, payer_code, version, effective_from/to, authority_url, authority_clause, review_reference และ definition. Engine รองรับ FIXED_ENCOUNTER, UNIT_RATE แบบ Billcode และ DRG แบบ grouper/base rate/k factor ที่ระบุ. ไม่ได้บรรจุอัตราปัจจุบัน 2570 โดยเดา. ต้องให้ทีมเรียกเก็บตรวจเงื่อนไขเฉพาะบริการก่อนใช้. สูตรที่ยังไม่รองรับใช้ REVIEW ไม่ fallback เป็นยอด HIS.

## 4. สูตรการเงินและการกระทบยอด

```text
his_charge = SUM(opitemrece.sum_price) เมื่อ lines complete และไม่ขาดราคา
estimated_item_cost = SUM(current master unitcost × qty)  [estimate_as_of]
observed_item_cost = SUM(cost) หาก line semantics; SUM(cost × qty) หาก unit semantics
submitted = SUM(latest reviewed submission amount ของแต่ละ component_key)
statement = SUM(signed net_amount ของ STM current ของเคลมที่จับคู่ได้)
comparison_gap = statement − rep_nhso_amount บนฐานเดียวกัน
cash = SUM(reviewed allocation จาก receipt จริง)
appeal_delta = SUM(new result rows)              [DELTA]
appeal_delta = SUM(replacement rows) − baseline  [REPLACEMENT]
```

- ใช้ `reporting.rep_latest` ต่อ clinical claim เพื่อไม่รวม REP หลายรอบซ้ำ; วันล่าสุดเท่ากันหลายแถวให้ review
- กระทบยอดรอบเอกสารใช้ REP + TRAN_ID ภายใน HCODE / IP/OP / payer ไม่เอายอดหรือวันที่มาเป็น identity
- HIS–REP IPD ใช้ AN unique และข้อมูลผู้ป่วยสอดคล้อง; OPD ต้องมี VN–TRAN_ID bridge; HN/CID อย่างเดียวไม่ระบุ visit
- ผู้ป่วยขัดแย้งหรือเคลมไปหลาย encounter ให้ MATCH_REVIEW และไม่รวมยอดที่คลุมเครือระดับ encounter
- เคสหลายสิทธิมี STM บางขอบเขตให้ PAYMENT_SCOPE_REVIEW; ต้องตรวจฐานผู้จ่ายก่อนสรุปส่วนต่าง
- รวมยา/อุปกรณ์/โรคแต่ละด้านก่อน JOIN และเชื่อม items กับ parent ภายใน document เดียว
- financial NULL ไม่ใช่ศูนย์; ยอดที่ขาดบางรายการทำให้ his_charge NULL ใน basis lines; ต้นทุนบางรายการแสดง subtotal + coverage
- API ส่ง decimal string; UI แสดง 2 decimals โดยไม่เปลี่ยนความละเอียดที่เก็บ
- สัดส่วนไม่ทราบ/ตัวหารศูนย์ให้ NULL → `—`; เงินชดเชยเทียบต้นทุนบางรายการใช้ชื่อ “ส่วนต่างชดเชยเทียบต้นทุนรายการที่ครอบคลุม”

## 5. สถานะและคิวงาน

| สถานะ | สิ่งที่ควรตรวจ |
|---|---|
| SUBMISSION_UNVERIFIED | HIS มีบริการ แต่ยังไม่มีหลักฐานส่งและคู่ที่ระบุได้ |
| REP_PENDING | มีหลักฐานส่ง / claim ที่ยังไม่เห็นผล REP |
| REP_REJECTED | อ่าน error code และเหตุผล reject; แก้ส่งใหม่ไม่เท่ากับอุทธรณ์ |
| REP_REVISION_REVIEW | ผลล่าสุดวันเท่ากันมีหลายรอบ ห้ามเลือกโดย ID ใหญ่สุด |
| STM_PENDING | REP accepted ในขอบเขต STM แต่ยังไม่พบ statement |
| MATCHED | ยอดบนฐานเดียวกันต่างไม่เกิน 0.01 บาท; ไม่รับรองเงินโอน |
| STATEMENT_PARTIAL / OVER_EXPECTED | เปิดแถว STM และ REP ตรวจรายการจ่ายและปรับปรุง |
| ZERO_OR_REVERSAL | มีศูนย์/ติดลบ เก็บเครื่องหมายและหลักฐานการปรับ |
| MATCH_REVIEW / AMOUNT_UNKNOWN | พักยอดระดับเคสที่คลุมเครือ ตรวจ identity หรือ mapping |
| SOURCE_INCOMPLETE | source dataset ไม่ครบ ต้องอ่านต่อก่อนสรุป |
| NOT_COVERED / PAYMENT_SCOPE_REVIEW | ขอบเขตสิทธิไม่ครอบคลุม / หลายผู้จ่าย อย่าเรียกตกหล่นโดยไม่มี rule |

อายุ 0–30,31–60,61–90,>90 วันใช้จัดคิวทั่วไป; ในหน้าทะเบียนอิงวันบริการ ระบุ basis ว่าไม่ใช่ actual submission lag. Deadline ต้องมีประกาศรุ่นและช่วงใช้ ไม่ใช้วันนำเข้าแทนวันส่ง. เปิดงานเดียวกัน encounter+reason ซ้ำเป็น update และเก็บ task_history ทุกการเปลี่ยน.

## 6. เคสใกล้เคียงและการวางแผน

การดู readmission ใช้เวลาไทยและหน้าต่าง 28 วันหลังจำหน่าย ระบบอ่านทั้ง admission ที่จำหน่ายในช่วงและที่รับเข้าในช่วง แม้รายหลังจำหน่ายพ้นช่วงรายงาน เพื่อไม่พลาดเหตุการณ์กลับมา ส่วนยอด IPD ใน Dashboard ยังนับตามวันจำหน่ายที่อยู่ในตัวกรอง กลุ่ม peers จำกัดเคสที่มีวันบริการในช่วง snapshot; ถ้าสิทธิยังไม่ทราบ จะยังไม่สร้างกลุ่มเปรียบเทียบ

ผล “ยังไม่พบ” ต้องมี admission-date coverage, อ่าน IP ครบ และเริ่มอ่านหลังสิ้นสุดหน้าต่างเวลา หากขาดเงื่อนไขใดให้เป็น “ยังประเมินไม่ได้” Snapshot เดิมที่อ่านเฉพาะ discharge ไม่ถูกใช้รับรองผลลบของ readmission

IPD cohort: สิทธิ + DRG + grouper version + age band + LOS band. OPD รุ่นแรก: สิทธิ + ICD3 + age band; **ยังไม่ปรับ service/procedure complexity** จึงเป็น descriptive comparison และไม่จัดอันดับแพทย์/คุณภาพการรักษา. รายงาน median/P75/P90 พร้อม contributing counts. ต้นทุนเปรียบเทียบเฉพาะเคส coverage=1; cohort ต่ำกว่า 20 แสดง sample warning.

Scenario ให้ผู้ใช้กำหนด volume, charge/case, item cost/case และ opportunity/case ที่มีหลักฐาน. ไม่มี input ให้ผล NULL; ไม่รายงาน net profit. Forecast API พักไว้จนประวัติ ≥24 เดือนต่อเนื่องมีตัวชี้วัดและ coverage ที่ตรวจรับ; domain engine มี rolling-origin backtest เทียบ seasonal naive กับ last-month และ MAE. ยังไม่มี certified training series จึงไม่ส่ง prediction จริงในรุ่นนี้.

## 7. ตัวอย่าง SQL ที่ไม่เปิดเผยผู้ป่วย

```sql
-- ตัวตั้งไม่ JOIN วินิจฉัยหรือยา (ใช้ snapshot_id ของตัวเอง)
SELECT care_type, count(*) AS encounters, count(DISTINCT hn) AS people
FROM his.cases
WHERE snapshot_id = '11111111-1111-4111-8111-111111111111'
  AND service_date BETWEEN DATE '2026-10-01' AND DATE '2027-09-30'
GROUP BY care_type;

-- ยอดรวมจาก view หนึ่งแถวต่อ encounter พร้อม contributors
SELECT sum(his_charge_amount),count(his_charge_amount),
       sum(observed_item_cost),sum(cost_known_count),sum(line_count),
       sum(stm_net_amount),count(stm_net_amount)
FROM analytics.case_financials
WHERE snapshot_id = '11111111-1111-4111-8111-111111111111';

-- ไม่คูณยอดจากหลาย diagnosis (ใช้ EXISTS แทน JOIN)
SELECT count(*)
FROM his.cases c
WHERE EXISTS (SELECT 1 FROM his.records r
  WHERE r.snapshot_id=c.snapshot_id AND r.dataset='ip_diag'
  AND r.payload->>'an'=c.an AND r.payload->>'icd10'='DEMO-DX');

-- ตัวอย่างข้อมูลจำลองที่ไม่ใช้ patient จริง
WITH demo(qty,unit_cost) AS (VALUES (2::numeric,1.125::numeric))
SELECT qty*unit_cost AS estimated_cost FROM demo; -- 2.250
```

## 8. เวลารายงานและความสอดคล้องของยอด

Dashboard อ่านจำนวน encounter, ยอดการเงิน, แนวโน้ม และคิวตัวอย่างจากคำสั่ง PostgreSQL เดียวกัน เพื่อให้ใช้ snapshot ของ transaction เดียวกันระหว่างที่ REP กำลังนำเข้า API ส่ง `his_as_of` เป็นเวลาของ HIS snapshot และ `as_of` เป็นเวลาที่อ่านยอดรายงาน พร้อม `rep_stm_input_document_ids` ระบุฉบับเอกสารปัจจุบันที่ฐานเลือกในเวลานั้น ฟิลด์ `aggregate_consistency` ระบุ `single_postgresql_statement` สำหรับยอดชุดนี้

สรุปรายเดือน REP–STM ที่เตรียมไว้มีเวลา refresh ของตนเองและ `statement_cache.stale` แยกต่างหาก จึงต้องตรวจสถานะก่อนเปรียบเทียบกับยอดที่อ่านปัจจุบัน เมื่อ import และ refresh สำเร็จ ระบบสร้างความสัมพันธ์เคลมใหม่ให้ HIS snapshot ที่ finalized ทุกฉบับ โดยไม่เขียนทับข้อมูล HIS ต้นทาง

## 9. แหล่งอ้างอิงและสถานะกฎ

กระบวนการ REP, statement และเงินรับแยกขั้นใน [คู่มือการเรียกเก็บ สปสช. ปี 2562](https://media.nhso.go.th/assets/portals/1/files/62-2_Claim_Book%28Thai%29.pdf); ใช้อธิบาย process ไม่ใช่อัตรา/กำหนดปี 2570. ความแตกต่างของรูปแบบจ่ายและช่องทาง claim/audit อ้าง [NHSO Claim and Audit](https://media.nhso.go.th/assets/portals/1/files/Lesson_Learn_on_UHC/68-1_Claim%20and%20Audit%20ENG.pdf). DRG/version อ้าง [หนังสือ DRG สปสช.](https://media.nhso.go.th/assets/portals/1/files/66-6_DRG%20Th%20book%20-%20Final_19Sep.pdf). ประกาศล่าสุดต้องตรวจข้อ/ช่วงใช้โดยเจ้าของกฎก่อนนำเข้า rule_packs; เอกสารทั่วไปไม่ยืนยันว่าใช้กับทุกเคส.
