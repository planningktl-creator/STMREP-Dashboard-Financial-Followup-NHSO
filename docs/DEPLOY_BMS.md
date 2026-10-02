# Build และ deploy BMS — 0.2.0-rc.3

## ตั้งค่าหน้า deployment ของ BMS

ผลสำรวจ portal ของแอปเดิม: ใช้ Dedicated Pod และ Gitea repo `STMREP-Dashboard` ซึ่งเป็นสำเนานำเข้าคนละ repo กับ GitHub ต้อง sync SHA ก่อน rebuild ผู้ดูแลโครงการเลือกพัก deployment รอ persistent storage ดู [ขั้นตอนส่งต่อผู้ดูแล BMS](BMS_PLATFORM_HANDOFF.md) สำหรับชื่อแอปจริง, PVC, runtime configuration และ auto-sleep

เลือก **Docker/Container** ในหน้า deployment ของแอปนี้ แล้วกำหนดค่าดังตาราง ชื่อช่องอาจต่างกันตามหน้า BMS ให้ใช้ความหมายของค่าเป็นหลัก

| ช่องตั้งค่า | ค่าที่ใช้ |
|---|---|
| Repository | `https://github.com/planningktl-creator/STMREP-Dashboard-Financial-Followup-NHSO` |
| Branch | `main`; บันทึก commit SHA ที่ build จริงเพื่อ rollback |
| Build mode | Docker/Container |
| Build context / working directory | `.` (root repository) |
| Dockerfile path | `Dockerfile` |
| Build/start command override | เว้นว่าง ใช้ขั้นตอน build และ `CMD` ของ Dockerfile |
| Container port / environment | `8000` / `PORT=8000` |
| Replica / rollout | `1` / `Recreate`; 1 API process และ 1 worker |
| Persistent storage | `/app/.data`, UID/GID `10929:10929` เขียนได้ |
| Temporary storage | `/tmp/stmrep`, UID/GID `10929:10929` เขียนได้ |
| Health probes | liveness `/healthz`; readiness `/api/health/ready` |
| HTTPS routing | ทั้ง `/` และ `/api/*` ไป container เดียวกัน |
| Proxy limits | request body `301 MiB`, read timeout `120s` |

ตั้ง environment ตาม `.env.example` ผ่าน runtime configuration ของ BMS: `APP_MODE=live`, `HOSPITAL_CODE=10929`, `WORKER_ENABLED=true`, `COOKIE_SECURE=true`, `DATA_DIR=/app/.data`, `APP_ORIGINS=https://<domain-จริง>` และ exact `BMS_ALLOWED_HOSTS` ที่ยืนยันแล้ว เก็บ `PGWEB_URL` ที่อาจมีข้อมูล authentication ผ่าน Secret ของแพลตฟอร์ม ค่า placeholder ในตัวอย่างต้องแทนก่อนเปิด live

### แก้ข้อผิดพลาด SPA build

หาก log แสดง `== raw-static (no package.json) ==` และ `ERROR: no package.json AND no index.html found at repo root, public/, static/, or docs/` ตัว build กำลังมอง repository เป็น SPA/static แต่ไฟล์ frontend อยู่ใน `frontend/` ให้เปลี่ยน build mode เป็น Docker/Container และ build ใหม่จาก `main`

Docker log ต้องแสดงขั้นตอนของ Dockerfile ทั้ง Node build (`npm ci`, `npm run build`) และ Python runtime แล้วเริ่ม `python -m financial.server` การเพิ่ม root `package.json`, ย้าย `index.html` หรือเลือก subdirectory `frontend` อย่างเดียวไม่ทำให้ FastAPI/worker พร้อมใช้งาน

หลังบันทึกค่าต้องตรวจ build log และ HTTPS domain ของ BMS จริง การ push repository ไม่เปลี่ยน build mode ของ deployment เดิมโดยอัตโนมัติ ถ้าหน้า BMS ไม่มีช่อง volume, Secret หรือ readiness ให้ผู้ดูแลแพลตฟอร์มตั้ง container contract ตามหัวข้อด้านล่างก่อนเปิด live

## รูปแบบที่ใช้

อ้างอิง IPTImprove และ CMI-Dashboard: multi-stage Docker, non-root, URL Session, same-origin UI/API, `/healthz`, cache ของ hashed assets และ CI ก่อน release ส่วน DRGSeekerAPI เป็นตัวอย่าง static preflight และ browser tests ที่ใช้ข้อมูลจำลอง

STMREP มี FastAPI และ worker ภายใน container เดียว ใช้ pgweb HTTPS ตามข้อตกลง รุ่นนี้ต้องมี **1 replica / 1 API process / 1 worker** Session อยู่ใน memory; restart แล้วเชื่อมใหม่ ส่วนไฟล์และ checkpoint อยู่บน persistent volume งาน HIS รอ Session ได้และ REP/STM ทำต่อได้จาก checkpoint

## สิ่งที่ผู้ดูแล BMS ต้องระบุ

