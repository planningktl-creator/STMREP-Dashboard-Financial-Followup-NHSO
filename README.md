# STMREP-Dashboard-Financial-Followup-NHSO

แฟ้มติดตามการเบิกจ่ายโรงพยาบาล **10929** จากตัวตั้ง HIS ทั้ง OPD/IPD → REP → STM → หลักฐานเงินรับและอุทธรณ์

React/TypeScript + FastAPI/worker + PostgreSQL. ข้อมูลต้นทุนที่ยังไม่ยืนยันไม่ถูกแสดงเป็น actual; statement ไม่ถูกตีความเป็นเงินโอน. หน้าสาธิตแยกข้อมูลจำลองจาก live.

รุ่น **0.2.0-rc.1** เตรียม Docker สำหรับ BMS: URL Session, readiness, graceful shutdown, persistent archive/checkpoint และ GitHub CI ใช้ pgweb HTTPS และ 1 instance

## ตั้งค่า BMS deployment: เลือก Docker/Container

Repository นี้ต้อง build ด้วย **Docker/Container** หรือใช้งานเป็น **Dedicated Pod** (Guaranteed QoS: 2 CPU / 2Gi RAM, in-memory RAM disk สำหรับ `/tmp/stmrep`) บน Kubernetes เพราะมี FastAPI และ worker ทำงานต่อเนื่อง ให้ตั้ง repository นี้ / branch `main`, build context `.`, Dockerfile `Dockerfile`, port `8000` และ `PORT=8000` ใช้คำสั่งเริ่มจาก image พร้อม persistent volume `/app/.data` ที่ UID/GID `10929` เขียนได้ ตั้ง runtime configuration และ HTTPS origin ตาม [คู่มือ BMS](docs/DEPLOY_BMS.md#ตั้งค่าหน้า-deployment-ของ-bms)

Repository มี root `package.json` คอย delegate คำสั่ง build ไปยัง `frontend/` เพื่อให้แพลตฟอร์มที่ค้นหาไฟล์ build ที่ root ทำงานได้ แต่การรันระบบสมบูรณ์ต้องเปิด container backend เพื่อให้ API/worker พร้อมใช้งาน หากพบ log `SPA build failed` ให้ตรวจสอบว่าเลือกประเภท deployment เป็น Docker/Container แล้วหรือยัง

## เอกสารหลัก

- [Data Dictionary](docs/DATA_DICTIONARY.md): schema, field meaning, source, key, NULL, precision, relationships และความเชื่อถือ
- [การใช้งานและ KPI](docs/DATA_USAGE_AND_KPI.md): ตัวตั้ง สูตรการเงิน coverage และขั้นตอนเปิดแฟ้ม/ติดตาม/อุทธรณ์
- [สถาปัตยกรรมและคู่มือติดตั้ง](docs/IMPLEMENTATION_PLAN.md): BMS Session, นำเข้า XLS, resume, deployment, backup และเกณฑ์ตรวจรับ
- [ผลตรวจรับ](docs/ACCEPTANCE.md): ผลที่ตรวจแล้วและข้อที่ต้องตรวจด้วยข้อมูลจริงภายในโรงพยาบาล
- [Build/deploy BMS](docs/DEPLOY_BMS.md): container contract, runtime secrets, probes และ rollout
- [ส่งต่อผู้ดูแล BMS](docs/BMS_PLATFORM_HANDOFF.md): source ใน Gitea, persistent storage, auto-sleep และขั้นตอนเปิดระบบจริงของแอปเดิม
- [Backup/restore/rollback](docs/BACKUP_RESTORE.md): เก็บ DB กับ archive/checkpoint พร้อมกัน
- [ผลตรวจ deployment release](docs/RELEASE_ACCEPTANCE.md): Docker, Session, CI และการกู้คืนด้วย fixture จำลอง
- [Machine dictionary](financial/dictionary.json), [mapping registry](repstm/mapping_registry.json), [approved layouts](repstm/approved_layouts.json)

## เริ่มแบบจำลอง

```powershell
python -m pip install --require-hashes -r requirements-dev.lock
python -m pip install --no-deps --no-build-isolation -e .
npm --prefix frontend ci
npm --prefix frontend run build
$env:APP_MODE='demo'
$env:COOKIE_SECURE='false'
$env:WORKER_ENABLED='false'
$env:APP_ORIGINS='http://127.0.0.1:18730'
python -m uvicorn financial.main:app --host 127.0.0.1 --port 18730 --no-access-log
```

เปิด http://127.0.0.1:18730 แล้วกดเข้าสู่ข้อมูลจำลอง. Demo ไม่อ่าน BMS/DB และไม่รับไฟล์จริง.

## เชื่อมข้อมูลจริง

คัดลอก `.env.example` เป็น `.env` ตั้ง PGWEB_URL, exact BMS_ALLOWED_HOSTS, HTTPS APP_ORIGINS และ volume DATA_DIR. ตั้ง APP_MODE=live, COOKIE_SECURE=true เมื่อใช้ TLS. ฐาน REP–STM ที่มีอยู่ให้รัน `python -m scripts.migrate` แล้วเปิด service **หนึ่ง process** หลัง reverse proxy ภายในโรงพยาบาล. เชื่อม BMS Session 10929 ในหน้าเว็บและอ่านช่วงสั้นก่อนขยายข้อมูลย้อนหลัง.

## ตรวจสอบ

```powershell
python -m pytest -q
npm --prefix frontend run build
python -m scripts.integration_check
python -m scripts.benchmark
```

Integration check ใช้ข้อมูลจำลองใน subtransaction และ rollback; ไม่เปิดเผย patient records. Benchmark เผยแพร่เฉพาะ timing/buffer counts. Automated tests ใช้ synthetic fixtures.

ชุดทดสอบรวม importer อยู่ใน repo นี้ด้วย ไม่ต้องมีไฟล์ผู้ป่วยใน Downloads เพื่อรัน automated tests. Synthetic workbook cells ตรวจชีตยา `(2)`, ภาษาไทย, HN ศูนย์นำหน้า, วันที่ พ.ศ., ยอดติดลบ และการพัก header การเงินที่เปลี่ยน; registry tests ตรวจทุก approved layout fingerprint.

ตรวจ query registry เทียบ schema metadata ก่อนเชื่อม HIS:

```powershell
python -m scripts.validate_his_metadata --hosxp 'C:\Users\KTLho\Desktop\HOSxP Structure with primary key.json'
```

เมื่อ BMS ตอบ Authorization Error (รวม adapter ที่ใช้ HTTP 501 / code 401) ระบบพักงานและให้เชื่อม Session ใหม่ ไม่ใช้ local TTL เป็นหลักฐานว่า HIS ยังอนุญาตอ่านอยู่

## สถานะการใช้งาน

โค้ดและ schema รุ่นแรกพร้อมทดลองภายในโรงพยาบาล. การรับรอง completeness KPI ยังต้อง active BMS Session, profile HIS จริง, semantics cost, current payment rules, วันส่ง/อุทธรณ์/receipt และ full REP corpus verification. Forecast ยัง gated. Staff integration พักตามแผน.

Git เก็บ source, metadata dictionary และ synthetic tests. ไฟล์ต้นฉบับ, archive, checkpoint, .env, reports และ clinical data อยู่ในโฟลเดอร์ที่ ignore. Repository นี้เผยแพร่ source แบบ public; deployment ใช้ runtime secrets ของแพลตฟอร์ม
