# STMREP: ตรวจระบบที่เปิดแล้วใช้งานไม่ได้

## ผลตรวจวันที่ 2 ตุลาคม 2569

### Domain v2 ที่ผู้ใช้รายงาน

- `https://stm-rep-v2-10929.kube.bmscloud.in.th/` แสดงหน้าเชื่อม BMS Session และ assets โหลดได้
- `/healthz` และ `/api/health` คืน JSON 200 ของโรงพยาบาล 10929 รุ่น `0.2.0-rc.3`, commit `b34d9d005910f688c992649ceaeae568bd02a33e`
- `/api/session` แบบ GET ที่ไม่มี cookie คืน `BMS_SESSION_REQUIRED` ตามปกติ
- ผู้ใช้ยืนยันว่าการเชื่อม Session ได้ `ORIGIN_REJECTED`; source ปฏิเสธ `Origin` ทุก `POST /api/*` ที่ไม่ตรง `APP_ORIGINS` ก่อนเรียก BMS จึงต้องตั้ง origin ของ domain v2
- `/api/health/ready` กลับตอบ HTTP 200 `text/html` ชื่อ `App Starting — stm-rep-v2` แทน JSON readiness; gateway อาจส่งหน้าเริ่มระบบแทน จึงยังอ่านสถานะ DB/schema/PVC ของ v2 จากภายนอกไม่ได้
- readiness ที่ทดสอบกับ `.env` ของ checkout เครื่องนี้พบ schema ขาด `his.refresh_links(integer)` และ `analytics.report_json(text)`; นี่ไม่ใช่หลักฐานว่า DB ของ v2 ขาดเช่นเดียวกัน
- ยังไม่ได้ตรวจ PVC หรือแก้ runtime ใน Portal; ผู้ใช้เลือกรอ persistent storage ก่อนเปิดระบบจริง

### Domain เดิมที่ตรวจไว้ก่อนหน้า

ตรวจ domain `stm-rep-dashboard-10929.kube.bmscloud.in.th` ด้วยคำขอ GET ที่ไม่ส่ง Session และไม่อ่านข้อมูลผู้ป่วย:

- บางคำขอหมดเวลา บางคำขอตอบ 404; รอบที่ตรวจด้วยเครื่องมือด้านล่าง `/api/health` ตอบ HTTP 200 **HTML ชื่อ Waking Up App...** จึงไม่ใช่ health ของ STMREP
- pgweb ที่ตั้งไว้ในเครื่องเข้าถึงได้: ตาราง `ingest.batches`, `his.records`, `followup.schema_versions`, `analytics.case_financials` มีอยู่ แต่ฟังก์ชัน `his.refresh_links(integer)` และ `analytics.report_json(text)` ยังไม่มี ฐานนี้จึงยังไม่ผ่าน readiness ของโค้ดรุ่นปัจจุบัน
- Dockerfile ที่ผู้ดูแลส่งมาเริ่ม `python -m financial.server` และเปิด port 8000 ถูกต้อง แต่ไฟล์นี้ไม่ยืนยันว่า Pod รัน image นั้น, Service ใช้ port 8000 หรือ PVC ถูก mount แล้ว
- ยังตรวจ configuration ล่าสุดใน Portal ไม่ได้: Session ที่เชื่อมจาก HOSxP ไม่ปรากฏใน Edge หรือ in-app browser ที่ใช้ตรวจ ไม่ใช้ข้อค้นพบเดิมแทนสถานะล่าสุด

อาการนี้เกิดก่อนการอ่านรายงาน จึงยังไม่มีผลวัดที่ชี้ว่า query ช้าเป็นสาเหตุ ผู้ดูแลโครงการเลือกเปิดระบบจริงหลัง persistent storage พร้อม; ยังไม่สั่ง wake/rebuild/migration เพื่อข้ามเงื่อนไขนี้

## คำสั่งตรวจที่ทำซ้ำได้

```sh
python -m scripts.runtime_doctor \
  --url https://stm-rep-dashboard-10929.kube.bmscloud.in.th \
  --expected-revision <full-commit-sha> \
  --output .ci/runtime-bms.json
```

