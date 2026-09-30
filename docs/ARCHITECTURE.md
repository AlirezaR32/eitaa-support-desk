# معماری — Eitaa Support Desk

این سند تصمیم‌های معماری، مدل داده، state machine و مسیرهای مقیاس‌پذیری را شرح می‌دهد.

## ۱. لایه‌ها و جریان داده

```text
Eitaa servers (TL-over-HTTPS, layer 135)
        │
        ▼
eitaa-cli 0.5.0 (pinned @ 685a71e)          ← کتابخانه غیررسمی
        │
        ▼
┌───────────────────────────────────────────────┐
│ Eitaa Adapter Layer (app/eitaa)               │
│  base.py     — EitaaClientAdapter protocol    │
│  adapter.py  — EitaaCliAdapter (تنها مصرف‌کننده eitaa-cli) │
│  registry.py — ساخت client از نشست رمزگشایی‌شده در حافظه │
│  exceptions  — سطح خطای مستقل از کتابخانه      │
└───────────────────────────────────────────────┘
        │                              │
        ▼                              ▼
 Sync Worker (polling)          Services (send/media)
 workers/sync_worker.py         services/message_service.py
        │                              │
        └──────────┬───────────────────┘
                   ▼
              PostgreSQL
        (dedup + state machine + audit)
                   │
                   ▼
     FastAPI (REST /api/v1 + WebSocket)
                   │
                   ▼
     React SPA (Vite, RTL, dark/light)
                   ▼
              Support Agents
```

### چرا Adapter مستقل؟

هر ۴۱۹ متد ایتا از طریق eitaa-cli قابل فراخوانی‌اند، اما هر تغییر سرور ایتا یا کتابخانه نباید بقیه سیستم را بشکند. `EitaaClientAdapter` یک Protocol پایتونی است:

```python
@runtime_checkable
class EitaaClientAdapter(Protocol):
    async def request_login_challenge(phone) -> EitaaLoginChallenge
    async def complete_login(phone, hash, code) -> EitaaSession
    async def verify_session(session) -> EitaaAccountInfo
    async def list_dialogs(session, limit) -> list[EitaaDialog]
    async def get_history(session, peer_ref, *, limit, min_id) -> list[EitaaMessage]
    async def send_text(session, peer_ref, text, *, reply_to) -> SendResult
    async def send_media(...) -> SendResult
    async def download_message_media(...) -> Path
    async def mark_read(...) -> bool        # best-effort
    ...
```

- پیاده‌سازی production: `EitaaCliAdapter` (همین فایل adapter.py)
- پیاده‌سازی تست: `FakeEitaaAdapter` در `tests/conftest.py` (test double، نه fake production)
- اگر eitaa-cli تغییر کند یا جایگزینی بیاید، فقط adapter.py بازنویسی می‌شود.

### نشست‌ها چگونه نگهداری می‌شوند؟

`EitaaClient(settings, _loaded_profile=SessionProfile(...))` در eitaa-cli اجازه می‌دهد client کاملاً از حافظه ساخته شود (بدون فایل session روی دیسک). ما payload کامل نشست (`phone_number`, `token`, `imei`, `user`) را با **Fernet** رمزنگاری و در `eitaa_accounts.session_encrypted` ذخیره می‌کنیم. هنگام هر عملیات، رمزگشایی فقط در حافظه انجام می‌شود. کلید از `EITAA_SESSION_ENCRYPTION_KEY` می‌آید (در production اجباری؛ در dev از SECRET_KEY مشتق می‌شود و هشدار داده می‌شود).

`phone_code_hash` فلوی OTP هم موقت و حساس است: در `auth_challenges` رمزنگاری‌شده، با TTL، و هرگز در پاسخ API یا log ظاهر نمی‌شود.

## ۲. State Machine گفتگو (مهم‌ترین تصمیم دامنه)

سه بُعد **مستقل** — نه یک enum واحد:

