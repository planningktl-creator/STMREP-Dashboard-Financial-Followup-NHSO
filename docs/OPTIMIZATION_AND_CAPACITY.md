# Dedicated deployment และผล Optimize — 0.2.0-rc.3

## Deployment contract

หน้าเว็บเป็น React SPA ส่วนระบบครบชุดใช้ BMS Dedicated Pod: Dockerfile ที่ root, context `.`, branch `main`, port `8000`, หนึ่ง API process และหนึ่ง worker, replica 1 / Recreate ผ่าน HTTPS origin เดียวกัน

- CPU request/limit 2 cores; memory request/limit 2Gi ให้ Guaranteed QoS แต่ยัง OOM/evict ได้ และไม่ใช่ node ส่วนตัว ดู [Kubernetes QoS](https://kubernetes.io/docs/concepts/workloads/pods/pod-qos/)
- PVC เริ่ม 32Gi ที่ `/app/.data`, UID/GID/fsGroup 10929; archive, uploads และ checkpoint ต้องคงอยู่หลังสร้าง pod ใหม่
- Temporary disk ที่ `/tmp/stmrep`: Kubernetes `emptyDir.sizeLimit: 1Gi`, ไม่ใช้ `medium: Memory` เพราะนับรวม memory limit ตาม [Kubernetes resource management](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/)
- Compose ใช้ named disk volume และจำกัด reservation ในแอป 1Gi; hard quota ต้องตั้งที่ host เอง
- คง 100MiB/ไฟล์, 300MiB/คำขอ, proxy 301MiB, proxy timeout 120s, report deadline รวม 90s, readiness 5s/no retry
- ปิด auto-sleep, ตั้ง Secret และ `APP_ORIGINS` จริง; คง auto-deploy พักไว้จนผู้ดูแลยืนยัน PVC/runtime configuration

Docker build บันทึก source SHA ใน log และ `/app/build-revision`; `/api/health` ส่ง `build_revision` หากส่ง build arg จะมี OCI revision label ด้วย ขั้นตอนตรวจ root build ต้องใช้ checkout ใหม่และ `npm run build` ซึ่งติดตั้ง dependencies จาก frontend lockfile ก่อนเสมอ

## การเปลี่ยนแปลง

| ส่วน | สิ่งที่ทำ |
|---|---|
| HTTP connection | reuse ภายใน request/วงจร worker แล้วปิด; ไม่แชร์ requests.Session ข้าม thread |
| pgweb schedule | จำกัด HTTP ที่รอ response สูงสุด 3 ต่อ endpoint และ background batch ส่งอยู่สูงสุด 1; foreground/heartbeat มาก่อน batch ถัดไป ให้ background ทำต่อหลัง foreground 8 ครั้ง; คง minimum start interval 0.25s |
| Overview | เลือก snapshot และอ่าน totals/coverage/trend/worklist ใน SQL statement เดียวบน MVCC เดียว |
| ค้นเคส | SQL หนึ่งครั้ง, keyset เดิม, HN/AN/VN prefix และ escape wildcard จากข้อความค้นหา |
| REP ล่าสุด | กรอง claim ก่อน window rank; ฉบับล่าสุดที่เวลาเท่ากันหลายแถวยังไม่มีผู้ชนะ |
| JIT | EXPLAIN พบ compilation ราว 2.4s จึง `SET jit=off` เฉพาะ report function; คืนค่าเดิมแม้ query ล้ม |
| HIS–claim | durable queue, refresh จำกัด 200 claim keys ต่อ transaction เฉพาะ snapshots ที่ได้รับผล; full rebuild ยังใช้ตรวจเทียบได้ |
| Metadata | `data_revision` เป็น string และ `refresh_state` ready/pending; รายงานแสดงว่ามีงานปรับคู่/ยอดค้าง |
| File I/O | multipart รับผ่าน temp disk; hashing/write/move ออกจาก API event loop; partial/spool ปิดใน finally |
| Frontend | debounce 300ms, abort และ ignore ผลเก่า, lazy case/secondary screens, poll 10s เฉพาะงานทำอยู่และแท็บแสดง |
| Gateway errors | HTTP 200 HTML/event-stream/JSON เสีย/ค่า null/array → INVALID_API_RESPONSE พร้อมข้อความให้ลองใหม่ |

Migration extension เพิ่ม `financial/optimize.sql` อย่าง atomic ก่อนเปิด app รุ่นนี้ ถ้า runtime role ต่างจาก migration owner ต้องให้ EXECUTE บน `analytics.report_json(text)` แก่ runtime role โดยตรง; `analytics.explain_query(text)` ให้เฉพาะผู้ตรวจ performance ทั้งสองเป็น SECURITY INVOKER และไม่มี PUBLIC EXECUTE ไม่มี HTTP endpoint รับ SQL

ไม่มีการเพิ่ม partition หรือดัชนีโดยเดา คงดัชนีเดิมจนการวัดข้อมูลจริงแสดงเหตุจำเป็น ดู [PostgreSQL EXPLAIN](https://www.postgresql.org/docs/current/using-explain.html)

## ผลตรวจในเครื่องพัฒนา (2 ตุลาคม 2569)

ข้อมูลทั้งหมดเป็น fixture จำลอง PostgreSQL 17 + pgweb ใน Docker; ไม่อ่าน HIS/ฐานโรงพยาบาล

| การวัด | ผล |
|---|---:|
| ผู้ใช้พร้อมกัน / งานนำเข้า | 5 / 1 |
| Encounter / รายการ HIS | 5,000 / 20,000 |
| REP XLS นำเข้าจริง | 15,000 records, 3 ชีต รวม Data Drug (2), ไม่ skip |
| P95 ค้นเคส | 1.194s (เป้า ≤2s) |
| P95 overview | 2.651s (เป้า ≤5s) |
| P95 liveness | 0.0047s (เป้า ≤1s) |
| Peak memory | 129,232,896 bytes (~123MiB), 6.0% ของ 2Gi |
| Event-loop delay สูงสุด | 0.0088s |
| Import end-to-end | 153.139s (~98.0 records/s), รวม inspect/verify/โหลดผู้ใช้ |
| Import transport requests | 155; gateway ทุกงาน 632 requests |
| EXPLAIN overview / ค้นเคส | ~129ms / ~9ms |
| EXPLAIN incremental refresh 200 keys | ~140ms |

ก่อนปรับ JIT บนชุดใหญ่เดียวกัน P95 overview 16.999s และค้นเคส 3.186s ไม่ผ่านเป้า หลังปรับผ่านตามตาราง ส่วน baseline รุ่นเดิมที่ 1,000 encounters มี P95 overview 1.407s และค้นเคส 0.286s ภายใต้ throttle แบบเดิม จึงไม่ใช้เป็นข้อสรุปว่าทุก query เร็วขึ้น: รุ่นใหม่บังคับคิว/rate limit รวม เพื่อควบคุม gateway และให้ UI/heartbeat ได้รับบริการขณะนำเข้า

Main JS ลดจากประมาณ 296kB เป็น 261.63kB (gzip 81.71kB); case และ secondary screens โหลดเพิ่มเมื่อใช้งาน

กรณีจำลอง gateway ช้าเพิ่ม 0.6s ต่อคำขอ: 5 users, 1,000 encounters, นำเข้าจริง 1,500 records ได้ P95 ค้นเคส 1.533s / overview 2.148s / liveness 0.0077s และ peak RAM ~75MiB ผ่านเป้า หลังพบว่าการ serialize ทุกคำขอทำให้ P95 3.459s / 5.825s จึงจำกัด parallel foreground สูงสุด 3 โดยยังคงส่ง background batch ได้ทีละชุดและไม่เพิ่ม worker

ทดสอบขนาดไฟล์ 99MiB: เติมพื้นที่ท้าย BIFF fixture ที่ยังอ่าน 3 ชีตได้ (40 แถว/ชีต, 120 records) พร้อม 5 users/5,000 encounters ได้ P95 ค้นเคส 1.420s / overview 2.460s / liveness 0.0078s, peak memory 289,787,904 bytes (~276MiB; 13.5% ของ 2Gi), นำเข้าครบใน 31.543s การทดสอบนี้ยืนยัน upload/spooling/hash/parse และ headroom ของไฟล์ขนาดใหญ่จำลอง ไม่แทน workbook จริงที่มีแถว/สูตร/รูปแบบซับซ้อนเต็ม 100MiB

ผล local นี้ยังไม่แทนชุด REP 13,936 ไฟล์ / STM 178 ไฟล์ และยังไม่รวมความหน่วง BMS gateway จริง ต้องวัด workbook จริงและข้อมูลเต็มบน staging อีกครั้งก่อนปรับ resource ไม่มีการรับรองยอด HIS–REP–STM หรือ forecasting จากผลนี้

## ตรวจซ้ำและหลักฐาน CI

```sh
python -m pytest -q
npm run build
node frontend/scripts/check-launch.mjs
node frontend/scripts/check-api.mjs
docker build --build-arg BUILD_REVISION=$(git rev-parse HEAD) -t stmrep:release-test .
python -m scripts.deployment_smoke
python -m playwright install chromium
python -m scripts.browser_smoke
python -m scripts.performance_check --enforce --keep-database
python -m scripts.query_benchmark
python -m scripts.performance_check --label slow-gateway --gateway-delay 0.6 --iterations 2 --enforce --keep-database
python -m scripts.performance_check --label large-file --pad-file-mib 99 --import-rows 40 --iterations 2 --enforce --keep-database
docker compose -p stmrep-perf-test -f deploy/compose.test.yaml down --volumes
```

ห้ามรัน performance seed/refresh EXPLAIN กับฐานโรงพยาบาล scripts ตรวจ endpoint และ database `stmrep_test` ก่อนทำงาน หลักฐานอยู่ `.ci/` และ CI artifact เฉพาะตัวเลข/node types/ภาพข้อมูลจำลอง ไม่มี SQL predicates, credential, archive หรือ checkpoint การวัด EXPLAIN ANALYZE ทำให้ refresh ทำงานจริง จึงจำกัดเฉพาะ fixture ทิ้งได้

CI ตรวจ Session/CSRF, malformed API, upload limits, storage/worker/schema/DB readiness, replay หลัง timeout commit, signed amounts/NULL, identity conflict, latest tied REP, snapshot/denominator และ incremental refresh เทียบ rebuild พร้อม Docker non-root, SIGTERM/recreate, archive/checkpoint และ database/volume backup restore

## งานก่อนเปิดผ่าน BMS

1. Commit/push GitHub, CI ผ่าน, sync Gitea fast-forward และตรวจ SHA เท่ากัน; build จาก SHA นี้
2. ผู้ดูแลยืนยัน PVC Bound, Secret, port8000, probes, disk quota, ปิด auto-sleep; คง auto-deploy พักระหว่างเตรียม
3. Backup ฐาน/volume และทดสอบ restore; รัน migration แยกโดยไม่เปิด writer เพิ่ม
4. ตรวจ SHA จาก domain, `/`/assets/`/api`, Session 10929, อัปโหลด fixture, restart/resume volume เดิม จำนวน/ยอดไม่เพิ่มซ้ำ
5. วัด 5 users + import บน gateway จริง; แยกฐาน/เครือข่ายช้าออกจาก API, เก็บ peak CPU/RAM/delay/queue และปรับ bottleneck ก่อนเพิ่ม worker
6. เปิดรับไฟล์จริงเมื่อผ่านเกณฑ์ระบบ และตรวจ financial completeness ตาม ACCEPTANCE.md แยกกัน

Readiness ล้มไม่ควรทำให้ liveness restart เพื่อแก้ Session; งาน HIS รอ reconnect ส่วน REP/STM ใช้ UUID/checkpoint เดิม ดู `/api/operations` สำหรับ queue wait, request/http time, CPU, cgroup memory และ event-loop delay โดยต้อง authenticated