ใน PowerShell ใช้บรรทัดเดียว (ไม่ใช้ `\` ต่อบรรทัด) เครื่องมือคืน exit code 0 เมื่อ API ของโรงพยาบาล 10929 อยู่โหมด live, commit ตรงเมื่อระบุ และ readiness ผ่านครบ; กรณีอื่นคืน 1 ไม่มีการ retry, ส่ง SQL, เชื่อม Session, อัปโหลด หรือติดตั้ง schema

GET บนแพลตฟอร์ม auto-sleep อาจทำให้ gateway เริ่ม wake ตามการตั้งค่าของ BMS เครื่องมือหยุดหลัง health ไม่ผ่านเพื่อไม่ส่งคำขอเพิ่ม รายงานบันทึกเฉพาะรหัสและเวลา ไม่มี response body, header, token หรือข้อมูลผู้ป่วย URL ต้องเป็น origin ที่ไม่มี credential/query/fragment

| รหัส | ความหมาย / ขั้นตอนถัดไป |
|---|---|
| `PLATFORM_WAKING` / `PLATFORM_STARTING` | Gateway ส่งหน้า wake/start; ตรวจ Pod, events, readiness probe และ auto-sleep ใน BMS |
| `API_ROUTE_NOT_FOUND` | Route API ตอบ 404; ตรวจ image, Service targetPort และ `/api/*` ที่ ingress |
| `API_REDIRECTED` | API ถูก redirect; ตรวจ proxy/auth หน้า Portal โดยไม่ถือหน้า login เป็น health |
| `INVALID_API_RESPONSE` | ไม่ใช่ JSON/object ของ STMREP; ตรวจ image และ gateway |
| `API_TIMEOUT` / `NETWORK_UNAVAILABLE` | คำขอไม่สำเร็จ; ตรวจ DNS/TLS/Ingress/Pod ก่อนปรับ query |
| `WRONG_APPLICATION_OR_MODE` | health ไม่ใช่ STMREP 10929 live; ตรวจ app/domain และ runtime configuration |
| `REVISION_MISMATCH` | image ไม่ตรง source ที่ต้องการ; ตรวจ Gitea SHA และ image/build revision |
| `NOT_READY` + `SCHEMA_MISSING` | สำรองฐานและ volume แล้วรัน migration แยกด้วย image ที่จะเปิด |
| `NOT_READY` + storage/worker | ตรวจสิทธิ์ UID/GID 10929, พื้นที่ว่าง, volume และ worker |

ผล `ready` ตรวจเพียง API และ readiness; **ยังไม่พิสูจน์ว่า storage เป็น PVC หรือข้อมูลจะอยู่หลังย้าย Pod** ต้องตรวจ mount/PVC และ restart/resume ตามคู่มือ deploy ด้วย

## ลำดับแก้บน BMS เดิม

1. ตรวจ deployment `portal-10929/stm-rep-dashboard`, replicas, image digest/commit, events และ build log ล่าสุด
2. จัด PVC `/app/.data` และ temporary disk `/tmp/stmrep` ตาม [คู่มือส่งต่อ](BMS_PLATFORM_HANDOFF.md); ยืนยัน Bound และเขียนได้ด้วย UID/GID 10929
3. ตั้ง `PORT=8000`, Service targetPort 8000, origin HTTPS เดียวสำหรับ `/` กับ `/api`, Secret ของ STMREP และปิด auto-sleep คง 1 replica / Recreate / 1 worker
4. สำรองฐานและ volume ให้กู้คืนได้ แล้วใช้ `python -m scripts.migrate` แยกจาก API/worker เพื่อเพิ่ม schema ที่ยังขาด ห้ามเปิด writer อีกชุด
5. Build จาก Gitea SHA ที่ตรง GitHub แล้วตรวจด้วยคำสั่งด้านบน ทดสอบ Session 10929, fixture จำลอง, archive/checkpoint และ resume หลัง restart ก่อนรับข้อมูลจริง

อ้างอิง [DEPLOY_BMS.md](DEPLOY_BMS.md) และ [BACKUP_RESTORE.md](BACKUP_RESTORE.md) ไม่ apply Kubernetes template ที่ใช้ชื่อ app ตัวอย่างจนเกิด worker ซ้ำ

## การแก้ในหน้าเว็บ

- จำกัด health และการอ่าน Session เดิม 8 วินาที; คำขอทั่วไป 95 วินาที (server จำกัดรายงาน 90 วินาที); multipart upload 300 วินาทีรวมเวลาส่งไฟล์
- Deadline ครอบคลุมทั้ง fetch และอ่าน body; การเปลี่ยนตัวกรองยังยกเลิกคำขอเก่าได้ ไม่ตีความ caller abort เป็น timeout
- แสดงข้อความ API 404, เครือข่าย, timeout และ health ผิดรูปแบบ พร้อมปุ่มตรวจบริการอีกครั้ง หน้าเริ่มระบบไม่กลืน health error
- แสดง `ORIGIN_REJECTED` พร้อมระบุให้ผู้ดูแลตั้ง `APP_ORIGINS` ให้ตรง domain
- ไม่ retry mutation อัตโนมัติ: timeout ไม่พิสูจน์ว่าฐานไม่ได้ commit ผู้ใช้ต้องดู job/UUID เดิมก่อนส่งซ้ำ

การเปลี่ยนนี้ช่วยให้หน้าจอออกจากสถานะค้างและตรวจปัญหาได้ ไม่สามารถแทนการจัด PVC, แก้ Service หรือ migrate ฐานของแพลตฟอร์ม
