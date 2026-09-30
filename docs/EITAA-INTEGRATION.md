# یکپارچه‌سازی با Eitaa — ماتریس قابلیت‌های واقعی

این سند حاصل بررسی مستقیم سورس [`eitaa-cli 0.5.0`](https://github.com/EhsanAhmadzadeh/eitaa-cli) (commit `685a71e`) است و مبنای پیاده‌سازی adapter این پروژه است. طبق اصل §۳۷ مشخصات، هیچ قابلیتی جعل نشده و هیچ endpoint ساختگی ساخته نشده است.

## قابلیت‌هایی که واقعاً وجود دارند (و استفاده می‌شوند)

| قابلیت | در eitaa-cli | نحوه استفاده در این پروژه |
|---|---|---|
| درخواست کد OTP | `auth.request_code()` | ویزارد اتصال اکانت — `POST /api/v1/eitaa/accounts/request-code` |
| ورود با کد | `auth.sign_in(..., save=False)` | همان ویزارد — نشست به‌جای فایل، رمزنگاری‌شده در DB |
| ارسال مجدد کد | `auth.resend_code(phone, hash)` | دکمه «ارسال مجدد کد» (با timeout سرور) |
| ساخت client از نشست حافظه‌ای | `EitaaClient(settings, _loaded_profile=SessionProfile(...))` | Registry — بدون فایل session روی دیسک |
| لیست دیالوگ‌ها | `dialogs.list(limit)` → `{dialogs, messages, users, chats}` | Sync Worker — تشخیص گفتگوهای جدید با `top_message_id` |
| تاریخچه پیام | `messages.history(peer, limit, min_id)` | Sync Worker — پیام‌های جدید هر گفتگو |
| ارسال متن | `messages.send_text(peer, text, reply_to=)` | `POST /conversations/{id}/messages` |
| ارسال رسانه | `media.send_file(path, caption=, voice=, duration=)` | همان endpoint با multipart |
| دانلود رسانه | `media.download_message(peer, message_id, dest)` | دانلود lazy با اولین درخواست نمایش |
| Reply | `reply_to` در send | ذخیره `reply_to_message_id` + نمایش quote |
| resolve همتا | `peers.resolve("user:ID:HASH" / "chat:ID" / ...)` | ارجاع پایدار گفتگو |
| متد عمومی TL | `client.invoke("messages.readHistory", {...})` | best-effort برای هم‌زمان‌سازی read با ایتا (متد در schema لایه ۱۳۵ موجود است، خطاها gracefully نادیده گرفته می‌شوند) |
| اطلاعات اکانت | `users.getFullUser(inputUserSelf)` | تأیید نشست + پروفایل اکانت |
| خروج | `auth.logOut` | قطع اکانت از پنل |

## محدودیت‌های واقعی و رفتار سیستم

| محدودیت ایتا | رفتار این پروژه |
|---|---|
| **جریان رویداد لحظه‌ای ندارد** («Real-time update streaming is not yet wrapped as a persistent event loop») | Sync Worker با polling (پیش‌فرض ۱۵s). پنل real-time است چون سرورِ خودِ ما با WebSocket به مرورگر push می‌کند. در `/api/v1/capabilities` مقدار `real_time: false` صادقانه اعلام شده است. |
| ورود با رمز (SRP) پیاده‌سازی نشده | فقط OTP؛ در UI هم گزینه‌ای برای رمز نیست |
| سرور کانال OTP را انتخاب می‌کند (SMS/call/flash/app) | ویزارد نوع ارسال را از پاسخ سرور نمایش می‌دهد؛ countdown طبق `timeout_seconds` خود سرور |
| `phone_code_hash` حساس و موقت | رمزنگاری‌شده در `auth_challenges` با TTL؛ هرگز در API response/log نیست |
| نشست = token+imei+user و ارزشمند | Fernet-encrypted در DB؛ کلید از env؛ لاگ ماسک می‌شود |
| file_reference رسانه منقضی می‌شود | دانلود lazy + رفرش خودکار پیام برای گرفتن file_reference جدید (`get_by_id`) |
| بدون username لینک عمومی وجود ندارد | دکمه «باز کردن در ایتا» فقط با username واقعی؛ در غیر این صورت hidden |
| کلاینت غیررسمی؛ endpoints ممکن است تغییر کنند | خطاها typed (`EitaaRPCError`…) → `last_error` اکانت + audit؛ نشست باطل → وضعیت «قطع» + رویداد WebSocket |
| محدودیت flood (`FLOOD_WAIT_x`) | پیام خطا با مدت دقیق سرور به پشتیبان نشان داده می‌شود؛ interval قابل تنظیم |
| آلبوم حداکثر ۱۰ فایل | ارسال تک‌فایل در پنل (ارسال آلبوم در UI نیست — ساده و صادقانه) |
| رمزگذاری/امضای رسمی API وجود ندارد | همان web profile کتابخانه استفاده می‌شود؛ هیچ ادعایی درباره stealth نیست |

## تفاوت عمدی با مشخصات اولیه

1. **«ارسال Voice»** — پشتیبانی می‌شود (ضبط در مرورگر با MediaRecorder → upload → `send_file(voice=True, duration=…)`). محدودیت واقعی: نوع کدک خروجی مرورگر webm/opus است؛ eitaa-cli آن را به‌عنوان سند صوتی می‌فرستد.
2. **«همگام‌سازی read به ایتا»** — best-effort است (بند بالا)؛ منبع حقیقت وضعیت خوانده‌شده DB خودمان است تا فیلترها دقیق بمانند.
3. **«Multiple accounts با Agentهای خاص»** — پیاده‌سازی کامل (`agent_eitaa_accounts`)؛ پشتیبان فقط گفتگوهای اکانت‌های متصل به خودش را می‌بیند.

## چرا pin به commit؟

`requirements.txt`:

```
eitaa-cli @ git+https://github.com/EhsanAhmadzadeh/eitaa-cli.git@685a71e12d78cf58cb18074e08aad4c8e06981a0
```

کتابخانه غیررسمی است؛ pin تضمین می‌کند build شما با کدی که adapter رویش نوشته و تست شده، همخوان بماند. هنگام ارتقا: مخزن را مرور کنید، adapter را در `backend/app/eitaa/adapter.py` (و فقط همان‌جا) به‌روز کنید و `pytest tests -k eitaa` را اجرا کنید.