| Configuration | ค่า/ข้อกำหนด |
|---|---|
| Build context | root repository; `Dockerfile` อยู่ root |
| Port | default 8000; ถ้าแพลตฟอร์มกำหนด 8080 ให้ตั้ง `PORT=8080` และเปลี่ยน targetPort/probes ให้ตรง |
| Domain/TLS | HTTPS domain ของแอป; `APP_ORIGINS` ตรง origin จริง |
| Runtime secret | PGWEB_URL, BMS_ALLOWED_HOSTS แบบ exact host ที่อนุญาต; ใส่ผ่านแพลตฟอร์ม |
| Storage | mount `/app/.data` ให้ UID/GID 10929 เขียนได้; persistent encrypted storage ตามนโยบายโรงพยาบาล |
| Upload temp | `/tmp/stmrep` แยกจาก archive/checkpoint; ใช้ disk-backed `emptyDir` ขนาดจำกัด 1Gi; ไม่ตั้ง `medium: Memory` เพราะ RAM disk นับรวมใน memory limit |
| Ingress | body 301 MiB, read timeout 120s, request buffering off; ไม่บันทึก query string/body/credentials |
| Rollout | Recreate, termination grace 150s; ไม่มี autoscaling (1 replica เท่านั้น) |
| Resource | Dedicated Pod กำหนด **Guaranteed QoS** (`requests` = `limits` = 2 CPU / 2Gi RAM) ช่วยจัดลำดับ QoS แต่ยังอาจ OOM หรือถูก eviction ได้; PVC 32Gi SSD (ReadWriteOnce) |

### การตั้งค่า Dedicated Pod บน Kubernetes อย่างมีประสิทธิภาพ

1. **Resources**: `requests` = `limits` = 2 CPU / 2Gi ทำให้ได้ Guaranteed QoS แต่ไม่ได้รับประกันว่าจะไม่ OOM/evict; Dedicated Pod ไม่ใช่ node ส่วนตัว
2. **Temporary disk**: `/tmp/stmrep` เป็น `emptyDir: {sizeLimit: 1Gi}` บนดิสก์ และแอปจำกัด reservation พร้อมตรวจพื้นที่ก่อนรับไฟล์; Compose ใช้ named disk volume โดย quota ต้องกำหนดที่ host
3. **Persistent archive**: PVC 32Gi ที่ `/app/.data`; ปิด auto-sleep และคงหนึ่ง replica / Recreate ก่อนเปิด production
4. **Root build**: `npm run build` ติดตั้ง dependencies ด้วย frontend lockfile แล้ว build SPA; Dockerfile เป็นช่องทาง deploy ทั้ง API/worker
5. **Source evidence**: build จาก checkout ใหม่ ตรวจ GitHub/Gitea SHA ตรงกัน ส่ง `BUILD_REVISION` เป็น build arg สำหรับ OCI label; หาก BMS ไม่ส่ง arg Docker อ่านเฉพาะ HEAD/main ref แล้วบันทึก `/app/build-revision` และ `/api/health.build_revision` โดยไม่คัดลอก Git config หรือ objects เข้า runtime

ต้องยืนยันว่าแพลตฟอร์มรองรับ Python process ต่อเนื่อง, persistent storage, Secret และ outbound HTTPS ไป pgweb/PasteJSON/BMS การมี static app deploy ได้ยังไม่ยืนยันข้อกำหนดเหล่านี้

ไม่ใช้ path `C:\Users\...` เป็น path บน server ส่งไฟล์ผ่านหน้าอัปโหลดหรือย้าย archive/checkpoint อย่างมี manifest ห้ามคัดลอก `.env` หรือข้อมูลจริงเข้า image

## เปิดจาก HOSxP

ใช้ URL รูปแบบ `https://<app-domain>/?bms-session-id=<dynamic-session>&marketplace_token=<optional-token>`; รองรับ `marketplace-token` ด้วย เปิดหน้าเต็มหรือแท็บใหม่ แทน iframe ข้าม origin

หน้าเว็บอ่านค่าครั้งเดียว ล้างทั้งสามพารามิเตอร์ออกจาก URL ก่อน handshake แล้วส่ง `POST /api/session` ไม่มี browser storage ของ Session/token Backend ยืนยันโรงพยาบาล 10929/host/TTL และออก opaque HttpOnly Secure cookie หาก Session ถูกยกเลิกจะแสดงให้เชื่อมใหม่ งาน HIS เป็น waiting_session

TLS terminator/ingress ต้องป้องกันการบันทึก credential จาก **คำขอหน้าแรกก่อน JavaScript ทำงาน** ทั้ง access และ error logs ตรวจข้อกำหนดนี้กับผู้ดูแลแพลตฟอร์ม ไม่ใส่ token ตายตัวใน URL config/GitHub

## Build และติดตั้ง

```sh
docker build --build-arg BUILD_REVISION=$(git rev-parse HEAD) -t stmrep:0.2.0-rc.3 .
docker image inspect stmrep:0.2.0-rc.3 --format '{{.Id}}'
```

