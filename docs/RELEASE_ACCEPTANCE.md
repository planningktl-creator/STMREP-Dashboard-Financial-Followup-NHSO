# Deployment release acceptance — 0.2.0-rc.1

วันที่ตรวจ: 2 ตุลาคม 2569 (Asia/Bangkok)

## ขอบเขต

รุ่นนี้ตรวจ build/deployment และเตรียม private GitHub ตามแนว IPTImprove/CMI-Dashboard/DRGSeekerAPI ใช้ pgweb HTTPS, API process/worker หนึ่งตัว และ persistent volume การตรวจทางการเงินกับ HIS/REP/STM จริงยังใช้ gates ใน `ACCEPTANCE.md`

## ผลทดสอบภายในเครื่อง

| การตรวจ | ผล |
|---|---|
| Python locked environment | 52 tests: API/domain/importer/worker/readiness/deadline/manifest และ financial guard |
| URL launch preflight | 8 checks: Session/token aliases, duplicate/invalid parameters และ clean URL |
| Frontend | TypeScript + Vite production build ผ่าน |
| Docker | build สำเร็จ; Node/Python base digest ตรึง, Python lock SHA-256, UID 10929, read-only root filesystem |
| SQL integration | PostgreSQL 17 + pgweb ชั่วคราว; 16 synthetic SQL assertions ผ่าน |
| Deployment smoke | 8 scenarios ผ่าน: migration replay, readiness, image exclusions, SIGTERM/recreate/volume restore, commit then lost-response UUID replay, DB dump/restore, Session wait/restart, DB outage ไม่ทำให้ liveness ล้ม |
| Browser | token สอง alias, single handshake, ล้าง URL/storage, case filter/modal, viewport 1440/390, hospital mismatch/reconnect/expiry ผ่าน |
| Publishing scan | code/metadata/synthetic fixtures; ไม่มี runtime data, credentials จริง, XLS, archive หรือ checkpoint ใน publishing candidates/image |

ผล runtime จาก scripts อยู่ `.ci/` ที่ไม่เข้า Git; workflow CI รันชุดเดียวกันโดยไม่เชื่อมโรงพยาบาล

Python TestClient มี deprecation warning จาก Starlette/httpx ใน dependency ที่ตรึง; tests ผ่าน ไม่เกี่ยวกับ runtime transport ของ HIS/pgweb

## ก่อนเปิด production บน BMS

- ระบุ domain/TLS, container port, registry/image digest, persistent storage/quota, runtime Secret และ network routes ของแพลตฟอร์ม
- ตรวจ access/error logs ของ ingress ไม่เก็บ credential จาก launcher URL
- ตรวจ migration/backup ของ DB เดิม และ restore บน staging ด้วยข้อมูลจริงที่ได้รับอนุญาต
- ตรวจ largest XLS, CPU/RAM/disk และผู้ใช้พร้อมกันก่อนปรับ resource limits
- ยืนยัน active BMS Session, source coverage, full-corpus REP, cost semantics/rules และหลักฐานรับเงินจริงก่อนรับรอง KPI

การเผยแพร่ source เป็น prerelease ไม่ประกาศว่าเปิด production หรือรับรองข้อมูลครบถ้วนแล้ว
