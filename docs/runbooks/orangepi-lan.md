# Runbook: Orange Pi LAN (`192.168.88.140`)

Triển khai Personal Email Marketing Platform trên máy này, cho các client trong cùng LAN.
Repo gốc: `/mnt/ssd/personal-email-marketing-platform`.

## Khác biệt so với Compose mặc định

Trên host này cổng mặc định đã bị chiếm:

| Stock | Host đang dùng | Email-platform (host → container) |
|---|---|---|
| API `:8000` | `picoERP-web` | **`8100 → 8000`** |
| Postgres `:5432` | `picoERP-db` | **`5440 → 5432`** |
| Redis `:6379` | (giữ trống) | **`6380 → 6379`** |
| S3 mock `:9000` | `ignis` | **`9100 → 9000`** |
| Web `:3000` | trống | **`3000 → 3000`** |

Trong Docker network vẫn dùng hostname nội bộ (`postgres:5432`, `redis:6379`, `object-storage:9000`). Chỉ **publish** ra host được đổi trong `infra/compose.yaml`.

`api` / `worker` / `scheduler` mount thêm `../secrets:/app/secrets:ro` để đọc
`ENCRYPTION_KEY_REF=file://./secrets/dev-encryption-key`.

## URL dùng trên LAN

| Service | URL |
|---|---|
| Web (APP) | http://192.168.88.140:3000 |
| API | http://192.168.88.140:8100 |
| API docs | http://192.168.88.140:8100/docs |
| Health | http://192.168.88.140:8100/healthz |
| Ready | http://192.168.88.140:8100/readyz |

CORS chỉ cho phép đúng `APP_BASE_URL` → trình duyệt phải mở **đúng**
`http://192.168.88.140:3000` (không dùng `localhost` trên máy khác trong LAN).

## File đã chuẩn bị

- `.env` — overlay LAN (không commit). Các URL public đã trỏ `192.168.88.140`.
- `secrets/dev-encryption-key` — hex 64 ký tự (32 byte), mode `600`.
- `infra/compose.yaml` — remap host ports + mount secrets.

OAuth Google / `OWNER_*` **còn trống**. Stack vẫn lên được health/UI; đăng nhập Google chỉ sau khi điền credential.

## Chạy stack (do bạn thực hiện)

**Không** dùng `docker compose … up --build -d` trên máy này: Docker root nằm
ở `/mnt/ssd/docker` (NVMe). Compose mặc định có thể build cùng lúc nhiều
service cùng `Dockerfile.api` và làm rớt ổ `/dev/nvme0n1p1`.

Dùng script build **tuần tự**, giới hạn 2 CPU / 4 GiB, rồi `up --no-build`:

```bash
cd /mnt/ssd/personal-email-marketing-platform
chmod +x scripts/gentle-compose-up.sh
./scripts/gentle-compose-up.sh
```

Tuỳ chọn (còn nhẹ hơn):

```bash
BUILD_CPUSET=0 BUILD_MEMORY=3g BUILD_MEMORY_SWAP=3g ./scripts/gentle-compose-up.sh
```

Theo dõi:

```bash
docker compose -f infra/compose.yaml ps
docker compose -f infra/compose.yaml logs -f api web
```

Lần đầu vẫn mất vài phút (pip + npm + mjml), nhưng chỉ **một** image backend
(`email-platform-api:local`) và **một** image web (`email-platform-web:local`).

Nếu chỉ cần chạy lại sau khi image đã có (không rebuild):

```bash
docker compose -f infra/compose.yaml up -d --no-build
```

### Nếu NVMe vẫn hay drop khi build

1. Dừng container nặng khác trước: `docker ps` rồi `docker stop …`.
2. Build image trên máy khác / x86 rồi `docker save | docker load` sang đây.
3. Dài hạn: cân nhắc chuyển `Docker Root Dir` khỏi NVMe (eMMC hoặc disk khác)
   nếu NVMe vẫn mất kết nối dưới tải I/O cao.

## Kiểm tra nhanh

```bash
curl -sS http://127.0.0.1:8100/healthz
curl -sS http://127.0.0.1:8100/readyz
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/
```

Từ máy khác trong LAN: mở `http://192.168.88.140:3000` và
`http://192.168.88.140:8100/docs`.

## Bật Google login sau này

1. Google Cloud Console → OAuth client (Web) → Authorized redirect URI **đúng**:
   `http://192.168.88.140:8100/api/v1/auth/google/callback`
2. Điền vào `.env`:
   - `OAUTH_GOOGLE_CLIENT_ID`
   - `OAUTH_GOOGLE_CLIENT_SECRET`
   - `OWNER_EMAIL` (hoặc `OWNER_GOOGLE_SUB`)
3. Restart API/web:

```bash
cd /mnt/ssd/personal-email-marketing-platform
docker compose -f infra/compose.yaml up -d --force-recreate api web
```

Với `APP_ENV=development`, nếu cả `OWNER_*` trống thì lần login Google đầu có thể tự nhận owner (có cảnh báo log) — chỉ dùng khi bạn chủ động muốn vậy.

## Dừng / dọn

```bash
cd /mnt/ssd/personal-email-marketing-platform
docker compose -f infra/compose.yaml down          # giữ volume DB/Redis/S3
docker compose -f infra/compose.yaml down -v       # XOÁ dữ liệu local
```

## Lưu ý vận hành trên máy này

- Không auto-start Docker từ agent; runbook này để bạn chạy tay.
- Host Python là 3.11; stack Compose dùng Python 3.12 trong image — ưu tiên Cách A (Compose).
- Cookie session do API set trên host `192.168.88.140` (cùng IP, khác port với web) — SameSite=Lax phù hợp LAN HTTP.
- `SESSION_COOKIE_SECURE` để trống → suy ra từ scheme `http` → cookie không `Secure` (đúng cho LAN HTTP).
