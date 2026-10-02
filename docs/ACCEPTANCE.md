# ผลตรวจรับรุ่น 0.1.0

วันที่บันทึก: **2 ตุลาคม 2569 (Asia/Bangkok)**

เอกสารนี้เป็น baseline ของรุ่น 0.1.0; ผล build/deployment รุ่นล่าสุดดู `RELEASE_ACCEPTANCE.md` และ `DEPLOY_BMS.md`

## สถานะ

ระบบพร้อมทดลองภายในโรงพยาบาล 10929 ด้วยข้อมูลจำลองและฐาน REP–STM ที่มีอยู่ ยังไม่รับรองความครบถ้วนทางการเงินของโรงพยาบาล เนื่องจาก HIS ยังอ่านไม่ครบ, REP ชุดใหญ่ยังนำเข้าอยู่ และนิยามต้นทุน/กฎจ่ายปัจจุบัน/หลักฐานเงินรับยังต้องตรวจยืนยัน

## ผลที่ผ่าน

| การตรวจ | ผลและหลักฐาน |
|---|---|
| Repository รุ่นใหม่ | **40 tests ผ่าน**: API/domain/worker 23 และ importer 17; ใช้ข้อมูลจำลองและสัญญา header metadata รวม Session ถูกยกเลิก, streaming body limit, ชีตยา `(2)` และขอบเขต readmission 28 วัน |
| ตัวนำเข้า REP–STM เดิม | **18 tests ผ่าน** ในรอบตรวจล่าสุด ครอบคลุม parser/layout และ replay |
| TypeScript และ production build | `npm --prefix frontend run build` ผ่าน |
| SQL integration บน PostgreSQL จริง | **16 checks ผ่าน** ด้วย fixture จำลองที่ rollback รวมจำนวน/ยอด/แนวโน้มจากคำสั่งเดียวและ decimal string/document lineage; ดู `SQL_INTEGRATION_RESULT.json` |
| ความสัมพันธ์/การเงิน SQL | วินิจฉัยไม่เพิ่ม encounter, AN-first line ownership, identity ขัดแย้งพักตรวจ, NULL/Decimal, ส่งซ้ำไม่รวมรอบเดิม, cap เงินรับ, ตรึงฐานอุทธรณ์/ยอดติดลบ, task history |
| Metadata HIS | **24 datasets**, ทุกคอลัมน์ใน registry มีใน JSON ที่ให้มา; ดู `HIS_SOURCE_METADATA_CHECK.json` เป็นการตรวจ metadata ไม่ใช่รับรองสิทธิอ่านจริง |
| หน้าจอ | เดสก์ท็อป 1440px และมือถือ 390px; ไม่มี document overflow; stage filter เลือก 20 เคสจำลอง; เปิดแฟ้ม, บันทึกงาน, ค้น Dictionary, คำนวณ scenario ผ่าน |
| Accessibility ของแฟ้ม | native modal มีชื่อ, tabs เชื่อม panel และใช้ ArrowLeft/Right/Home/End; finish review ของ impeccable ได้ `ship` สำหรับข้อแก้ไขที่ตรวจ |
| Dictionary | **73 ตาราง / 953 ฟิลด์**; source/keys/precision/NULL/privacy/owner/transform และ ER diagram; ไม่มีข้อมูลผู้ป่วยจริง |

## ข้อมูลจริงที่ตรวจได้และขอบเขตที่ขาด

### STM

- 178 ไฟล์ → 175 เอกสารเนื้อหา; รายละเอียดต้นทาง 649,497 แถว
- รายละเอียด canonical 645,083 แถว; alias ซ้ำ 4,414 แถวจาก 3 คู่เอกสาร ไม่รวมยอดซ้ำ
- ยอดติดลบเก็บเครื่องหมาย; ผลตรวจ baseline ก่อนหน้าระบุสุทธิ 1,051,462,860.88 บาท
- การตรวจนี้ยืนยันชุดเอกสารที่มีอยู่ ไม่ยืนยันว่าครอบคลุมสิทธิ/บริการทั้งหมดของ HIS หรือเป็นเงินรับจริง

### REP

- ชุดต้นทางที่สำรวจ: 13,936 ไฟล์
- ณ การอ่านสถานะ 07:33 น. มี 4,590 ไฟล์ในฐาน, 4,589 เอกสาร `ready`; ตัวเลขเปลี่ยนได้ระหว่างงานนำเข้า
- งานทำต่อจาก checkpoint เดิม เมื่อ gateway ตอบ 503 จะ retry UUID เดิม; ยังไม่มีผลตรวจครบชุดท้ายงาน
- ต้องรอ `reports/full_corpus_verification.json` ในโปรเจ็คตัวนำเข้าเดิม พร้อม refresh รายงาน ก่อนรับรอง full corpus

