# ส่งต่อผู้ดูแล BMS: persistent storage ก่อนเปิด STMREP จริง

สถานะตรวจวันที่ 2 ตุลาคม 2569 (Asia/Bangkok): ผู้ดูแลโครงการเลือก **รอ persistent storage แล้วเปิดระบบจริง** จึงพัก auto-deploy และไม่เปิดโหมดจำลองบน production domain

ภายหลังพบ domain v2 `https://stm-rep-v2-10929.kube.bmscloud.in.th` ซึ่งหน้าเว็บและ liveness ตอบรุ่น `0.2.0-rc.3` commit `b34d9d0` แต่ผู้ใช้เชื่อม Session ไม่ผ่านเพราะ `ORIGIN_REJECTED` ต้องตั้ง `APP_ORIGINS` ให้ตรง domain v2 Readiness URL สาธารณะตอบหน้า HTML `App Starting` แทน JSON จึงยังไม่ทราบ PVC/runtime configuration ภายในของ v2 และห้ามสรุปว่าสถานะ PVC ของ app เดิมใช้กับ v2 ได้

## ข้อเท็จจริงจาก portal

| รายการ | ผลตรวจ |
|---|---|
| Namespace / app | `portal-10929` / `stm-rep-dashboard` |
| Domain | `https://stm-rep-dashboard-10929.kube.bmscloud.in.th` |
| Platform | `dedicated` (Dedicated Pod) |
| สถานะก่อนดำเนินการ | Sleeping, replicas 0, port 80 |
| Source ที่ BMS ใช้ | Gitea repo `STMREP-Dashboard`, branch `main` |
| Source ที่พบก่อน sync | commit `62b9288`; GitHub มี commit ใหม่กว่า |
| Environment ที่พบ | เฉพาะ `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASS`, `DATABASE_URL`; ไม่มี configuration ของ STMREP |
| Storage / auto-sleep | portal รายงาน storage 0 MB และ auto-sleep เปิด; API ที่สิทธิ์นี้เห็นไม่มี interface ตั้งหรือยืนยัน PVC และปิด auto-sleep |
| Rebuild status | รายงาน building แต่ log ระบุว่า build pod ถูก TTL cleanup แล้ว จึงไม่ใช้สถานะนี้เป็นหลักฐานว่ามี build ทำงานจริง |

GitHub และ Gitea เป็น repo คนละชุด การ push GitHub ไม่ได้ sync Gitea ที่เคยนำเข้าโดยอัตโนมัติ ต้องตรวจ SHA ของ Gitea ก่อน rebuild ทุกครั้ง ในรอบนี้เตรียม sync แบบ fast-forward หลังพัก webhook; ตรวจผลจริงจาก SHA ของ branch `main` ทั้งสองฝั่ง ไม่มี force push

## งานของผู้ดูแลคลัสเตอร์ก่อนเปิดระบบจริง

1. ยืนยัน deployment, service และ ingress ของแอปเดิมใน namespace นี้ รวมถึงหยุด build ที่ค้างจริงถ้ามี เก็บ configuration/image เดิมและ backup ฐาน REP–STM ก่อน migration ห้ามเริ่ม writer ตัวที่สอง
2. จัด PVC `stmrep-data` ใน `portal-10929`, ขนาดเริ่ม 32Gi, `ReadWriteOnce`, storage class ของแพลตฟอร์มที่มีการสำรองและการจัดเก็บตามนโยบายโรงพยาบาล ยืนยัน Bound แล้ว mount `/app/.data` ใน container ของ deployment **เดิม**
3. กำหนด UID/GID/fsGroup `10929:10929` ให้เขียน PVC ได้ และจัด temporary volume `/tmp/stmrep` ตาม template; ข้อมูลใน temporary volume ไม่ใช่ archive/checkpoint ใช้ temporary disk 1Gi (ไม่ใช้ RAM disk) ภายใต้ memory limit 2Gi และตรวจพื้นที่กับขนาดไฟล์จริงก่อนใช้งาน
4. Patch deployment เดิมเป็น `Recreate`, 1 replica / 1 API process / 1 worker, termination grace 150 วินาที และปิด auto-sleep สำหรับแอปนี้เพื่อให้ worker ทำงานต่อเนื่อง ใช้ชื่อ container ที่อ่านพบจริงจาก deployment เดิม ไม่ apply template ที่ชื่อ `stmrep` จนเกิดแอป/worker เพิ่มอีกตัว
5. ตั้ง container และ service target port เป็น 8000 โดยใช้ PORT=8000; liveness `/healthz`, readiness `/api/health/ready` และ HTTPS origin เดียวสำหรับ frontend กับ `/api/*`
6. ตั้ง ingress body limit 301 MiB, read timeout 120 วินาที, buffering off และไม่บันทึก credential จาก launcher URL ยืนยัน controller/TLS/domain ที่แพลตฟอร์มใช้อยู่

