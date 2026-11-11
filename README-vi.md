# Personal Email Marketing Platform

[English](README.md) | **Tiếng Việt**

Ứng dụng email marketing tự host, một chủ sở hữu duy nhất. Phase 1 hướng tới một người vận hành
được tin cậy: quản lý audience dựa trên consent, dựng template MJML/GrapesJS, lên lịch campaign, và
gửi email marketing qua các provider account đủ điều kiện một cách tường minh, đồng thời ghi nhận
kết quả do provider báo về. Data model đã sẵn sàng cho multi-tenant để Phase 2 có thể phục vụ nhiều
tenant độc lập.

## Mục lục

- [Trạng thái hiện tại](#trạng-thái-hiện-tại)
- [Tài liệu](#tài-liệu)
- [Công nghệ](#công-nghệ)
- [Các service](#các-service)
- [Yêu cầu trước khi cài đặt](#yêu-cầu-trước-khi-cài-đặt)
- [Bắt đầu nhanh (local)](#bắt-đầu-nhanh-local)
- [Cấu hình](#cấu-hình)
- [Phát triển cục bộ không cần toàn bộ Compose](#phát-triển-cục-bộ-không-cần-toàn-bộ-compose)
- [Kiểm thử và CI](#kiểm-thử-và-ci)
- [Cấu trúc repository](#cấu-trúc-repository)
- [Lộ trình](#lộ-trình)
- [Nguyên tắc bất biến (không thương lượng)](#nguyên-tắc-bất-biến-không-thương-lượng)

## Trạng thái hiện tại

Stage 0 (quyết định và nền tảng dự án) và Stage 1 (runtime, lưu trữ, và identity) đã hoàn tất. Đến
nay đã có:

- Stack Docker Compose: web, api, worker, scheduler, migration job, PostgreSQL 16, Redis 7, và một
  object store tương thích S3 chạy cục bộ.
- Kiểm tra cấu hình với các kiểm tra an toàn fail-closed cho production, request ID có cấu trúc, và
  mặc định logging an toàn.
- `/healthz` (liveness) và `/readyz` (readiness có nhận biết dependency, báo cáo chính xác trạng thái
  PostgreSQL và Redis).
- Schema Alembic ban đầu: tenants, users, memberships, sessions, và audit log; một workspace tenant
  duy nhất được bootstrap lúc khởi động.
- Đăng nhập Google OIDC login/callback có kiểm tra state, session phía server, logout/revocation, và
  owner allowlist fail-closed nghiêm ngặt.
- Các pattern repository/service theo tenant scope với ràng buộc composite gắn tenant.

Chưa nối: đăng nhập thật cần Google OAuth credentials và owner identity (xem
[Cấu hình](#cấu-hình)). Audience, content, campaign và gửi email sẽ có ở Stage 2 trở đi.

## Tài liệu

Các tài liệu nguồn (source of truth) nằm trong [`docs/initials/`](docs/initials/):

| Tài liệu | Nội dung |
|---|---|
| [PRD.md](docs/initials/PRD.md) | Yêu cầu sản phẩm và tiêu chí nghiệm thu |
| [SPEC.md](docs/initials/SPEC.md) | Schema, API contract, bất biến, bảo mật, release gate |
| [ARCHITECTURE.md](docs/initials/ARCHITECTURE.md) | Ranh giới service và topology triển khai |
| [IMPLEMENTATION_PLAN.md](docs/initials/IMPLEMENTATION_PLAN.md) | Kế hoạch triển khai theo stage |

Tài liệu bổ trợ:

| Tài liệu | Nội dung |
|---|---|
| [docs/decisions/](docs/decisions/) | Architecture decision record (ADR 0001-0007) |
| [docs/threat-model.md](docs/threat-model.md) | Threat model Phase 1, được rà soát mỗi stage |
| [docs/data-classification.md](docs/data-classification.md) | Quy tắc mã hoá, logging, lưu trữ và truy cập theo từng nhóm dữ liệu |
| [docs/deployment-limits.md](docs/deployment-limits.md) | Giới hạn tạm thời do người vận hành chỉnh (không phải cam kết sản phẩm) |
| [docs/provider-evaluation-resend.md](docs/provider-evaluation-resend.md) | Đánh giá provider đầu tiên (Resend) |
| [docs/runbooks/migrations.md](docs/runbooks/migrations.md) | Runbook migration, rollback, backup và phục hồi |

## Công nghệ

| Lớp | Lựa chọn |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic |
| Database | PostgreSQL 16 |
| Queue / cache | Redis 7 + Celery |
| Frontend | Next.js 14 (TypeScript), xử lý session phía server |
| Thiết kế email | GrapesJS + MJML |
| Object storage | Tương thích S3 (adobe/s3mock khi chạy cục bộ) |
| Triển khai | Docker Compose (một chủ sở hữu) |

## Các service

Backend là một modular monolith với các tiến trình api, worker và scheduler chạy độc lập.

| Service trong Compose | Vai trò |
|---|---|
| `web` | Giao diện Next.js |
| `api` | HTTP API FastAPI |
| `worker` | Celery worker |
| `scheduler` | Scheduler chỉ chạy một instance |
| `migrate` | Chạy một lần `alembic upgrade head`, trước khi `api` khởi động |
| `createbucket` | Tạo bucket một lần trong object store cục bộ |
| `postgres` | PostgreSQL 16 |
| `redis` | Redis 7 (broker/cache) |
| `object-storage` | Object store tương thích S3 cho upload object riêng tư |

## Yêu cầu trước khi cài đặt

- Docker Desktop (kèm Compose v2)
- Python 3.12+ và Node.js 20+ (chỉ cần khi chạy tooling ngoài Docker)

## Bắt đầu nhanh (local)

```bash
cp .env.example .env      # sau đó điền giá trị OAuth + owner identity
docker compose -f infra/compose.yaml up --build
```

Service và cổng mặc định:

| Service | URL |
|---|---|
| web | http://localhost:3000 |
| api | http://localhost:8000 |
| api docs | http://localhost:8000/docs |
| object storage (S3) | http://localhost:9000 |
| postgres | localhost:5432 |
| redis | localhost:6379 |

Migration chạy tự động qua service một lần `migrate` trước khi `api` khởi động, và `createbucket`
tạo bucket upload riêng tư.

## Cấu hình

Toàn bộ cấu hình dựa trên biến môi trường/secret. Xem [.env.example](.env.example) để biết tên biến
và placeholder an toàn cho môi trường cục bộ. Ứng dụng sẽ dừng khởi động nếu thiếu secret production
hoặc còn giá trị mặc định không an toàn. Không bao giờ commit `.env` thật hoặc credential của
provider.

Tối thiểu để đăng nhập được:

| Biến | Mục đích |
|---|---|
| `OAUTH_GOOGLE_CLIENT_ID` / `OAUTH_GOOGLE_CLIENT_SECRET` | Credential Google OIDC client |
| `OAUTH_GOOGLE_REDIRECT_URI` | Phải khớp callback URL trong Google console |
| `OWNER_GOOGLE_SUB` (ưu tiên) hoặc `OWNER_EMAIL` | Chủ sở hữu duy nhất được phép đăng nhập |
| `SESSION_KEY` | Khoá ký session, tối thiểu 32 byte |

`SESSION_COOKIE_SECURE` có thể để trống để tự suy ra từ scheme của `APP_BASE_URL`.

## Phát triển cục bộ không cần toàn bộ Compose

```bash
# backend
python -m venv .venv && .venv\Scripts\activate      # Windows PowerShell
pip install -e ".[dev]"
ruff check . && pytest

# frontend
npm install
npm run dev
```

## Kiểm thử và CI

```bash
ruff check .     # lint
pytest -q        # unit test
npm run lint     # lint frontend
npm run typecheck
```

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) chạy lint + unit test cho backend và
lint + typecheck cho frontend mỗi khi push lên `main` và mỗi pull request.

## Cấu trúc repository

```text
apps/web/            Giao diện Next.js
services/api/app/    FastAPI app, domain service, worker, provider, event, bảo mật
migrations/          Migration Alembic
infra/               compose.yaml, Dockerfile, monitoring
packages/            Package frontend dùng chung (api client, schema)
docs/                initials, decisions, runbooks, đánh giá provider
tests/               unit, integration, e2e, fixtures
```

## Lộ trình

Thứ tự triển khai theo phụ thuộc; xem
[IMPLEMENTATION_PLAN.md](docs/initials/IMPLEMENTATION_PLAN.md) để biết task và exit gate.

| Stage | Nội dung | Trạng thái |
|---|---|---|
| 0 | Quyết định và nền tảng dự án | Xong |
| 1 | Runtime, lưu trữ, và identity | Xong |
| 2 | Audience, import, consent, và suppression | Tiếp theo |
| 3 | Content và template | Dự kiến |
| 4 | Campaign model, snapshot, và scheduling | Dự kiến |
| 5 | Provider gateway và định tuyến capacity hợp lệ | Dự kiến |
| 6 | Webhook, unsubscribe, và analytics | Dự kiến |
| 7 | Gia cố bảo mật, vận hành, và release | Dự kiến |
| - | Phase 2: SaaS multi-tenant | Ngoài phạm vi Phase 1 |

## Nguyên tắc bất biến (không thương lượng)

- Lưu trữ contact tách biệt với năng lực gửi; quota của provider là yếu tố bên ngoài, theo từng
  account phía provider, không bao giờ suy ra từ số lượng API key.
- Gửi marketing yêu cầu account đủ điều kiện một cách tường minh và không cũ; account chỉ dùng cho
  transactional thì không đủ điều kiện.
- Kết quả submit không rõ ràng (`ambiguous`) phải chuyển thành `unknown`; không retry mù quáng và
  không failover sang account khác.
- Suppression là nguồn chân lý và được kiểm tra lại ngay trước mỗi lần submit lên provider.
- Số liệu về quota, giá, và quyền hạn không bao giờ bị hard-code thành cam kết sản phẩm.
