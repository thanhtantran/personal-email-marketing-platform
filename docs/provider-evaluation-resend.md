# Provider Evaluation — Resend

Review date: 2026-11-09

Đánh giá này phục vụ cho việc viết một Architecture Decision Record (ADR) về việc có nên implement một adapter gửi email qua Resend cho nền tảng email marketing self-hosted, single-owner hay không. Tài liệu **chỉ nghiên cứu**, không chứa mã ứng dụng.

**Phương pháp:** Toàn bộ dữ kiện dưới đây được lấy trực tiếp từ tài liệu chính thức của Resend (resend.com/docs, resend.com/pricing, resend.com/legal) và xác minh tại thời điểm `2026-11-09`. Mỗi khẳng định đều kèm URL nguồn chính thức. Khi không thể xác nhận từ nguồn chính thức, tài liệu ghi rõ **UNVERIFIED** thay vì suy đoán.

> ⚠️ **CẢNH BÁO QUAN TRỌNG — SỰ KIỆN BÊN NGOÀI, CÓ THỂ THAY ĐỔI**
>
> Quota, giới hạn tốc độ, hạn mức, giá, các gói dịch vụ, điều khoản pháp lý (AUP/ToS) và quyền gửi marketing **là các dữ kiện bên ngoài (external facts) do Resend quy định, có thể thay đổi bất kỳ lúc nào mà không cần báo trước**. Chúng **KHÔNG phải** là bảo đảm (guarantee) của sản phẩm. Người vận hành (operator) **BẮT BUỘC** phải kiểm tra lại toàn bộ các con số/điều khoản này trên trang chính thức của Resend **trước khi bật adapter**, và **TUYỆT ĐỐI KHÔNG được hard-code** chúng vào sản phẩm như những hằng số bảo đảm. Mọi giá trị dưới đây chỉ mang tính mô tả "tại thời điểm review".

---

## Sources (nguồn chính thức)

- Resend Docs — Introduction: https://resend.com/docs/introduction
- Resend Docs — Which sending feature to use (transactional vs marketing): https://resend.com/docs/knowledge-base/what-sending-feature-to-use
- Resend — Acceptable Use Policy: https://resend.com/legal/acceptable-use-policy (canonical: https://resend.com/legal/acceptable-use)
- Resend — Terms of Service: https://resend.com/legal/terms-of-service
- Resend — Privacy Policy: https://resend.com/legal/privacy-policy
- Resend — Subprocessors: https://resend.com/legal/subprocessors
- Resend — Pricing: https://resend.com/pricing
- Resend Docs — Add and verify a domain: https://resend.com/docs/add-a-domain
- Resend Docs — Verified Domains: https://resend.com/docs/dashboard/domains/introduction
- Resend Docs — Implementing DMARC: https://resend.com/docs/dashboard/domains/dmarc
- Resend Docs — Choosing a Region: https://resend.com/docs/dashboard/domains/regions
- Resend Docs — Account quotas and limits: https://resend.com/docs/knowledge-base/account-quotas-and-limits
- Resend Docs — API Reference — Usage Limits (rate + quota): https://resend.com/docs/api-reference/rate-limit
- Resend Docs — API Reference — Introduction: https://resend.com/docs/api-reference/introduction
- Resend Docs — API Reference — Errors: https://resend.com/docs/api-reference/errors
- Resend Docs — API Reference — Send Email: https://resend.com/docs/api-reference/emails/send-email
- Resend Docs — API Reference — Send Batch Emails: https://resend.com/docs/api-reference/emails/send-batch-emails
- Resend Docs — API Reference — Retrieve Sent Email: https://resend.com/docs/api-reference/emails/retrieve-email
- Resend Docs — Idempotency Keys: https://resend.com/docs/dashboard/emails/idempotency-keys
- Resend Docs — Webhooks — Verify Webhooks Requests: https://resend.com/docs/dashboard/webhooks/verify-webhooks-requests
- Resend Docs — Webhooks — Event Types: https://resend.com/docs/dashboard/webhooks/event-types
- Resend Docs — Webhooks — Retries and Replays: https://resend.com/docs/dashboard/webhooks/retries-and-replays
- Resend Docs — Webhooks — How to Store Webhooks Data: https://resend.com/docs/dashboard/webhooks/how-to-store-webhooks-data
- Resend Docs — Does Resend require production approval: https://resend.com/docs/knowledge-base/does-resend-require-production-approval

