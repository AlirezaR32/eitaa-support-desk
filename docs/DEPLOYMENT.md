# راهنمای Deployment در Production

دو سناریوی پشتیبانی‌شده. در هر دو، **HTTPS اجباری** است (refresh cookie و WebSocket).

---

## پیش‌نیازهای مشترک

1. یک PostgreSQL (مدیریت‌شده یا خودتان).
2. سه secret تولیدشده:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"                        # SECRET_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(48))"                        # JWT_SECRET
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # EITAA_SESSION_ENCRYPTION_KEY
```

3. دامنه‌ها: مثلاً `desk.example.com` (فرانت) و `api.example.com` (بک‌اند) — یا یک دامنه با path (سناریوی B).
4. هشدار: بدون `EITAA_SESSION_ENCRYPTION_KEY` مستقل، سرور در حالت production بالا نمی‌آید (بررسی startup).

---

## Option A — Frontend روی Vercel/Netlify/Cloudflare، Backend روی Render/Railway/Fly.io

### Frontend (مثال Vercel)

- **Repo/Root Directory:** `frontend`
- **Build Command:** `bun install && bun run build`
- **Output:** `dist`
- **Environment (production):**

```env
VITE_API_BASE_URL=https://api.example.com
```

(خالی بگذارید اگر API روی همان دامنه زیر path سرو می‌شود.)

Vercel `vercel.json` برای SPA routing:

```json
{ "rewrites": [{ "source": "/(.*)", "destination": "/index.html" }] }
```

### Backend (مثال Render)

- **Environment:** Python 3
- **Root Directory:** `backend`
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT"`
- **Health Check Path:** `/health` (Render) — `READY /ready` هم status دقیق‌تری می‌دهد
- **Environment Variables:**

```env
APP_ENV=production
DATABASE_URL=postgresql+asyncpg://<user>:<pass>@<host>:5432/<db>
SECRET_KEY=<generated>
JWT_SECRET=<generated>
EITAA_SESSION_ENCRYPTION_KEY=<fernet-key>
CORS_ORIGINS=https://desk.example.com
EITAA_SYNC_INTERVAL=15
RUN_SYNC_WORKER=true
UPLOADS_DIR=/data/uploads
LOG_LEVEL=INFO
LOG_JSON=true
```

- **Persistent Disk:** به `/data` (محدودیت: روی Render/Railley disk باید به plan متصل شود؛ آپلودها اینجا می‌مانند).
- **نکته Railway/Fly:** متغیر `PORT` تزریق می‌شود؛ در Start Command از `$PORT` استفاده کنید. Fly.io در `fly.toml`:

```toml
[http_service]
  internal_port = 8000
  [[http_service.checks]]
    path = "/health"
```

### Database

Managed PostgreSQL (Neon / Supabase / Render Postgres / RDS). connection string را در `DATABASE_URL` بگذارید (پیشوند `postgresql+asyncpg://`). برای SSL اضافه‌شده: `?ssl=require`.

### نکات مهم این سناریو

- **CORS:** `CORS_ORIGINS=https://desk.example.com` (بدون slash انتهایی).
- **Migration:** با Start Command بالا هر deploy خودکار `alembic upgrade head` می‌زند. برای rollback دستی: کنسول Render/Railway → `alembic downgrade -1`.
- **WebSocket:** روی Render/Railway از نظر پشتیبانی می‌شود؛ مطمئن شوید proxy timeout بالاست (پنل هر ۲۵ ثانیه ping می‌زند).
- **تک‌نود با worker داخلی:** پیش‌فرض `RUN_SYNC_WORKER=true` ساده‌ترین حالت است. اگر plan شما چند instance می‌سازد، روی web سرویس `RUN_SYNC_WORKER=false` بگذارید و یک سرویس worker جدا (همان image، فقط worker) بسازید.

---

## Option B — همه‌چیز با Docker روی VPS (Nginx + تک‌دامنه)

```text
اینترنت ──▶ Nginx (80/443, Let's Encrypt)
             ├── /            → frontend (nginx container)
             └── /api, /docs  → backend:8000
                                ├── PostgreSQL (یا managed)
                                └── worker (اختیاری، همان image)
```

### ۱) آماده‌سازی

```bash
git clone https://github.com/<you>/eitaa-support-desk.git
cd eitaa-support-desk
cp .env.example .env     # مقادیر production را پر کنید
```