| فیلد | مقادیر | چه‌وقت تغییر می‌کند |
|---|---|---|
| `read_state` | `unread` / `read` | پیام جدید کاربر → `unread`؛ باز کردن توسط پشتیبان → `read` (فقط همین) |
| `answer_state` | `unanswered` / `answered` | آخرین پیام از کاربر → `unanswered`؛ ارسال موفق پشتیبان (از پنل یا از خود ایتا) → `answered`؛ **ارسال ناموفق تغییری نمی‌دهد** |
| `status` | `active` / `waiting_user` / `skipped` / `closed` | عملیات صریح پشتیبان + reopen خودکار با پیام جدید کاربر |

سناریوی حساس (§۱۱ و §۳۸ مشخصات):

```text
10:00  کاربر پیام می‌فرستد        → UNREAD + UNANSWERED
10:02  پشتیبان گفتگو را باز می‌کند  → READ   + UNANSWERED   ← تغییر answer_state ممنوع
10:15  هنوز پاسخ نداده             → READ   + UNANSWERED   ← فیلتر «بدون پاسخ» او را می‌گیرد
10:20  پشتیبان پاسخ می‌دهد         → READ   + ANSWERED
```

کل این منطق **سمت سرور** در `message_service._apply_message_side_effects` است؛ فرانت فقط نمایش می‌دهد.

## ۳. Sync Worker

```text
هر EITAA_SYNC_INTERVAL ثانیه:
  برای هر اکانت متصل و sync-enabled:
    pg_try_advisory_lock(key(account_id)) روی یک connection اختصاصی   ← بدون تداخل بین workerها
    dialogs = getDialogs(limit)
    برای هر dialog از kind مجاز:
      upsert conversation (unique: account_id + peer_type + peer_id)
      اگر dialog.top_message_id > conversation.last_message_id:
        history = getHistory(min_id=last_message_id)
        برای هر پیام:
          INSERT با unique(conversation_id, eitaa_message_id)   ← duplicate impossible
          آپدیت state machine + انتشار WebSocket
    آپدیت sync_state (موفقیت/شکست/خطا)
```

نکات پیاده‌سازی که در عمل درست شدند:

- **Advisory lock باید روی یک connection ثابت گرفته و آزاد شود.** lock روی connection الف و unlock روی connection ب (از pool) عملاً unlock نمی‌شود → پاسخ‌های `sync_all` صفر. راه‌حل: یک `engine.connect()` اختصاصی برای lock در کل طول pass.
- **rollback در مواجهه با IntegrityError** در ingest، شرط dedup است نه خطا؛ `None` برگردانده می‌شود.
- **باطل شدن نشست** (`AuthenticationRequired`) → اکانت `disconnected` + رویداد WebSocket + رکورد audit؛ سایر خطاها فقط در `sync_state.last_error`.
- پیام‌های outbound که از خود ایتا فرستاده شده‌اند (`out=true`) هم ingest می‌شوند (source=eitaa_app) و گفتگو را «پاسخ‌داده» می‌کنند.

## ۴. مدل داده (۱۶ جدول)

```text
roles ─┬─ users ──────────── refresh_tokens
       │     └─ user_permissions
permissions ─ role_permissions

eitaa_accounts ─┬─ agent_eitaa_accounts (کدام پشتیبان، کدام اکانت)
                ├─ auth_challenges (OTP در جریان — رمزنگاری‌شده)
                └─ conversations ─┬─ messages ──── message_attachments
                                  ├─ internal_notes
                                  ├─ notifications
                                  └─ sync_state (سطح اکانت)
audit_logs
```

Constraintهای کلیدی:

- `uq_conversation_peer`: `(eitaa_account_id, peer_type, peer_id)`
- `uq_message_eitaa`: `(conversation_id, eitaa_message_id)` — دقیقاً همان «unique بودن (account, peer, message_id)» مشخصات، با کلید فشرده‌تر
- `uq_notification_dedupe`: `(user_id, dedupe_key)` — dedupe اعلان‌ها
- ایندکس‌های ترکیبی برای فیلترهای Inbox: `(status, answer_state)`, `(assigned_agent_id)`, `(last_message_at)`
- ایندکس GIN با `pg_trgm` روی `messages.text` و `conversations.title` (best-effort در migration؛ اگر هاست اجازه نداد، ILAFF عادی کار می‌کند)

