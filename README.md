# Eitaa Support Desk

پنل پشتیبانی حرفه‌ای (Helpdesk) برای **ایتا** — چند پشتیبان، چند اکانت، بلادرنگ.

یک سیستم کامل برای دریافت پیام‌های کاربران ایتا، نمایش مکالمات در پنل وب، پاسخ‌دهی چند پشتیبان همزمان، اختصاص و وضعیت‌بندی گفتگوها، یادداشت داخلی، لاگ کامل فعالیت، اعلان گفتگوهای بدون پاسخ و مدیریت اکانت‌های ایتا — با اتصال از طریق کتابخانه [`eitaa-cli`](https://github.com/EhsanAhmadzadeh/eitaa-cli).

![stack](https://img.shields.io/badge/Backend-FastAPI%20%2B%20SQLAlchemy%202%20async%20%2B%20PostgreSQL-0d9488)
![stack](https://img.shields.io/badge/Frontend-React%2019%20%2B%20Vite%20%2B%20Tailwind%204-0d9488)
![pkg](https://img.shields.io/badge/package%20manager-Bun-0d9488)

---

## فهرست

1. [قابلیت‌ها](#قابلیت‌ها)
2. [معماری](#معماری)
3. [پیش‌نیازها](#پیش‌نیازها)
4. [راه‌اندازی Development (گام‌به‌گام)](#راه‌اندازی-development)
5. [راه‌اندازی با Docker Compose](#راه‌اندازی-با-docker-compose)
6. [مهاجرت‌های دیتابیس (Alembic)](#مهاجرت‌های-دیتابیس)
7. [تست‌ها](#تست‌ها)
8. [API و مستندات](#api-و-مستندات)
9. [Deploy در Production](docs/DEPLOYMENT.md)
10. [محدودیت‌های واقعی Eitaa](#محدودیت‌های-واقعی-eitaa)
11. [متغیرهای محیطی](#متغیرهای-محیطی)
12. [عیب‌یابی](#عیب‌یابی)

---

## قابلیت‌ها

| حوزه | جزئیات |
|---|---|
| **Inbox حرفه‌ای** | لیست گفتگوها با پیش‌نمایش، جستجوی سراسری (نام/یوزرنیم/متن پیام/شناسه)، فیلترهای ترکیبی، صفحه‌بندی واقعی |
| **دسته‌بندی** | همه، خوانده‌نشده، خوانده‌شده، بدون پاسخ، پاسخ‌داده‌شده، اختصاص‌یافته به من، بدون پشتیبان، در انتظار کاربر، ردشده، بسته — **ترکیب‌پذیر** (مثلاً «خوانده‌نشده + بدون پشتیبان») |
| **وضعیت دقیق (Server-side)** | سه بُعد مستقل: `read_state` (خوانده/ناشناخته)، `answer_state` (پاسخ‌داده/بدون‌پاسخ)، `status` (فعال/در انتظار کاربر/ردشده/بسته). سناریوی §۱۱: باز کردن بدون پاسخ = **READ + UNANSWERED** |
| **تخصیص** | Assign / Reassign / **Claim** (اتمیک و ضد race) / Release / Take-over |
| **پیام‌ها** | دریافت و ارسال Text / تصویر / ویس / صوت / ویدیو / فایل + Caption؛ Reply به پیام مشخص؛ وضعیت ارسال (در حال ارسال/ارسال‌شده/ناموفق) با **تلاش مجدد** |
| **یادداشت داخلی** | برای هر گفتگو؛ هرگز برای کاربر ایتا ارسال نمی‌شود و در UI کاملاً متمایز است |
| **Real-time** | WebSocket با احراز هویت و scope دسترسی — بدون refresh |
| **Sync Worker** | Polling قابل تنظیم (`EITAA_SYNC_INTERVAL`) + PostgreSQL advisory lock + جلوگیری از پردازش تکراری با unique constraint |
| **اعلان‌ها** | تشخیص خودکار گفتگوهای بدون پاسخ (>۱۰ دقیقه) بدون duplicate؛ شمارنده badge |
| **Dashboard** | شمارنده‌ها و آمار (میانگین اولین پاسخ، میانگین حل، پیام‌های امروز، پشتیبان‌های فعال) — فقط از داده واقعی DB |
| **چنداکانتی** | چند اکانت ایتا؛ هر پشتیبان فقط اکانت‌های متصل به خود را می‌بیند |
| **اتصال اکانت ایتا** | ویزارد OTP (شماره → کد → متصل)؛ **نشست رمزنگاری‌شده (Fernet)** در دیتابیس |
| **RBAC قابل توسعه** | نقش‌ها/مجوزها داده‌محور در DB (Owner/Admin/Agent) + override per-user |
| **Audit Log** | تمام عملیات مهم باActor/زمان/هدف؛ بدون داده حساس |
| **امنیت** | Argon2، JWT + refresh rotation با تشخیص reuse، rate limiting، اعتبارسنجی upload (حجم/پسوند/magic bytes)، secure headers، CORS محدود، ضد IDOR |
| **UI** | فارسی/RTL، Dark/Light، کلیدهای میان‌بر (J/K/Ctrl+K/R/C/?)، Skeleton، Empty/Error states، Toast، ضبط ویس در مرورگر |

## معماری

خلاصه (شرح کامل در [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)):

```text
                Eitaa (TL-over-HTTPS)
                         │
                         ▼
        ┌─────────────────────────────────┐
        │   eitaa-cli 0.5.0 (pinned)      │  ← غیررسمی؛ reverse-engineered
        └─────────────────────────────────┘
                         │
                         ▼
        ┌─────────────────────────────────┐
        │  Eitaa Adapter Layer            │  app/eitaa/ — تنها نقطه تماس با ایتا
        │  (EitaaClientAdapter protocol)  │  قابل تعویض اگر eitaa-cli عوض شود
        └─────────────────────────────────┘
                 │                    │
         Message Sync            Media (lazy download)
   (polling + advisory lock)   (file_reference refresh)
                 │                    │
                 └─────────┬──────────┘
                           ▼
                      PostgreSQL
                           │
              ┌────────────┼─────────────┐
              ▼            ▼             ▼
        Conversations    Users/RBAC   Audit/Events
              │
              ▼
           FastAPI  ──REST /api/v1──▶  React (Vite)
              └──────WebSocket────────────┘
                           ▼
                    Support Agents
```

**نکته کلیدی:** `eitaa-cli` جریان رویداد لحظه‌ای ندارد؛ بنابراین Sync Worker هر `EITAA_SYNC_INTERVAL` ثانیه `messages.getDialogs` را می‌خواند و برای دیالوگ‌های دارای پیام جدید، تاریخچه را می‌گیرد. به‌محض ذخیره در DB، رویداد از طریق WebSocket به همه پنل‌های مجاز push می‌شود (پنل real-time است؛ منبع داده polling است).

## پیش‌نیازها

| ابزار | نسخه | یادداشت |
|---|---|---|
| Python | 3.11+ | روی 3.12 تست شده |
| PostgreSQL | 14+ | روی 18 تست شده |
| Bun | 1.1+ | برای frontend (طبق الزام پروژه، به‌جای npm) |
| Git | هر | برای clone و نصب eitaa-cli از GitHub |

## راه‌اندازی Development

```bash
git clone https://github.com/AlirezaR32/eitaa-support-desk.git
cd eitaa-support-desk
```

### 1) دیتابیس

فقط PostgreSQL را بالا بیاورید (همان فایل compose):

```bash
docker compose up -d postgres
```

یا اگر PostgreSQL بومی دارید، یک دیتابیس بسازید:

```bash
createdb eitaa_desk
```

### 2) Backend

```bash
cd backend

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> **نکته نصب eitaa-cli:** این پکیج در PyPI نیست؛ `requirements.txt` آن را با commit pin شده از GitHub نصب می‌کند:
> `eitaa-cli @ git+https://github.com/EhsanAhmadzadeh/eitaa-cli.git@685a71e`
> اگر دسترسی به GitHub ندارید، مخزن را clone یا wheel آن را دانلود و محلی نصب کنید:
> `pip install ./eitaa-cli`

متغیرهای محیطی (حداقل dev):

```bash
export DATABASE_URL="postgresql+asyncpg://desk:desk@localhost:5432/eitaa_desk"
export UPLOADS_DIR="/tmp/eitaa-uploads"
```

مهاجرت + ساخت Owner اولیه:

```bash
alembic upgrade head
python -m app.db.seed --email owner@yourdomain.local --password 'AStrongPass!123' --name 'Owner'
```

اجرا:

```bash
uvicorn app.main:app --reload --port 8010
```

- API: http://localhost:8010/api/v1
- Swagger: http://localhost:8010/docs
- Health: http://localhost:8010/health و http://localhost:8010/ready

### 3) Frontend

```bash
cd ../frontend
bun install
bun run dev        # http://localhost:5173 — /api به localhost:8010 پروکسی می‌شود
```

### 4) ورود و اتصال ایتا

1. به `http://localhost:5173` بروید و با Owner وارد شوید.
2. از «اکانت‌های ایتا» → «افزودن اکانت ایتا» شماره اکانت پشتیبانی را وارد کنید.
3. کد OTP ایتا را در همان ویزارد وارد کنید (سرور ایتا روش ارسال را تعیین می‌کند: پیامک/تماس/اپ).
4. Sync خودکار شروع می‌شود و گفتگوها در Inbox ظاهر می‌شوند.
5. (اختیاری، فقط dev) داده نمونه برای تست UI بدون اکانت واقعی:
   `python -m scripts.seed_demo --email owner@yourdomain.local`

## راه‌اندازی با Docker Compose

کل استک با یک دستور:

```bash
cp .env.example .env          # مقادیر را پر کنید (خصوصاً EITAA_SESSION_ENCRYPTION_KEY)
docker compose --profile full up -d --build
```

سرویس‌ها:

| سرویس | آدرس | توضیح |
|---|---|---|
| frontend | http://localhost:8080 | nginx serve + reverse proxy به API (تک‌مبدأ) |
| backend | http://localhost:8000 | API + sync worker در یک پروسه |
| worker | — | پروفایل `worker`: نمونه جدا فقط برای sync (با `RUN_SYNC_WORKER=true`؛ روی API خاموشش کنید) |
| postgres | localhost:5432 | volume پایدار `pgdata` |
| redis | localhost:6379 | اختیاری (پروفایل `redis`) — rate limit مشترک |

> برای مقیاس افقی: `RUN_SYNC_WORKER=false` روی سرویس‌های API و یک/چند کانتینر `worker` — advisory lock تضمین می‌کند هر اکانت همزمان فقط یک‌بار sync شود.

## مهاجرت‌های دیتابیس

```bash
alembic upgrade head          # اعمال همه
alembic downgrade -1          # یک قدم عقب
alembic revision --autogenerate -m "..."   # مهاجرت جدید
alembic history               # تاریخچه
```

> در Docker، کانتینر backend هنگام بالا آمدن خودش `alembic upgrade head` را اجرا می‌کند.

## تست‌ها

Backend (نیازمند PostgreSQL در دسترس؛ در CI سرویس postgres بالا می‌آید):

```bash
cd backend
export DATABASE_URL="postgresql+asyncpg://desk:desk@localhost:5432/eitaa_desk_test"
python -m pytest tests -v
```

پوشش سناریوهای کلیدی: state machine خوانده/پاسخ (§۱۱/§۳۸)، race دو پشتیبان روی Claim (یکی ۲۰۰، دیگری ۴۰۹)، sync تکراری بدون duplicate، RBAC و جلوگیری از escalation، چرخش refresh + تشخیص reuse، فلوی OTP با بررسی رمزنگاری‌بودن نشست، اعتبارسنجی upload، یادداشت هرگز ارسال نمی‌شود، dedup اعلان‌ها، deep-link فقط با یوزرنیم واقعی.

Frontend:

```bash
cd frontend
bun run test          # vitest
bun run typecheck     # tsc
bun run build         # بیلد production
```

اسکریپت‌های کمکی dev:

```bash
bash backend/scripts/smoke_backend.sh   # smoke کل API (login/refresh/filters/...)
bash backend/scripts/e2e_browser.sh     # E2E با مرورگر headless (نیازمند agent-browser)
```

## API و مستندات

- Swagger UI: `GET /docs` — OpenAPI کامل همه endpointها
- همه مسیرها زیر `/api/v1`: auth, agents, eitaa/accounts, conversations (+read/claim/release/assign/skip/close/reopen/waiting-user/messages/notes), messages/{id}/retry, attachments/{id}/download, notifications, dashboard, audit-logs, capabilities, ws
- Healthcheckها: `GET /health` (liveness) و `GET /ready` (readiness شامل DB)

## Deploy در Production

راهنمای کامل با دو سناریو (Vercel+Render/Railway یا VPS با Docker+Nginx، HTTPS، دامنه، migration، health check و persistent storage) در **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**.

## محدودیت‌های واقعی Eitaa

صادقانه، بر پایه بررسی سورس `eitaa-cli 0.5.0` (بدون جعل هیچ قابلیتی):

1. **بدون رویداد لحظه‌ای:** ایتا stream ندارد → sync با polling انجام می‌شود (پیش‌فرض هر ۱۵ ثانیه؛ قابل تنظیم). پنل خودش real-time است (WebSocket از سرورِ شما).
2. **ورود فقط با OTP:** لاگین با رمز (SRP) در eitaa-cli پیاده‌سازی نشده. سرور، کانال ارسال کد را انتخاب می‌کند (پیامک/تماس/اپ).
3. **mark-read ایتا best-effort است:** متد `messages.readHistory` در schema لایه ۱۳۵ موجود است و از طریق invoke عمومی صدا زده می‌شود؛ اما منبع حقیقت وضعیت خوانده‌شده، دیتابیس خود شماست.
4. **لینک «باز کردن در ایتا» فقط با username واقعی** ساخته می‌شود (`https://eitaa.com/USERNAME`). برای کاربران بدون username، دکمه نمایش داده نمی‌شود (هرگز حدس زده نمی‌شود).
5. **رسانه ورودی lazy دانلود می‌شود:** فایل‌های پیام‌های کاربر هنگام sync فقط metadata دارند؛ با اولین درخواست دیدن، از ایتا دانلود و cache می‌شود (file_reference منقضی‌شده خودکار refresh می‌شود).
6. **کلاینت غیررسمی:** هر تغییر سرور ایتا می‌تواند sync را بشکند؛ همه خطاها در `eitaa_accounts.last_error` و لاگ audit دیده می‌شوند و اکانت در صورت باطل‌شدن نشست خودکار «قطع» می‌شود.
7. **ارسال از خود ایتا هم پاسخ حساب می‌شود:** اگر پشتیبان از اپ ایتا جواب بدهد، پیام outbound ثبت و گفتگو «پاسخ‌داده» می‌شود.

## متغیرهای محیطی

نمونه کامل با توضیح: [`.env.example`](.env.example)

| کلید | پیش‌فرض | توضیح |
|---|---|---|
| `DATABASE_URL` | — | اجباری؛ `postgresql+asyncpg://...` |
| `SECRET_KEY` / `JWT_SECRET` | — | در production اجباری (≥۳۲ کاراکتر) |
| `EITAA_SESSION_ENCRYPTION_KEY` | derived | کلید Fernet نشست‌های ایتا — در production حتماً مستقل |
| `EITAA_SYNC_INTERVAL` | 15 | فاصله polling (ثانیه) |
| `CORS_ORIGINS` | localhost:5173 | مبدأهای مجاز فرانت‌اند |
| `MAX_UPLOAD_SIZE_MB` | 25 | سقف حجم پیوست |
| `RUN_SYNC_WORKER` | true | در معماری multi-instance خاموش/روشن کنید |
| `UPLOADS_DIR` | /data/uploads | مسیر ذخیره فایل‌ها (volume) |

## عیب‌یابی

| نشانه | علت احتمالی / راه‌حل |
|---|---|
| `/ready` عدد 503 می‌دهد | DATABASE_URL اشتباه یا PostgreSQL پایا نیست |
| پیام «Session expired» روی اکانت | نشست ایتا باطل شده → از پنل دوباره OTP بزنید (اکانت خودکار «قطع» می‌شود) |
| پیام‌ها دیر می‌آیند | `EITAA_SYNC_INTERVAL` را کم کنید؛ محدودیت flood ایتا را در نظر بگیرید |
| خطای «FLOOD_WAIT» | ایتا محدودیت کرده؛ interval را زیاد کنید (متن خطا در `last_error` اکانت) |
| ارسال پیام ناموفق | وضعیت در خود حباب پیام + `MESSAGE_FAILED` در لاگ فعالیت؛ دکمه «تلاش مجدد» |
| خطای pip هنگام نصب eitaa-cli | دسترسی GitHub؛ مخزن را clone و `pip install ./eitaa-cli` بزنید |
| Refresh دائم 401 در حالت cross-origin | فرانت و API را روی یک مبدأ (reverse proxy) سرو کنید — مثل nginx کانتینر frontend |

## ساختار پروژه

```text
eitaa-support-desk/
├── backend/
│   ├── app/
│   │   ├── core/          # config, security, RBAC registry, logging, ratelimit
│   │   ├── db/            # base, session, seed
│   │   ├── models/        # SQLAlchemy 2 models (16 tables)
│   │   ├── schemas/       # Pydantic v2
│   │   ├── eitaa/         # ★ Adapter layer (protocol + eitaa-cli impl + registry)
│   │   ├── services/      # business logic (state machine, claim, send pipeline…)
│   │   ├── api/v1/        # routers + WebSocket + deps
│   │   └── workers/       # sync worker + scheduler
│   ├── alembic/           # migrations
│   ├── tests/             # unit + integration (49 tests)
│   ├── scripts/           # smoke / e2e / seed_demo
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── api/           # TanStack Query hooks
│   │   ├── lib/           # api client (single-flight refresh), fa format
│   │   ├── stores/        # auth, theme, toast
│   │   ├── hooks/         # useRealtime (WebSocket)
│   │   ├── components/    # inbox / conversation / ui / layout
│   │   └── pages/         # 9 pages
│   ├── Dockerfile         # bun build + nginx
│   └── package.json
├── docker-compose.yml
├── .env.example
├── .github/workflows/ci.yml
└── docs/                  # ARCHITECTURE.md, DEPLOYMENT.md
```

## لایسنس

MIT