`.env` نمونه production:

```env
APP_ENV=production
DATABASE_URL=postgresql+asyncpg://desk:STRONGPASS@postgres:5432/eitaa_desk
SECRET_KEY=...
JWT_SECRET=...
EITAA_SESSION_ENCRYPTION_KEY=...
CORS_ORIGINS=https://desk.example.com
EITAA_SYNC_INTERVAL=15
RUN_SYNC_WORKER=true
UPLOADS_DIR=/data/uploads
LOG_JSON=true
```

### ۲) docker-compose producción

`docker-compose.prod.yml`:

```yaml
services:
  postgres:
    image: postgres:18-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: desk
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: eitaa_desk
    volumes: [pgdata:/var/lib/postgresql/data]

  backend:
    build: ./backend
    restart: unless-stopped
    env_file: .env
    environment:
      RUN_SYNC_WORKER: "true"     # تک‌نود؛ برای تفکیک، false + سرویس worker
    volumes: [uploads:/data/uploads]
    depends_on: [postgres]
    expose: ["8000"]

  frontend:
    build: ./frontend
    restart: unless-stopped
    depends_on: [backend]
    expose: ["80"]

  nginx:
    image: nginx:1.29-alpine
    restart: unless-stopped
    ports: ["80:80", "443:443"]
    volumes:
      - ./nginx.prod.conf:/etc/nginx/conf.d/default.conf:ro
      - /etc/letsencrypt:/etc/letsencrypt:ro
    depends_on: [frontend, backend]

volumes:
  pgdata:
  uploads:
```

`nginx.prod.conf`:

```nginx
server {
    listen 80;
    server_name desk.example.com;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://$host$request_uri; }
}

server {
    listen 443 ssl http2;
    server_name desk.example.com;

    ssl_certificate     /etc/letsencrypt/live/desk.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/desk.example.com/privkey.pem;

    client_max_body_size 30m;

    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;

    location /api/ {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;      # WebSocket
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
    }

    location ~ ^/(docs|redoc|openapi.json|health|ready)$ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
    }

    location / {
        proxy_pass http://frontend:80;
        proxy_set_header Host $host;
    }
}
```

### ۳) اجرا

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head   # (خودکار هم هست)
docker compose -f docker-compose.prod.yml exec backend \
  python -m app.db.seed --email owner@example.com --password 'StrongPass!123'
```

### ۴) گواهی Let's Encrypt

```bash
sudo apt install certbot
sudo certbot certonly --webroot -w /var/www/certbot -d desk.example.com
# تمدید خودکار: cron روزانه certbot renew + docker compose restart nginx
```

### ۵) Health و مشاهده وضعیت

```bash
curl -sf https://desk.example.com/health         # {"status":"ok"}
curl -sf https://desk.example.com/ready          # DB + worker status
docker compose -f docker-compose.prod.yml logs -f backend
```

---

## Checklist نهایی production

- [ ] `APP_ENV=production` (سرور بدون secretهای قوی بالا نمی‌آید)
- [ ] `EITAA_SESSION_ENCRYPTION_KEY` مستقل و backup شده
- [ ] HTTPS فعال (HSTS خودکار در production)
- [ ] `CORS_ORIGINS` فقط مبدأ فرانت‌اند
- [ ] backup روزانه PostgreSQL (`pg_dump` یا snapshot managed)
- [ ] volume آپلودها در backup
- [ ] `/health` به LB/uptime متصل شده
- [ ] Owner اولیه ساخته و گذرواژه قوی دارد
- [ ] اکانت ایتا از پنل متصل شده و sync سالم است (`/ready` و صفحه اکانت‌ها)
- [ ] (اختیاری) `REDIS_URL` برای چند instance

## Backup / Restore

```bash
# backup
docker compose -f docker-compose.prod.yml exec postgres \
  pg_dump -U desk eitaa_desk | gzip > backup-$(date +%F).sql.gz

# restore
gunzip -c backup-2026-09-30.sql.gz | \
  docker compose -f docker-compose.prod.yml exec -T postgres psql -U desk eitaa_desk
```

> نشست‌های ایتا داخل DB رمزنگاری‌شده‌اند؛ restore با همان `EITAA_SESSION_ENCRYPTION_KEY` کار می‌کند — این کلید را هم backup بگیرید.