## ۵. امنیت

| لایه | مکانیزم |
|---|---|
| گذرواژه | Argon2 (pwdlib) |
| Access token | JWT کوتاه‌عمر (۳۰دقیقه) با `token_version` برای ابطال فوری |
| Refresh | opaque random، هش SHA-256 در DB، httpOnly cookie با path محدود، **چرخش + تشخیص reuse** (استفاده مجدد → ابطال کل خانواده) |
| CSRF | چون refresh فقط با cookie کار می‌کند، endpoint آن Origin را با allowlist اعتبارسنجی می‌کند |
| RBAC | داده‌محور (roles/permissions/role_permissions/user_permissions)؛ endpointها فقط `require("code")` می‌گویند |
| IDOR | هر endpoint مکالمه، `permitted_account_ids` را سمت سرور چک می‌کند |
| Rate limit | middleware پنجره ثابت (حافظه یا Redis با `REDIS_URL`) + سهمیه جدا برای auth |
| Upload | سقف حجم + allowlist پسوند + magic-byte sniffing (`filetype`) |
| Headers | nosniff, DENY, Referrer-Policy, HSTS در production |
| لاگ | فیلتر پاک‌سازی که کلیدهای حساس (token/otp/password/…) را ماسک می‌کند |
| Claim race | `UPDATE ... WHERE assigned_agent_id IS NULL` — اتمیک در سطح دیتابیس |

## ۶. Real-time (WebSocket)

`/api/v1/ws?token=<access>`؛ پس از احراز هویت، اتصال در `EventBus` با scope دسترسی کاربر ثبت می‌شود (`conversation.view.all` = همه؛ وگرنه فقط اکانت‌های متصل به او). سرویس‌ها رویداد منتشر می‌کنند:

- `message.created` / `message.updated`
- `conversation.updated`
- `notification.created` (فقط مخاطب مشخص)
- `eitaa_account.updated`

فرانت این رویدادها را به invalidation کش‌های TanStack Query تبدیل می‌کند → UI همه پشتیبان‌های مجاز هم‌زمان به‌روز می‌شود. اتصال با backoff نمایی وصل می‌ماند.

## ۷. مقیاس‌پذیری

وضعیت پیش‌فرض (تک‌نود): همه‌چیز در یک پروسه (API + sync + scheduler) — ساده و مناسب اکثر تیم‌های پشتیبانی.

برای مقیاس:

1. **جداسازی worker**: APIها با `RUN_SYNC_WORKER=false`، کانتینرهای worker جدا. advisory lock سازگاری چند worker را تضمین می‌کند.
2. **WebSocket چند‌نودی**: `EventBus` تک‌پروسه‌ای است؛ برای چند instance، همان interface با Redis pub/sub پیاده کنید (`REDIS_URL` از قبل در config هست) — بدون تغییر در سرویس‌ها چون همه از `bus.publish` استفاده می‌کنند.
3. **رسانه**: فایل‌ها در `UPLOADS_DIR` (volume)؛ برای S3-compatible storage، فقط `upload_service` و endpoint دانلود را عوض کنید.

## ۸. تصمیم‌های ثبت‌شده

| موضوع | تصمیم | چرا |
|---|---|---|
| eitaa-cli به‌صورت library درون‌پروسه، نه subprocess | import مستقیم | typed، بدون overhead پراسس، تزریق نشست حافظه‌ای ممکن |
| pin به commit | `685a71e` | build تکرارپذیر؛ تغییرات آینده کتابخانه کنترل‌شده وارد شود |
| email بدون deliverability-check | regex سینتکسی | دیپلوی‌های خصوصی با دامنه داخلی (مثل `owner@desk.local`) کار کنند |
| soft-delete پشتیبان | deactivation | حفظ یکپارچگی audit و ارجاع پیام‌ها |
| deep-link فقط با username | بدون حدس | الزام §۷ مشخصات؛ هرگز لینک ساختگی نساز |
| نشست ایتا در DB رمزنگاری‌شده، نه فایل | Fernet | پشتیبان‌گیری/restore ساده، امنیت at-rest، بدون وابستگی به دیسک محلی |