Frontend ใช้ `npm ci`; Python ใช้ `requirements.lock` พร้อม SHA-256 และ base images ตรึง digest การเปลี่ยน dependency/base image ต้องรัน CI ใหม่ build image เป็น release artifact แล้วส่ง registry ของแพลตฟอร์ม ใช้ digest ที่ build จริงเมื่อ deploy

Docker Compose: คัดลอก `.env.example` เป็น `.env` ในเครื่อง deployment ตั้งค่าจริง แล้ว `docker compose build` / `docker compose up -d` หลัง migration ข้างล่าง Default bind เฉพาะ localhost:18729 ให้ HTTPS proxy เข้าถึง ไม่มี secrets อยู่ใน compose

Kubernetes: `deploy/kubernetes.yaml` เป็น template ที่ต้องแทน domain, registry/image digest, ingress class, TLS secret, pgweb/BMS endpoints, storageClass/quota และ network policy ตามแพลตฟอร์ม ไม่ apply placeholder ลง production

## Migration และ rollout

1. สำรอง DB และ volume ก่อนเปลี่ยน schema/image ตรวจว่าชุด backup restore ได้
2. พักงานผ่านหน้า jobs และรอถึง checkpoint; บันทึก UUID/manifest/runtime image เดิม
3. ฐานที่มี ingest/eclaim อยู่แล้วให้รัน `python -m scripts.migrate` ผ่าน one-shot container ของ image ใหม่กับ runtime secret เท่านั้น ไม่เปิด API/worker ของ migration container
4. ฐานใหม่ต้องติดตั้ง legacy REP–STM schema **ก่อน** extension อย่ารัน legacy reset/drop-view หลัง extension และอย่าให้หลาย instance migrate พร้อมกัน
5. Recreate app ด้วย image ใหม่และ volume เดิม ตรวจ `/healthz` และ `/api/health/ready`
6. เชื่อม BMS ใหม่ ตรวจ hospital 10929 และ resume งาน HIS/REP–STM จาก UUID เดิม
7. ทดสอบ upload, case search, task และ source coverage บน staging ก่อนเปิด production

`financial.server` รับ SIGTERM แล้วประกาศ draining/หยุดรับงานใหม่ Worker เก็บ unsent batches และรอสูงสุด 120s หากถูก kill กลาง request ใช้ UUID เดิมตรวจ replay; lease หมดภายใน 180s หลัง heartbeat หยุด ก่อน resume ตรวจว่า instance เดิมหยุดจริง

## Health และ monitoring

- `/healthz`, `/api/health`: liveness เท่านั้น ไม่ตรวจ BMS/DB
- `/api/health/ready`: deadline 5s/no retry ตรวจ storage, schema/DB และ worker; DB/พื้นที่/worker ไม่พร้อมคืน 503
- BMS Session หมดอายุไม่ทำให้ liveness ล้ม และไม่ restart ระบบเพื่อแก้ permission
- `/api/operations`: ต้อง authenticated; counts งาน/ค้างเกิน 10 นาทีจากเวลา progress จริง, gateway events และ disk free ไม่มี token/SQL/ข้อมูลคนไข้
- คำขอรายงานใช้ deadline รวม 90s ร่วมกันระหว่าง pgweb calls ไม่เพิ่มเวลาใหม่ต่อ query; worker ใช้ retry/checkpoint ของงาน
- Alerts: readiness ล้มซ้ำ, gateway unavailable, jobs failed/stalled, STORAGE_LOW และ WORKER_SHUTDOWN_TIMEOUT; เริ่มเตือนเมื่อ volume เหลือต่ำกว่า 20% ด้วย monitoring ของแพลตฟอร์ม แอปมี hard minimum 256 MiB เพื่อพัก readiness

## ตรวจรับก่อน release

```sh
python -m pip install --require-hashes -r requirements-dev.lock
python -m pytest -q
node frontend/scripts/check-launch.mjs
node frontend/scripts/check-api.mjs
npm run build
docker build -t stmrep:release-test .
python -m scripts.deployment_smoke
python -m playwright install chromium
python -m scripts.browser_smoke
python -m scripts.performance_check --enforce --keep-database
python -m scripts.query_benchmark
docker compose -p stmrep-perf-test -f deploy/compose.test.yaml down --volumes
python -m scripts.check_release
```

Smoke ใช้ compose project `stmrep-release-test`, ports 18830–18833 และ PostgreSQL/pgweb ชั่วคราว ไม่เชื่อม HIS หรือฐานโรงพยาบาล SQL integration ใช้ synthetic fixture เท่านั้น ท้ายงานลบเฉพาะ test containers/volumes ของ project นี้

Release นี้เตรียม deployment; ความครบถ้วน HIS/REP/STM, นิยามต้นทุน, current rules, เงินรับจริง และ forecast ยังใช้ gates ใน `ACCEPTANCE.md` ไม่อนุมานว่า CI ผ่านเท่ากับรับรองยอดการเงิน