---

## 1. Có được phép gửi marketing / bulk không?

**Kết luận: CÓ.** Resend phân biệt rõ hai loại gửi và cho phép cả hai:

- *"Resend is the email API for developers... you'll be ready to send **both types of emails**: Transactional emails... **Marketing campaigns: bulk email Broadcasts distributed to a contact list**."*
  — https://resend.com/docs/introduction
- Marketing email được định nghĩa: *"A Marketing email is any email that is not transactional... recipients **must have the option to unsubscribe**. Examples of marketing emails: Promotional offers and discounts, Newsletters, Product updates."*
  — https://resend.com/docs/knowledge-base/what-sending-feature-to-use
- Về kênh gửi: *"transactional emails are emails sent using the `/emails` API, while marketing emails are sent using the `/broadcasts` API or through the Broadcasts interface in the dashboard."* và *"Can I send my newsletter through the `/emails` API instead of Broadcasts? **Yes.**"* — nhưng khi gửi newsletter qua `/emails` API thì *"need your own visible unsubscribe link plus the `List-Unsubscribe` and `List-Unsubscribe-Post` headers"*, và mỗi người nhận tính 1 email vào quota transactional.
  — https://resend.com/pricing (mục FAQ)

**Điều kiện ràng buộc (AUP) — trích nguyên văn:**
Từ Acceptable Use Policy (https://resend.com/legal/acceptable-use-policy):

- *"All mail must be sent to recipients who have **explicitly opted in** to receive communications from you. Sending to unsolicited recipients is not permitted on Resend."*
- *"For any bulk sending, you are also required to: 1. Include a valid address and company name in the email 2. Explicitly disclose why you are contacting the recipient 3. Provide a frictionless way to opt-out (unsubscribe) and honor their wish within 7 days 4. Be confident that your message provides them with value 5. Follow any and all applicable laws and regulations."*
- *"**Your complaint rate must be lower than 0.08%.**"* và *"**Your bounce rate must be lower than 4%.**"* — *"If complaint or bounce rates go above these thresholds, your account may be shut down without warning."*
- *"**Spamming**: You are prohibited from sending unsolicited messages of any kind, including cold outreach, purchased lists, or scraped contact data."*
- *"Users are expressly forbidden from creating or using an account or multiple accounts with the aim of **circumventing any quotas or limits**."*

Hàm ý cho nền tảng: marketing/bulk hợp lệ **về mặt chính sách**, nhưng nền tảng phải đảm bảo consent, có unsubscribe, và theo dõi complaint/bounce rate để không vượt ngưỡng. Xem thêm ràng buộc cấm về ngành/nội dung (pornography, gambling, pharma, MLM, debt collection, v.v.) trong cùng AUP nếu sản phẩm phục vụ ngành dọc cụ thể.

---

## 2. Sender identity / yêu cầu xác minh domain (SPF, DKIM, DMARC, onboarding@resend.dev)

- Bắt buộc domain riêng: *"Resend sends emails using a domain you own (i.e., not a shared or public domain). You must **add and verify at least one domain** to send emails with Resend."* — https://resend.com/docs/dashboard/domains/introduction
- Khuyến nghị gửi từ **subdomain**: *"We strongly recommend sending emails from a subdomain (e.g., `notifications.example.com`) instead of your root domain"*; mỗi subdomain phải được add/verify riêng. — https://resend.com/docs/add-a-domain
- DNS record cần thiết: *"Provide the **DKIM and SPF** configurations (`TXT` and `MX` or `CNAME` records) to your DNS provider. These records must match exactly what Resend generated."* — https://resend.com/docs/add-a-domain
  - Ví dụ record SPF (MX + TXT) và DKIM (`resend._domainkey`) được liệt kê trong payload webhook `domain.created`. — https://resend.com/docs/dashboard/webhooks/event-types
- DMARC là bước **bổ sung, thực hiện sau khi domain đã verify**: *"After your domain is verified, you can then implement DMARC."* DMARC dựa trên SPF+DKIM: *"If you have a verified domain with Resend, it means you are already passing SPF and DKIM."* Mẫu record: `_dmarc.example.com TXT "v=DMARC1; p=none; rua=mailto:..."`. — https://resend.com/docs/dashboard/domains/dmarc
- Return-Path mặc định `send.example.com` (có thể tùy chỉnh) — https://resend.com/docs/add-a-domain
- Xác minh DNS: thường trong ~15 phút, tối đa tới 72 giờ — https://resend.com/docs/add-a-domain
- `onboarding@resend.dev`: dùng làm sender ví dụ trong tài liệu. **Hạn chế:** chưa verify domain thì chỉ gửi được tới email của chính bạn: *"You can only send testing emails to your own email address... To send emails to other recipients, please verify a domain at resend.com/domains, and change the `from` address to an email using this domain."* — https://resend.com/docs/api-reference/errors (lỗi `validation_error`, 403)
- Sau khi domain verified: *"Send and receive emails using any email address at your domain without any extra configuration."* — https://resend.com/docs/dashboard/domains/introduction
- Không cần "production approval": *"No, Resend does not require production approval. All accounts, including free accounts, have immediate production access."* — https://resend.com/docs/knowledge-base/does-resend-require-production-approval

---

## 3. Rate limits & quota model (RPS, giới hạn ngày/tháng, Free vs Paid)

> Nhắc lại: các con số dưới đây là **dữ kiện bên ngoài tại thời điểm review (2026-11-09)**, KHÔNG phải bảo đảm sản phẩm. Operator phải tự xác minh lại.

**Rate limit (requests/second):**
- *"All accounts start with a rate limit of **10 requests per second**."* — https://resend.com/docs/knowledge-base/account-quotas-and-limits
- *"The default maximum rate limit is **10 requests per second per team**... **The rate limit is per team, not per API key or per domain.** All API keys associated with your team share the same rate limit pool."* — https://resend.com/docs/api-reference/rate-limit
- *"There is no separate burst allowance above the stated limit. If your limit is 10 requests per second, an eleventh request in the same second window will receive a `429` response."* — https://resend.com/docs/knowledge-base/account-quotas-and-limits
- Vượt → `429` (`rate_limit_exceeded`). Có thể yêu cầu tăng qua support. — https://resend.com/docs/api-reference/errors
- *"Does upgrading my plan raise the API rate limit? **No.** The API rate limit (requests per second) is set per team and is the same on every plan."* — https://resend.com/pricing (FAQ)

**Quota email (gửi + nhận đều tính):**
- Free: **100 emails/ngày** và **3.000 emails/tháng**. *"The daily quota is a UTC calendar day (00:00–24:00 UTC) and resets at midnight UTC."* — https://resend.com/docs/knowledge-base/account-quotas-and-limits
- Pro (tại thời điểm review): **50.000 emails/tháng**, **không có giới hạn ngày**.
- Scale: **100.000 emails/tháng**, không giới hạn ngày.
- *"Paid sending plans have no daily quota, only the monthly limit."* — https://resend.com/docs/api-reference/rate-limit
- Nhiều người nhận trên `To`/`CC`/`BCC` tính thành nhiều email: *"Multiple `To`, `CC`, or `BCC` recipients in sent emails count as separate emails towards this quota."* — https://resend.com/docs/knowledge-base/account-quotas-and-limits
- Giới hạn batch/số người nhận: `/emails` cho phép `to` **tối đa 50** địa chỉ; Batch API gửi **tối đa 100 email trong 1 request** và *"each batch request counts as a single request against the limit."* — https://resend.com/docs/api-reference/emails/send-email ; https://resend.com/docs/api-reference/emails/send-batch-emails ; https://resend.com/docs/knowledge-base/account-quotas-and-limits

**Marketing quota (Broadcasts):**
- Free: *"unlimited emails to up to 1.000 contacts per month."* — https://resend.com/docs/knowledge-base/account-quotas-and-limits
- *"Broadcast emails... do **not** count against your transactional email limits."* — https://resend.com/pricing (FAQ)

**Overage (vượt hạn mức):**
- Paid plan có pay-as-you-go overage, chia theo bucket 1.000 emails/giá overage; hard cap mặc định **5x quota tháng**, vượt thì *"sending will be paused until the next billing cycle."* — https://resend.com/docs/knowledge-base/account-quotas-and-limits ; https://resend.com/pricing

**Cách đọc usage:**
- Response header: `ratelimit-limit`, `ratelimit-remaining`, `ratelimit-reset`, `retry-after`; quota: `x-resend-daily-quota` (chỉ gửi cho free plan) và `x-resend-monthly-quota`. — https://resend.com/docs/api-reference/rate-limit

---

## 4. Idempotency cho send API

**Có hỗ trợ idempotency key.** Chi tiết:

- Header: `Idempotency-Key` (với SMTP dùng email header `Resend-Idempotency-Key`). — https://resend.com/docs/dashboard/emails/idempotency-keys
- Hỗ trợ trên endpoint: `POST /emails` và `POST /emails/batch` (ngoài ra còn các endpoint Inboxes). — https://resend.com/docs/dashboard/emails/idempotency-keys
- Ràng buộc: *"Should be **unique per API request**"*; *"Idempotency keys expire after **24 hours**"*; *"Have a maximum length of **256 characters**"*. — https://resend.com/docs/api-reference/emails/send-email
- Cơ chế: *"Resend checks whether an email with the same idempotency key has already been sent in the last 24 hours... you can make the same request and our API will give the same response, without actually sending the email again."* — https://resend.com/docs/dashboard/emails/idempotency-keys
- Phản hồi lỗi liên quan:
  - `400 invalid_idempotency_key` — key phải dài 1–256 ký tự.
  - `409 invalid_idempotent_request` — *"This idempotency key has been used with this HTTP method and endpoint within the last 24 hours, but the request body was modified and doesn't match the original request."* (retry vô nghĩa).
  - `409 concurrent_idempotent_requests` — *"another request with the same idempotency key is in progress... it is safe to retry this request later if needed."*
  — https://resend.com/docs/dashboard/emails/idempotency-keys ; https://resend.com/docs/api-reference/errors

**Phạm vi (scope):** tài liệu mô tả key được kiểm tra theo **HTTP method + endpoint** trong 24 giờ (ví dụ `POST /emails` vs `POST /emails/batch` là hai không gian riêng). Việc key có được chia sẻ giữa nhiều team/account hay không **không được nêu rõ** — coi là **UNVERIFIED** ở mức chi tiết này. Thực tế nên tạo key unique (UUID) cho từng email để tránh đụng độ.

---

## 5. Webhook: chữ ký (Svix), event types, event ID để dedup

**Xác minh chữ ký — dùng Svix:**
- Webhook được ký với Svix. Header gồm `svix-id`, `svix-timestamp`, `svix-signature`. Secret lấy từ trang chi tiết webhook, hoặc trả về qua API create/retrieve/list webhook. — https://resend.com/docs/dashboard/webhooks/verify-webhooks-requests
- Xác minh bằng SDK Resend (`resend.webhooks.verify({ payload, headers, webhookSecret })`) hoặc trực tiếp thư viện Svix (`new Webhook(secret).verify(payload, headers)`). **Phải dùng raw request body** khi verify: *"The cryptographic signature is sensitive to even the slightest change... Make sure that you're using the raw request body."* — https://resend.com/docs/dashboard/webhooks/verify-webhooks-requests
- Chống replay: timestamp trong `svix-timestamp` (Svix docs). Resend không chi tiết cửa sổ tolerance trong trang này.

**Event types khả dụng** (payload có trường `type`, `created_at`, `data`): — https://resend.com/docs/dashboard/webhooks/event-types
- `email.sent` — API request thành công, Resend sẽ cố gửi tới mail server người nhận.
- `email.delivered` — gửi thành công tới mail server người nhận.
- `email.delivery_delayed` — lỗi tạm thời (hộp thư đầy, server nhận gặp sự cố transient).
- `email.complained` — đã delivered nhưng người nhận đánh dấu spam.
- `email.bounced` — bị mail server người nhận từ chối vĩnh viễn (payload có `bounce.type` Permanent/Transient, `bounce.subType`).
- `email.opened` — người nhận mở email.
- `email.clicked` — người nhận click link (payload có `click`).
- `email.received` — nhận email (inbound).
- `email.failed` — gửi thất bại do lỗi (invalid recipients, API key, domain chưa verify, **email quota limits**, v.v.); payload có `failed.reason` (ví dụ `reached_daily_quota`).
- Ngoài email: `contact.created/updated/deleted`, `domain.created/updated/deleted`.

**Event ID để dedup:**
- *"**Event ID** - The unique `svix-id` for deduplication"* — đây là ID dùng để khử trùng lặp khi lưu trữ event. — https://resend.com/docs/dashboard/webhooks/how-to-store-webhooks-data
- `data.email_id` liên kết event về lần gửi gốc (dùng để map về email đã gửi). — https://resend.com/docs/dashboard/webhooks/event-types

**Retry / replay:**
- Retry tự động theo lịch exponential backoff: *"Immediately, 5 seconds, 5 minutes, 30 minutes, 2 hours, 5 hours, 10 hours, 10 hours"*. — https://resend.com/docs/dashboard/webhooks/retries-and-replays
- Nếu endpoint không trả `200`, Resend sẽ retry; có thể replay thủ công (cả event failed lẫn succeeded) từ dashboard. — https://resend.com/docs/dashboard/webhooks/introduction ; https://resend.com/docs/dashboard/webhooks/retries-and-replays
- IP nguồn webhook (dùng cho allowlist): `44.228.126.217`, `50.112.21.217`, `52.24.126.164`, `54.148.139.208`, `2600:1f24:64:8000::/52`. — https://resend.com/docs/dashboard/webhooks/introduction

---

## 6. Reconciliation: tra cứu theo message id sau timeout & tính "definitive" của response

**Tra cứu sau khi gửi:** có API `GET /emails/:email_id` trả về trạng thái mới nhất.
- Response gồm `id`, `message_id` (SMTP Message-ID), `to/from/subject`, `last_event`, `tags`, v.v. — https://resend.com/docs/api-reference/emails/retrieve-email
- `last_event` phản ánh event gần nhất (ví dụ `delivered`); danh sách `last_event` theo "Email Events overview". — https://resend.com/docs/api-reference/emails/retrieve-email
- Vì vậy: nếu bạn **có** `email_id` (từ response gửi thành công), có thể tra cứu lại sau một timeout mơ hồ để reconcile trạng thái. Nếu bạn **không** có `email_id` (ví dụ request timeout trước khi nhận response), thì không có API lookup theo dữ liệu tự tạo — phải dựa vào `Idempotency-Key` để retry an toàn (mục 4).

**Response gửi có "definitive" không?**
- Send thành công trả `{ "id": "..." }` — xác nhận **đã được chấp nhận (accepted) để gửi**, *không* đồng nghĩa đã delivered. — https://resend.com/docs/api-reference/emails/send-email ; https://resend.com/docs/dashboard/webhooks/event-types (`email.sent` = "API request was successful")
- Sau khi accepted, trạng thái cuối cùng đến qua webhook hoặc `GET /emails/:id` (`delivered`, `bounced`, `complained`, `failed`, ...). Đặc biệt `email.failed` có thể xảy ra **bất đồng bộ** (ví dụ chạm quota → `reached_daily_quota`), tức một send đã "accepted" vẫn có thể thất bại ở tầng gửi. — https://resend.com/docs/dashboard/webhooks/event-types
- Kết luận: response send là definitive về mặt **acceptance**, KHÔNG definitive về **delivery**. Reconciliation dựa trên webhook + `last_event` là cần thiết.

---

## 7. Ràng buộc khu vực / pháp lý

**Vùng gửi (sending regions):** Resend hỗ trợ 4 vùng cho transactional và marketing:
- North Virginia (`us-east-1`), Ireland (`eu-west-1`), São Paulo (`sa-east-1`), Tokyo (`ap-northeast-1`). — https://resend.com/docs/dashboard/domains/regions

**Data residency (quan trọng):**
- *"Region selection controls where your emails are **routed and sent from**. It does **not** control where customer data is stored. **All account data, including email metadata, logs, and API records, is stored in the United States** regardless of the sending region you select."* — https://resend.com/docs/dashboard/domains/regions
- *"If your organization has strict data residency requirements, review the Resend Subprocessors list and Privacy Policy."* — https://resend.com/docs/dashboard/domains/regions ; https://resend.com/legal/subprocessors ; https://resend.com/legal/privacy-policy

**Pháp nhân & luật điều chỉnh:**
- Nhà cung cấp: **Plus Five Five, Inc.** — https://resend.com/legal/terms-of-service
- Governing law: *"These Terms shall be governed and construed in accordance with the laws of the **State of California** without regard to its conflict of law provisions."* — https://resend.com/legal/terms-of-service (mục "Governing Law")
- Tuân thủ: Tài liệu nêu GDPR compliance và SOC 2 Type II là tính năng trên bảng pricing. — https://resend.com/pricing
- Chuyển vùng dữ liệu: multi-region là tính năng trên pricing (dấu ✓ ở cột plan), nhưng như trên, không đổi nơi lưu account data. — https://resend.com/pricing ; https://resend.com/docs/dashboard/domains/regions

**Hàm ý:** Với yêu cầu lưu trữ dữ liệu tại EU/khác US, tính năng chọn region của Resend **không đáp ứng** (chỉ đổi vùng gửi đi). Đây là điểm rủi ro cần ghi vào ADR nếu nền tảng có ràng buộc data residency.

---

## 8. Hạn chế liên quan tới quota-aware routing

**Quota là theo account/team, không theo domain hay API key:**
- Rate limit: *"The rate limit is **per team**, not per API key or per domain."* — https://resend.com/docs/api-reference/rate-limit
- Email quota: theo plan của account/team (daily/monthly), gộp gửi + nhận. — https://resend.com/docs/knowledge-base/account-quotas-and-limits
- Contact quota (marketing): theo plan. — https://resend.com/docs/api-reference/rate-limit
- Hệ quả: nhiều domain/subdomain cùng một team vẫn **dùng chung** một pool rate limit và một quota email. Không thể "routing" để né quota bằng cách rải sang domain khác trong cùng team.

**Có API đọc usage/quota hiện tại không?**
- Trong tài liệu chính thức **không mô tả một REST API endpoint để đọc usage/quota**. Cách đọc usage được nêu là: dashboard **Usage page** (`https://resend.com/settings/usage`) và các **response header** sau mỗi request (`ratelimit-*`, `x-resend-daily-quota`, `x-resend-monthly-quota`). — https://resend.com/docs/api-reference/rate-limit ; https://resend.com/docs/knowledge-base/account-quotas-and-limits
- ⚠️ Việc tồn tại một endpoint usage/quota "ẩn"/không công bố là **UNVERIFIED**. Do đó, routing/quyết định quota nên dựa trên header response + state nội bộ (đếm email trong ngày/tháng tại phía nền tảng).

**Không được lách quota bằng nhiều account:** *"Users are expressly forbidden from creating or using an account or multiple accounts with the aim of circumventing any quotas or limits."* — https://resend.com/legal/acceptable-use-policy

---

## Adapter implications (ánh xạ HTTP response → `SubmitResult`)

Bảng dưới map phản hồi của Resend vào contract `SubmitResult` của nền tảng: `accepted` / `definitive_transient_rejection` / `definitive_permanent_rejection` / `ambiguous`.

| Tình huống Resend | HTTP | Loại lỗi / ghi chú | Ánh xạ `SubmitResult` |
|---|---|---|---|
| Gửi thành công | `200` | Response `{ "id": "..." }` (đã accepted, chưa chắc delivered) | **accepted** |
| `validation_error` (field sai), `invalid_attachment`, `missing_required_field`, `missing_required_parameter`, `invalid_parameter` | `400`, `422` | Lỗi payload phía client | **definitive_permanent_rejection** |
| `invalid_idempotency_key` | `400` | Key sai định dạng | **definitive_permanent_rejection** |
| `missing_api_key` / API key invalid / `restricted_api_key` / `suspended_api_key` | `401` / `403` | Sai/hết hạn/thu hồi key | **definitive_permanent_rejection** |
| Domain chưa verify, `domain mismatch`, `onboarding@resend.dev` gửi ra ngoài, `email_above_quota` | `403` | Cấu hình/domain | **definitive_permanent_rejection** |
| `invalid_idempotent_request` (cùng key, payload khác) | `409` | Retry vô nghĩa | **definitive_permanent_rejection** |
| `concurrent_idempotent_requests`, `resource_locked` | `409` | Đang xử lý song song | **definitive_transient_rejection** (retry sau) |
| `rate_limit_exceeded` | `429` | Vượt RPS | **definitive_transient_rejection** (dùng `retry-after`/`ratelimit-reset`) |
| `daily_quota_exceeded` | `429` | Hết quota ngày (reset 00:00 UTC) | **definitive_transient_rejection** (retry sau khi reset) |
| `monthly_quota_exceeded` | `429` | Hết quota tháng (reset chu kỳ billing) | **definitive_transient_rejection** (retry ở chu kỳ sau) |
| `application_error` | `500` | Lỗi hạ tầng Resend | **definitive_transient_rejection** (retry có backoff) |
| `service_unavailable` | `503` | Tạm thời không khả dụng | **definitive_transient_rejection** (retry có backoff) |
| Timeout / connection drop / không có response, hoặc `409 concurrent_idempotent_requests` khi chưa rõ kết quả | — | Không xác định kết quả | **ambiguous** → retry bằng cùng `Idempotency-Key` (24h) và/hoặc reconcile qua `GET /emails/:id` |

**Lưu ý cho adapter:**
- Phải gửi header `User-Agent` (request thiếu → `403` code `1010`). — https://resend.com/docs/api-reference/introduction
- **Bật idempotency key** cho mọi send để `ambiguous` + retry trở nên an toàn; lưu ý key chỉ sống **24 giờ** và không dùng lại key với payload khác.
- `accepted` **không** đồng nghĩa delivered — cần pipeline webhook (dedup theo `svix-id`, map theo `data.email_id`) và/hoặc polling `GET /emails/:id` (`last_event`) để có trạng thái cuối. `email.failed` có thể đến **bất đồng bộ** cho các lỗi như quota.
- Webhook **phải verify chữ ký Svix trên raw body**; dùng `svix-id` để dedup.
- Quota/rate là **per team**; routing không né được quota trong cùng team, và bị cấm tạo nhiều account để lách quota.
- Không hard-code các con số (RPS, quota, giá, giới hạn ngày) — đọc động từ response header và/hoặc cấu hình của operator.

---

### Điểm chưa xác minh (UNVERIFIED)

- Scope chính xác của `Idempotency-Key` ở mức team/account (tài liệu chỉ nêu "per API request" và "theo method + endpoint trong 24 giờ").
- Sự tồn tại của một REST API công khai để **đọc usage/quota hiện tại** (tài liệu chỉ nêu dashboard Usage page và response headers).
- Cửa sổ tolerance timestamp chính xác khi verify chữ ký Svix (Resend không nêu con số; phụ thuộc Svix).
