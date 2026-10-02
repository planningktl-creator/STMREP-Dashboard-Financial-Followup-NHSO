# Deployment release acceptance — 0.2.0-rc.1

วันที่ตรวจ: 2 ตุลาคม 2569 (Asia/Bangkok)

## ขอบเขต

รุ่นนี้ตรวจ build/deployment ตามแนว IPTImprove/CMI-Dashboard/DRGSeekerAPI ใช้ pgweb HTTPS, API process/worker หนึ่งตัว และ persistent volume Repository เผยแพร่ source แบบ public ตามคำสั่งผู้ดูแล การตรวจทางการเงินกับ HIS/REP/STM จริงยังใช้ gates ใน `ACCEPTANCE.md`

## ผลทดสอบภายในเครื่อง

| การตรวจ | ผล |
|---|---|
| Python locked environment | 52 tests: API/domain/importer/worker/readiness/deadline/manifest และ financial guard |
| URL launch preflight | 8 checks: Session/token aliases, duplicate/invalid parameters และ clean URL |
| Frontend | TypeScript + Vite production build ผ่าน |
| Docker | build สำเร็จ; Node/Python base digest ตรึง, Python lock SHA-256, UID/GID 10929:10929, read-only root filesystem |
| SQL integration | PostgreSQL 17 + pgweb ชั่วคราว; 16 synthetic SQL assertions ผ่าน |
| Deployment smoke | 9 scenarios ผ่าน: schema ขาดคืน readiness 503/liveness 200, migration replay, SQL assertions, UID/GID + same-origin HTML/assets/API + image exclusions, SIGTERM/recreate/volume restore, commit then lost-response UUID replay, DB dump/restore, Session wait/restart, DB outage ไม่ทำให้ liveness ล้ม |
| Browser | token สอง alias, single handshake, ล้าง URL/storage, case filter/modal, viewport 1440/390, hospital mismatch/reconnect/expiry ผ่าน |
| Publishing scan | code/metadata/synthetic fixtures; ไม่มี runtime data, credentials จริง, XLS, archive หรือ checkpoint ใน publishing candidates/image |

ผล runtime จาก scripts อยู่ `.ci/` ที่ไม่เข้า Git; workflow CI รันชุดเดียวกันโดยไม่เชื่อมโรงพยาบาล

Python TestClient มี deprecation warning จาก Starlette/httpx ใน dependency ที่ตรึง; tests ผ่าน ไม่เกี่ยวกับ runtime transport ของ HIS/pgweb

## แก้ BMS SPA build failure

ตรวจซ้ำวันที่ 2 ตุลาคม 2569: Docker build, 52 Python tests, URL launch preflight 8 checks, TypeScript/Vite build, deployment smoke 9 scenarios และ browser smoke 3 scenarios ผ่านโดยใช้ fixture จำลองทั้งหมด

เพิ่มคำแนะนำเลือก Docker/Container ที่ README/คู่มือ BMS, ตรึง `PORT=8000` ใน image/Compose/Kubernetes และกำหนดทั้ง UID/GID เป็น `10929:10929` ให้ตรง volume contract ไม่มีการเพิ่ม root SPA manifest เพราะระบบต้องใช้ FastAPI และ worker

ผลนี้ตรวจในเครื่องและ disposable PostgreSQL 17/pgweb ไม่ใช่ผล deployment บน domain BMS จริง หน้า Developer Portal ที่เปิดจาก URL ตรงระบุว่าต้องเข้าผ่าน HOSxP Dashboard/BMS Cloud จึงยังไม่มี Session ของ portal สำหรับเปลี่ยน deployment เป็น Docker, ตั้ง runtime configuration/volume หรือทดสอบ staging การสำรอง/migration ฐานจริงและตรวจ domain ต้องดำเนินการหลังเข้าถึง deployment นี้ได้

## ก่อนเปิด production บน BMS

- ระบุ domain/TLS, container port, registry/image digest, persistent storage/quota, runtime Secret และ network routes ของแพลตฟอร์ม
- ตรวจ access/error logs ของ ingress ไม่เก็บ credential จาก launcher URL
- ตรวจ migration/backup ของ DB เดิม และ restore บน staging ด้วยข้อมูลจริงที่ได้รับอนุญาต
- ตรวจ largest XLS, CPU/RAM/disk และผู้ใช้พร้อมกันก่อนปรับ resource limits
- ยืนยัน active BMS Session, source coverage, full-corpus REP, cost semantics/rules และหลักฐานรับเงินจริงก่อนรับรอง KPI

การเผยแพร่ source เป็น prerelease ไม่ประกาศว่าเปิด production หรือรับรองข้อมูลครบถ้วนแล้ว