ตรวจชื่อทรัพยากรและ PVC ด้วยคำสั่งอ่านก่อน patch:

```sh
kubectl -n portal-10929 get deployment stm-rep-dashboard
kubectl -n portal-10929 get service,ingress,pvc
kubectl -n portal-10929 get deployment stm-rep-dashboard -o jsonpath='{.spec.template.spec.containers[*].name}'
kubectl -n portal-10929 get pvc stmrep-data
```

`deploy/kubernetes.yaml` เป็น reference ของ container contract มีชื่อและ domain ตัวอย่าง ผู้ดูแลต้องปรับ contract ให้เข้ากับทรัพยากร BMS เดิมและตรวจผลหลัง rebuild ว่า platform ไม่เขียนทับ PVC/probes/security context การใช้ volume ที่เขียนได้และ readiness 200 ยังต้องตรวจประกอบว่าเป็น PVC ที่ผูกอยู่จริง

## Runtime configuration และ migration

ตั้ง Secret/runtime configuration ผ่านแพลตฟอร์ม ไม่ใส่ข้อมูลจริงใน Git หรือ Docker image:

| ตัวแปร | ค่า |
|---|---|
| `PORT` | `8000` |
| `APP_MODE` / `HOSPITAL_CODE` | `live` / `10929` |
| `APP_ORIGINS` | `https://stm-rep-v2-10929.kube.bmscloud.in.th` สำหรับ v2; exact HTTPS origin ไม่มี slash ท้าย |
| `COOKIE_SECURE` | `true` |
| `DATA_DIR` | `/app/.data` |
| `WORKER_ENABLED` | `true` หลัง backup/migration และตรวจ PVC แล้ว |
| `PGWEB_URL` | URL HTTPS ของ pgweb ที่ยืนยันว่าใช้ฐาน REP–STM เดิมและเข้าถึงจาก pod ได้ |
| `BMS_PASTE_URL` / `BMS_ALLOWED_HOSTS` | ค่า endpoint และ exact host ที่ตรวจอนุญาตแล้วตาม `.env.example`; ไม่ใช้ wildcard |
| `ITEM_COST_SEMANTICS` | `unverified` จนความหมายต้นทุนผ่านการตรวจ |

ตัวแปร `DATABASE_URL` ที่ portal inject อยู่ยังไม่ใช่ `PGWEB_URL` ของ transport รุ่นนี้ ต้องตั้ง configuration ให้ตรง code และตรวจ outbound HTTPS ไป pgweb/BMS

หลัง backup ฐานและ volume สำเร็จ ให้ใช้ image เดียวกับ release รัน `python -m scripts.migrate` เป็น one-shot migration โดยไม่เปิด API/worker แล้วจึงเปิด deployment เดิม อ่านรายละเอียดการกู้คืน/rollback ใน `BACKUP_RESTORE.md` และขั้นตอน migration ใน `DEPLOY_BMS.md`

## เกณฑ์เปิดใช้งานและคืน auto-deploy

- ตรวจ Gitea SHA ตรงกับ release commit ที่ผ่าน GitHub CI; rebuild ต้องใช้ Dedicated/Kaniko และ Dockerfile ไม่ใช้ SPA หรือ AI auto-fix เพื่อแก้ชนิด deployment
- ภายใน pod ตรวจ UID/GID 10929, mount PVC และเขียน fixture ที่ `/app/.data` ได้ สร้าง pod ใหม่แล้วตรวจ fixture/archive/checkpoint และ SHA เดิม รวมถึงกรณีเปลี่ยน node ถ้า storage รองรับ
- ตรวจ `/healthz` 200 และ `/api/health/ready` 200; เมื่อ DB/schema/worker ไม่พร้อมให้ readiness 503 และเก็บเหตุผลตามจริง
- ผ่าน HTTPS domain ตรวจหน้าเว็บ/assets/API, Session 10929, อัปโหลด fixture จำลอง, worker/job status และ resume หลัง restart โดย UUID/จำนวนแถว/ยอดไม่เพิ่มซ้ำ
- เปิดจริงและคืน auto-deploy หลังผู้ดูแลยืนยันว่า BMS rollout คง PVC, Secret, probes, 1 replica และการปิด auto-sleep ได้ บันทึก image digest กับ commit SHA ที่ deploy จริง

ผลตรวจนี้ยังไม่ยืนยันว่าผู้ดูแลได้จัด PVC, เปลี่ยน port, ตั้ง Secret, migrate ฐานจริง หรือเปิด production แล้ว การตรวจ source/CI ไม่รับรองความครบถ้วนของยอด HIS–REP–STM
