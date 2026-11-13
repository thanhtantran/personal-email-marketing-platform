# Hướng dẫn cài đặt và chạy thử

Tài liệu này là hướng dẫn từng bước để cài và chạy **Personal Email Marketing Platform** trên máy
cá nhân. Nội dung được viết dựa trên đúng mã nguồn hiện tại của repo (`infra/compose.yaml`,
`.env.example`, `pyproject.toml`, `services/api/app/config.py`, `apps/web/`).

Có hai cách:

- **Cách A — Docker Compose (khuyến nghị)**: chạy toàn bộ stack (API, worker, scheduler, web,
  PostgreSQL, Redis, object storage). Phù hợp để "cài thử" nhanh và đúng như thiết kế.
- **Cách B — chạy trực tiếp không Docker**: hữu ích khi muốn sửa code backend/frontend và debug.

---

## 0. Yêu cầu trước khi cài đặt

| Thành phần | Bắt buộc cho | Ghi chú |
|---|---|---|
| Docker Desktop + Compose v2 | Cách A | Windows/macOS/Linux đều được |
| Python 3.12+ | Cách B, và để chạy test | `python --version` |
| Node.js 20+ | Cách B (frontend), và để render template ngoài Docker | `node --version` |
| Git | Cả hai | để lấy mã nguồn |
| Một tài khoản Google | Để đăng nhập owner | dùng cho OAuth |

Kiểm tra nhanh trên Windows PowerShell:

```powershell
docker --version
docker compose version
python --version
node --version
```

Nếu một lệnh báo "not recognized", hãy cài thành phần đó rồi mở lại terminal.

> Trong repo này **không có sẵn file `package-lock.json`/`node_modules`**; `npm install` sẽ tự tạo.
> Không cần chạy frontend nếu bạn chỉ muốn thử phần API.

---

## 1. Lấy mã nguồn

```powershell
git clone <URL-repo> personal-email-marketing-platform
cd personal-email-marketing-platform
```

Nếu bạn đã có sẵn thư mục dự án (ví dụ `e:\Trae\personal-email-marketing-platform`), chỉ cần `cd`
vào đó. **Mọi lệnh trong tài liệu này chạy từ thư mục gốc của repo** (nơi có `pyproject.toml`,
`alembic.ini` và `.env.example`).

---

## 2. Tạo file cấu hình `.env`

```powershell
Copy-Item .env.example .env
```

(macOS/Linux: `cp .env.example .env`)

File `.env` **không** được commit (đã nằm trong `.gitignore`). Mặc định trong `.env.example` là các
giá trị an toàn cho local; bạn chỉ cần sửa một vài biến dưới đây.

### 2.1 Biến tối thiểu để đăng nhập được

| Biến | Giá trị cần đặt | Bắt buộc khi nào |
|---|---|---|
| `OAUTH_GOOGLE_CLIENT_ID` | Client ID từ Google Cloud Console | Luôn cần để đăng nhập |
| `OAUTH_GOOGLE_CLIENT_SECRET` | Client Secret tương ứng | Luôn cần để đăng nhập |
| `OAUTH_GOOGLE_REDIRECT_URI` | `http://localhost:8000/api/v1/auth/google/callback` | Phải khớp với Google Console |
| `OWNER_EMAIL` | Email Google của bạn (đã xác minh) | Khuyến nghị |
| `SESSION_KEY` | Chuỗi ngẫu nhiên ≥ 32 bytes | Bắt buộc khi `APP_ENV=production` |

Tạo `SESSION_KEY` ngẫu nhiên (PowerShell, kết quả 48 ký tự hex = 48 bytes):

```powershell
-join ((1..48) | ForEach-Object { '{0:x}' -f (Get-Random -Max 16) })
```

Hoặc (macOS/Linux): `openssl rand -hex 32`