### HIS และ BMS Session

- Backend เคยยืนยันโรงพยาบาล 10929 และ PostgreSQL จาก Session ที่ให้มาได้
- Query ทะเบียนอ่านได้ **472,970 แถว / 472,970 HN ไม่ซ้ำ / HN ว่าง 0** เป็นจำนวนทะเบียน ไม่ใช่ผู้มารับบริการในปี
- การอ่าน encounter ช่วง 29 กันยายน 2569 ยังไม่สำเร็จครบ: snapshot ที่จบเป็น `partial`, 0 เคสที่อ่านได้ ไม่ตีความเป็นจำนวนผู้มารับบริการจริงศูนย์
- ตรวจล่าสุด BMS ตอบ **HTTP 501 / MessageCode 401: Authorization Error** แม้ local TTL ยังเหลือ จึงต้องเชื่อม Session ใหม่จากหน้าเว็บ
- แก้ registry ยา `drugitems.units AS unit` และ cursor เริ่มต้นเป็น string ว่าง เพราะ adapter ไม่รับ parameter NULL; เพิ่ม bounded retry สำหรับ transport และพักงานเมื่อ Session ใช้ไม่ได้
- API รายงานคืนตัวตั้งเป็น **NULL** เมื่อ core dataset อ่านไม่ครบ พร้อม coverage และ observed counts; ข้อมูลส่วนที่อ่านไม่สำเร็จไม่ถูกแทนด้วยยอดศูนย์

## ประสิทธิภาพ

`PERFORMANCE_RESULT.json` บันทึก EXPLAIN (ANALYZE, BUFFERS) บนชุด REP–STM ที่มีอยู่: claim lookup 0.080 ms, REP round 0.450 ms, STM aggregate 0.903 ms และ monthly aggregate 64.165 ms ในรอบที่วัด ตัวเลขเป็นเวลา execution ของฐานข้อมูล ไม่รวม latency HTTPS

`IMPORT_PROGRESS_SAMPLE.json` เก็บตัวอย่างสถานะขณะนำเข้า: 4,590 REP files ในฐาน ณ เวลาบันทึก ตัวอย่างนี้ไม่ใช่ผลตรวจรับครบชุด การวัด process ใน attempt ก่อนหน้าพบ peak working set 94.53 MiB แต่ไม่ได้วัด peak ตลอด corpus จึงไม่ใช้รับรองหน่วยความจำเต็มชุด

HIS page ในรอบนั้นมี 0 แถว จึง **ไม่รับรองความเร็ว HIS production** ต้องวัดใหม่หลังอ่านข้อมูลจริงและนำเข้า REP ครบ ปัจจุบันช่องทาง HTTPS มี 503 เป็นระยะ

## สิ่งที่ต้องผ่านก่อนใช้งานทางการและ GitHub

1. เชื่อม BMS Session ใหม่ อ่าน HIS ช่วงสั้นให้ profiles ก่อน/หลัง/actual ตรง แล้วขยายย้อนหลัง; ตรวจ VN/AN/HN ซ้ำและคู่เคลมกับทีมโรงพยาบาล
2. นำเข้า REP ครบ ตรวจ source Summary/ฉบับ/aliases และ refresh เคลม/เดือน; ทดสอบ query plans บนขอบเขตเต็ม
3. ยืนยัน `opitemrece.cost` ต่อหน่วยหรือทั้งรายการ และ codebook สิทธิ/ผลจำหน่าย; ราคาทะเบียนปัจจุบันยังเป็นประมาณการ
4. อนุมัติกฎสิทธิ/อัตรา/กำหนดส่งรุ่นที่ใช้จริง พร้อมหลักฐาน; ยังไม่ใช้ทะเบียนอุปกรณ์ปี 2566 เป็นอัตราปัจจุบัน
5. ตรวจหลักฐานวันส่ง อุทธรณ์ และเงินรับจริง/การจัดสรร; ไม่ใช้วันรายงานหรือยอด STM แทนการโอน
6. ตรวจ deployment TLS, origins, exact host allowlist และ backup/restore ภายในโรงพยาบาล; Docker/compose เป็นชุดติดตั้งที่ยังไม่ได้ build/run ในรอบนี้
7. Forecast ยัง `NOT_READY`; ต้องมีอย่างน้อย 24 เดือนที่ตรวจรับแล้ว พร้อม backtest/error ก่อนเปิดผลพยากรณ์
8. ตรวจ tracked files ไม่มี credential/PHI/archive/checkpoint ก่อนขึ้น private GitHub; ตรวจสถานะ release และ CI ปัจจุบันใน `RELEASE_ACCEPTANCE.md`

ผลจำลองและ metadata ที่ผ่านไม่ทดแทนการตรวจรับข้อมูลจริงตามข้อข้างต้น
