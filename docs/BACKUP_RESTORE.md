# Backup, restore, rollback และย้ายเครื่อง

## ชุดที่ต้องเก็บพร้อมกัน

- PostgreSQL ทุก schema: ingest/eclaim/reporting/his/followup/analytics รวม batch receipts, job UUIDs, source relationships และ audit
- persistent DATA_DIR: uploads, content-addressed archive, SQLite checkpoints/pending batches และ manifest
- archive/checkpoints ของตัวนำเข้าเดิมที่ยังทำงานอยู่ จนย้ายสำเร็จ
- image digest, parser/mapping/query versions, configuration ที่ไม่มี secret และเวลา backup (Asia/Bangkok)

สำรองรายวันและก่อน migration โดยผู้ดูแลโรงพยาบาล จัดเก็บเข้ารหัส จำกัดผู้เข้าถึง และแยกจาก GitHub/image/logs กำหนด retention และเวลาการกู้คืนกับผู้ดูแลฐานตามนโยบายของโรงพยาบาล

## ทำ backup ให้กู้คืนสอดคล้องกัน

1. พัก jobs และ bulk runner; รอให้ batch ที่อยู่ระหว่างส่งจบหรือมี pending UUID บน disk
2. หยุด instance เดิมด้วย SIGTERM เพื่อให้ไม่มี writer ทำงานระหว่างเก็บ DB กับ volume
3. ผู้ดูแล DB ทำ PostgreSQL custom-format dump (`pg_dump -Fc`) ผ่านช่องทางที่ได้รับสิทธิ หรือใช้ backup ของ managed DB ที่ restore ได้ ไม่เผยแพร่ credential ในคำสั่ง/log
4. เก็บ volume snapshot/archive หลังปิด SQLite handles แล้ว พร้อม SHA-256 ของ archive แต่ละไฟล์และ backup artifact ห้ามคัดลอกเฉพาะ sqlite main ขณะ WAL ยังเปิด
5. บันทึก manifest เวลา/image/mapping และเก็บ backup ให้ครบทั้ง DB กับ volume จึงเริ่ม service ใหม่

ไม่ถือว่า DB dump อย่างเดียวเพียงพอ เพราะ client pending batch และไฟล์หลักฐานอยู่บน volume

## Restore และย้ายเครื่อง

1. Restore DB ไปฐานแยกก่อน เปิด image **digest เดิม** กับ volume ที่ restore โดยปิด worker
2. ตรวจ batch receipts, job manifests, schema versions และ SHA-256 ของ archive; จำนวน/ยอดต้องตรงชุด backup
3. Mount DATA_DIR ที่ absolute path เดิมเมื่อเป็นไปได้ สำหรับ archive ที่ยังอ้าง Windows path ใช้รายการ old→new path พร้อม SHA ตรวจทุกไฟล์ก่อนแก้ที่มาใน DB/checkpoint
4. ห้ามส่ง pending ไปฐานที่ restore เก่ากว่า ledger โดยไม่ตรวจ target identity; หาก installer สร้าง DB identity ใหม่ ต้องตรวจ manifest/receipt แล้วทำขั้นตอน rebind ที่บันทึกหลักฐานไว้ ห้ามลบ checkpoint เพื่อข้าม guard
5. เปิด worker เพียงหนึ่งตัว เชื่อม BMS ใหม่ งาน waiting_session ให้ resume ผ่าน API จาก UUID เดิม งาน REP/STM replay batches เดิมได้
6. ตรวจ Summary, cache refresh, coverage และ source links ก่อนเปิดผู้ใช้

## Rollback

- หาก schema ยังเข้ากันได้ ให้หยุด writer และกลับ image digest ก่อนหน้า พร้อม volume เดิม
- หาก schema ไม่เข้ากัน ให้ restore **DB และ volume ของ backup เดียวกัน** แล้วใช้ image/parser/mapping รุ่นของชุดนั้น
- ข้อมูลที่เกิดหลัง backup ต้องตรวจ ledger/manifest และ replay อย่างมีหลักฐานก่อนเปิดอีกครั้ง ห้ามเพียงย้อน image แล้วละทิ้งรายการใหม่
- เก็บ failed release และผลตรวจที่ไม่เปิดเผยข้อมูลผู้ป่วยไว้สำหรับตรวจสาเหตุ

## หลักฐาน automated acceptance

`scripts.deployment_smoke` ตรวจ DB dump/restore บน PostgreSQL 17, archive/SQLite volume backup/restore, SIGTERM/recreate และ lost response หลัง commit ด้วย fixture จำลองทั้งหมด ผลอยู่ `.ci/deployment-result.json` ภายในเครื่องทดสอบ

การ restore ข้อมูลโรงพยาบาลจริง, managed backup, encryption และ retention เป็นการตรวจรับของผู้ดูแล production เพิ่มเติม