> **Ghi chú quan trọng về dev vs production**: với `APP_ENV=development` (mặc định trong
> `.env.example`), ứng dụng **khởi động được ngay cả khi còn dùng `SESSION_KEY` mặc định yếu**. Việc
> kiểm tra fail-closed (secret mạnh, OAuth, owner, `https`, KMS) chỉ được áp dụng khi
> `APP_ENV=production` (xem [config.py](file:///e:/Trae/personal-email-marketing-platform/services/api/app/config.py)
> — `require_production_safety`).

> **Về `OWNER_GOOGLE_SUB` vs `OWNER_EMAIL`**: nếu `OWNER_GOOGLE_SUB` được đặt, hệ thống so khớp
> `sub` của Google (ổn định, khuyến nghị cho production). Nếu chỉ đặt `OWNER_EMAIL`, hệ thống yêu cầu
> email đã xác minh và so khớp không phân biệt hoa thường. Nếu **cả hai đều trống và `APP_ENV` là
> `development`**, lần đăng nhập Google đầu tiên sẽ **tự nhận làm owner** (có cảnh báo trong log) —
> đây là cách nhanh nhất để thử local.

### 2.2 Khóa mã hóa (`ENCRYPTION_KEY_REF`) — bắt buộc nếu bạn sẽ thêm provider account

`.env.example` đặt mặc định:

```dotenv
ENCRYPTION_KEY_REF=file://./secrets/dev-encryption-key
```

Nhưng **file `secrets/dev-encryption-key` không tồn tại trong repo** (chỉ có `secrets/.gitkeep`) và
**thư mục `secrets/` không được mount vào các container backend** (xem `infra/compose.yaml` và
`infra/docker/Dockerfile.api`; WORKDIR trong container là `/app`). Hệ quả: `/healthz` và `/readyz`
vẫn OK, nhưng khi bạn **tạo provider account** (thao tác cần mã hóa credential), ứng dụng sẽ lỗi
`EncryptionKeyError: cannot read encryption key file '/app/secrets/dev-encryption-key'`.

Chọn **một** trong hai cách sau.

**Cách 2.2.a — dùng giá trị key trực tiếp (đơn giản nhất cho local)**

Thay dòng trong `.env` bằng một chuỗi **hex 64 ký tự** (tương đương 32 byte, đúng định dạng mà
`load_key_material` chấp nhận):

```powershell
-join ((1..32) | ForEach-Object { '{0:x2}' -f (Get-Random -Max 256) })
```

Rồi đặt:

```dotenv
ENCRYPTION_KEY_REF=<dán-chuỗi-hex-64-ký-tự-vừa-sinh>
```

(Giá trị này cũng có thể là chuỗi base64 của đúng 32 byte.)

**Cách 2.2.b — dùng file secret và mount vào container**

1. Tạo file `secrets/dev-encryption-key` chứa 64 ký tự hex (32 byte) ở thư mục gốc repo.
2. Thêm dòng mount sau vào `infra/compose.yaml` cho **cả ba** service `api`, `worker`, `scheduler`
   (mỗi service đang có mục `volumes:`):

   ```yaml
   volumes:
     - ../services/api:/app/services/api
     - ../secrets:/app/secrets:ro
   ```

Lưu ý: đây là tùy chỉnh của bạn, không phải nội dung có sẵn trong repo.

### 2.3 Các biến mặc định đúng cho Compose (không cần sửa)

`.env.example` đã dùng hostname nội bộ của Compose nên **chạy được ngay trong Cách A**:

```dotenv
DATABASE_URL=postgresql+asyncpg://email:email@postgres:5432/email_platform
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2
OBJECT_STORAGE_ENDPOINT=http://object-storage:9000
```

Nếu bạn chạy ở Cách B (không Docker), phải đổi các hostname này thành `localhost` (xem mục 5).

---

## 3. Tạo Google OAuth credentials

Đăng nhập dùng Google OIDC (owner-only), nên cần tạo OAuth client:

1. Vào **Google Cloud Console** → **APIs & Services** → **Credentials**.
2. Nếu chưa có, cấu hình **OAuth consent screen** (loại "External", điền tên app và email hỗ trợ).
3. **Create Credentials** → **OAuth client ID** → Application type: **Web application**.
4. Ở **Authorized redirect URIs**, thêm **chính xác**:
   `http://localhost:8000/api/v1/auth/google/callback`
5. Copy **Client ID** và **Client Secret** vào `.env` (`OAUTH_GOOGLE_CLIENT_ID`,
   `OAUTH_GOOGLE_CLIENT_SECRET`).
6. Nếu consent screen còn ở trạng thái **Testing**, thêm email Google của bạn vào **Test users**.

Điểm hay gặp lỗi: giá trị `OAUTH_GOOGLE_REDIRECT_URI` trong `.env` phải **trùng khớp ký tự** với
redirect URI đã khai trong Google Console, nếu không Google trả về `redirect_uri_mismatch`.

---

## 4. Cách A — chạy toàn bộ stack bằng Docker Compose

Từ thư mục gốc repo:

```powershell
docker compose -f infra/compose.yaml up --build
```

Lần đầu sẽ build image backend (Python 3.12 + MJML CLI) và image web (Node 20) nên mất vài phút.

**Thứ tự khởi động** (Compose tự điều phối theo `depends_on`/`healthcheck`):

1. `postgres`, `redis`, `object-storage` — phải healthy trước.
2. `createbucket` — job một lần, tạo bucket `email-platform` trong S3 mock (chạy xong là thoát).
3. `migrate` — job một lần, chạy `alembic upgrade head` để tạo schema (chạy xong là thoát).
4. `api`, `worker`, `scheduler`, `web` — chạy thường trực.

Nếu muốn chạy nền (không chiếm terminal):

```powershell
docker compose -f infra/compose.yaml up --build -d
docker compose -f infra/compose.yaml logs -f api
```

### Cổng và URL mặc định

| Service | URL / Cổng |
|---|---|
| web (UI) | http://localhost:3000 |
| api | http://localhost:8000 |
| api docs (Swagger) | http://localhost:8000/docs |
| object storage (S3) | http://localhost:9000 |
| PostgreSQL | localhost:5432 (`email` / `email`, db `email_platform`) |
| Redis | localhost:6379 |

---

## 5. Cách B — chạy trực tiếp không Docker

### 5.1 Chạy hạ tầng phụ trợ bằng Docker (khuyên dùng)

Chỉ cần PostgreSQL, Redis, object storage và bucket:

```powershell
docker compose -f infra/compose.yaml up -d postgres redis object-storage createbucket
```

Sau đó sửa `.env` để trỏ về `localhost`:

```dotenv
DATABASE_URL=postgresql+asyncpg://email:email@localhost:5432/email_platform
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2
OBJECT_STORAGE_ENDPOINT=http://localhost:9000
```

### 5.2 Backend

Cài dependency (chạy từ **thư mục gốc repo**; package `app` nằm ở `services/api` và được khai báo
trong `[tool.setuptools.packages.find]` của `pyproject.toml`, nên `pip install -e .` sẽ import được):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Chạy migration (từ thư mục gốc, vì `alembic.ini` ở đó và `prepend_sys_path = services/api`):

```powershell
alembic upgrade head
```

Chạy ba tiến trình (mở ba terminal riêng, cùng kích hoạt `.venv`):

```powershell
uvicorn app.main:app --reload --port 8000
celery -A app.workers.celery_app.celery_app worker -l info --concurrency 2
python -m app.workers.scheduler
```

> **MJML**: render template phía server gọi CLI `mjml` (`MJML_BINARY=mjml`). Trong image Docker CLI
> này đã được cài sẵn, nhưng khi chạy trực tiếp bạn cần:
> ```powershell
> npm install -g mjml@4
> ```

### 5.3 Frontend

```powershell
npm install
npm run dev
```

Next.js sẽ chạy ở http://localhost:3000 và gọi API tại `NEXT_PUBLIC_API_BASE_URL`
(mặc định `http://localhost:8000`, xem
[packages/api-client/src/index.ts](file:///e:/Trae/personal-email-marketing-platform/packages/api-client/src/index.ts)).

---

## 6. Kiểm tra sau khi cài

Thay `<host>` bằng `localhost` (Cách A/B đều vậy vì cả hai expose cổng ra máy host).

```powershell
curl http://localhost:8000/healthz     # liveness
curl http://localhost:8000/readyz      # readiness: báo cáo PostgreSQL + Redis
curl http://localhost:8000/metrics     # Prometheus text (mặc định bật, xem METRICS_ENABLED)
```

Kỳ vọng:

- `/healthz` trả về trạng thái OK (không phụ thuộc DB/Redis).
- `/readyz` trả về OK **chỉ khi** PostgreSQL và Redis kết nối được.
- `/metrics` trả về định dạng Prometheus. Endpoint này mặc định **không yêu cầu auth** (dành cho
  scrape trong mạng riêng). Đặt `METRICS_ENABLED=false` để tắt, hoặc `METRICS_TOKEN=<token>` để yêu
  cầu header `Authorization: Bearer <token>`.

Sau đó:

1. Mở http://localhost:8000/docs để xem toàn bộ API (`/api/v1/...`).
2. Mở http://localhost:3000 → bấm đăng nhập Google.
3. Nếu đăng nhập thất bại, xem mục **Lỗi thường gặp** bên dưới.

---

## 7. Dùng thử trong UI

Sau khi đăng nhập với tư cách owner:

| Trang | Việc cần làm |
|---|---|
| Providers | Thêm provider account (ví dụ Resend API key) → **verify** eligibility → **refresh quota** |
| Imports | Upload CSV để tạo import, xem preview rồi commit |
| Contacts | Xem danh sách, chi tiết liên hệ, export CSV |
| Segments | Tạo segment và xem số lượng |
| Templates | Tạo template (GrapesJS/MJML) và xem preview |
| Campaigns | Tạo campaign, lên lịch, xem trạng thái recipient |

Lưu ý nghiệp vụ (đúng theo thiết kế, không phải bug):

- Gửi marketing yêu cầu provider account có **eligibility chưa hết hạn** và **capacity snapshot chưa
  cũ**; account quá cũ sẽ bị loại khỏi routing và lượt gửi sẽ bị **hoãn rồi thử lại**, không bị mất.
- Test send chỉ gửi được tới địa chỉ trong `TEST_SEND_ALLOWLIST` (và luôn cho phép `OWNER_EMAIL`).
- Tracking mặc định **tắt** (`TRACKING_ENABLED=false`).

---

## 8. Chạy test và lint (tùy chọn, xác nhận môi trường)

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m ruff check services/api tests
```

Kết quả mong đợi ở trạng thái hiện tại của repo: **294 test passed** và **ruff: All checks passed**.
Các test là unit test thuần (dùng fake/patched), **không cần PostgreSQL/Redis**.

---

## 9. Dừng và dọn dẹp

```powershell
# dừng nhưng giữ dữ liệu (volume vẫn còn)
docker compose -f infra/compose.yaml down

# dừng và xóa toàn bộ dữ liệu local (postgres, redis, s3, node_modules)
docker compose -f infra/compose.yaml down -v
```

---

## 10. Lỗi thường gặp

| Triệu chứng | Nguyên nhân | Cách xử lý |
|---|---|---|
| `/readyz` báo PostgreSQL/Redis down | Container chưa healthy hoặc `.env` sai hostname | Xem `docker compose -f infra/compose.yaml logs postgres redis`; trong Compose hostname phải là `postgres`/`redis`, không phải `localhost` |
| `api` không start, log báo lỗi config | `APP_ENV=production` nhưng thiếu secret/owner/https | Dùng `APP_ENV=development` cho local, hoặc điền đủ các biến ở mục 2.1 và dùng `https` + KMS |
| `redirect_uri_mismatch` khi đăng nhập | `OAUTH_GOOGLE_REDIRECT_URI` không khớp Google Console | Đặt lại đúng `http://localhost:8000/api/v1/auth/google/callback` ở cả hai nơi |
| Sau callback bị chuyển về `/?auth_error=...` | Identity không phải owner, hoặc OAuth bị từ chối | Kiểm tra `OWNER_EMAIL`/`OWNER_GOOGLE_SUB`; email phải đã xác minh; nếu ở dev có thể để trống owner để lần login đầu tự nhận owner |
| Tạo provider account lỗi `cannot read encryption key file` | `ENCRYPTION_KEY_REF` trỏ tới file không tồn tại trong container | Xem mục 2.2 (dùng hex trực tiếp hoặc mount `secrets/`) |
| Không thấy bucket / upload lỗi | `createbucket` chưa chạy | `docker compose -f infra/compose.yaml run --rm createbucket` |
| Cổng 3000/8000/5432/6379/9000 bị chiếm | Trùng service khác trên máy | Tắt service đó, hoặc sửa mapping cổng trong `infra/compose.yaml` |
| Render template lỗi (Cách B) | Chưa có CLI `mjml` | `npm install -g mjml@4` |
| `next build` không chạy được | Chưa có Node 20+ | Cài Node 20+; hoặc chỉ dùng API nếu chưa cần UI |

---

## 11. Cấu trúc thư mục liên quan

```text
.env.example                 mẫu cấu hình; copy thành .env
alembic.ini                  cấu hình Alembic (chạy từ thư mục gốc)
pyproject.toml               dependency backend + cấu hình pytest/ruff
infra/compose.yaml           stack local đầy đủ
infra/docker/                Dockerfile.api (Python + MJML), Dockerfile.web (Node)
services/api/app/            mã nguồn FastAPI (api/v1, domain, workers, security, observability)
migrations/                  các migration Alembic
apps/web/                    Next.js UI
packages/api-client/         client TypeScript gọi API (base URL, CSRF)
docs/deployment.md           hướng dẫn triển khai thật (DNS/sender, backup, upgrade)
docs/runbooks/operations.md  runbook vận hành (pause, cảnh báo, xoay credential)
```

---

## 12. Ghi chú dành cho môi trường production

Hướng dẫn trên là cho **local/thử nghiệm**. Khi triển khai thật, bắt buộc:

- Đặt `APP_ENV=production` (khi đó ứng dụng **fail-closed** nếu thiếu secret mạnh, OAuth, owner,
  `APP_BASE_URL` dùng `https`, hoặc `ENCRYPTION_KEY_REF` vẫn là `file://`).
- Dùng KMS/secret manager thật cho `ENCRYPTION_KEY_REF`, không dùng file local.
- Thay thế S3 mock bằng object storage thật và bật `OBJECT_STORAGE_USE_TLS=true`.
- Làm theo [docs/deployment.md](deployment.md) (DNS/SPF/DKIM/DMARC, backup, upgrade) và
  [docs/runbooks/operations.md](runbooks/operations.md).
