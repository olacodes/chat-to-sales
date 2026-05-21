# ChatToSales — Deployment Guide

## Infrastructure

| Component | Service | Cost |
|-----------|---------|------|
| Backend API | Hetzner VPS (CX23: 2 vCPU, 4GB RAM, 40GB) | €4.99/month |
| Frontend | Vercel (free tier) | Free |
| Database | PostgreSQL 16 (Docker on VPS) | Included |
| Cache | Redis 7 (Docker on VPS) | Included |
| Image Storage | Cloudflare R2 | Pay per use |
| Domain | Namecheap (chattosales.com) | ~$10/year |

## Architecture

```
                    ┌──────────────┐
 WhatsApp Users ──> │  Meta Cloud  │
                    │  (webhooks)  │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
 Dashboard Users -> │   Vercel     │ (www.chattosales.com)
                    │   Next.js    │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │   Hetzner    │ (api.chattosales.com)
                    │   Nginx      │ :443 (SSL)
                    │      │       │
                    │   FastAPI    │ :8000
                    │      │       │
                    │  PostgreSQL  │ :5432
                    │  Redis       │ :6379
                    └──────────────┘
```

## DNS Records (Namecheap)

| Type | Host | Value |
|------|------|-------|
| A | api | 178.104.205.4 (your Hetzner IP) |
| CNAME | www | cname.vercel-dns.com |
| CNAME | @ | cname.vercel-dns.com |

## Files on the Server

```
/opt/chattosales/
├── .env.prod                          # Production environment variables
├── docker-compose.prod.yml            # Production Docker Compose
├── Dockerfile                         # Multi-stage build (builder → runtime)
├── nginx/
│   ├── nginx.conf                     # Main Nginx config
│   └── conf.d/
│       ├── app.conf                   # Active site config (HTTP or SSL)
│       └── app-ssl.conf.example       # SSL template
├── alembic/                           # Database migrations
├── app/                               # Application code
└── tests/                             # Test suite
```

## Environment Variables (.env.prod)

```bash
# ── Application
ENVIRONMENT=production
DEBUG=false
APP_BASE_URL=https://api.chattosales.com
FRONTEND_URL=https://www.chattosales.com

# ── Security
SECRET_KEY=<random-64-char-string>
ENCRYPTION_KEY=<fernet-key>
ALLOWED_HOSTS=["https://www.chattosales.com","https://chattosales.com"]

# ── Database
DATABASE_URL=postgresql+asyncpg://postgres:<password>@postgres:5432/chattosales
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<strong-password>

# ── Redis
REDIS_URL=redis://:<password>@redis:6379/0
REDIS_PASSWORD=<strong-password>

# ── WhatsApp / Meta
WHATSAPP_VERIFY_TOKEN=<your-verify-token>
WHATSAPP_APP_SECRET=<your-app-secret>
WHATSAPP_PHONE_NUMBER_ID=1119151557949296
WHATSAPP_ACCESS_TOKEN=<permanent-system-user-token>
PLATFORM_WHATSAPP_NUMBER=2348141605756
TENANT_ID=<your-platform-tenant-id>

# ── AI APIs
ANTHROPIC_API_KEY=<your-key>
OPENAI_API_KEY=<your-key>
GOOGLE_VISION_API_KEY=<your-key>

# ── Paystack
PAYSTACK_SECRET_KEY=<your-key>

# ── Cloudflare R2
R2_ACCOUNT_ID=<your-id>
R2_ACCESS_KEY_ID=<your-key>
R2_SECRET_ACCESS_KEY=<your-secret>
R2_BUCKET_NAME=chattosales-images
R2_PUBLIC_URL=https://images.chattosales.com

# ── Admin
ADMIN_PHONE=2348166041471
ADMIN_EMAIL=admin@chattosales.com
ADMIN_PASSWORD=<strong-password>

# ── Smart follow-up
FOLLOWUP_DELAY_HOURS=24
```

## First-Time Server Setup

### 1. Provision Hetzner VPS

- Create a CX23 server (2 vCPU, 4GB RAM, 40GB disk)
- Ubuntu 22.04 or 24.04
- Add your SSH key
- Enable backups in Hetzner Console (~€1.20/month extra)

### 2. Install Docker

```bash
ssh root@YOUR_SERVER_IP

# Create deploy user
adduser deploy
usermod -aG docker deploy

# Install Docker
curl -fsSL https://get.docker.com | sh
systemctl enable docker

# Switch to deploy user
su - deploy
```

### 3. Clone the repo

```bash
cd /opt
git clone https://github.com/olacodes/chat-to-sales.git chattosales
cd chattosales
```

### 4. Create .env.prod

```bash
cp .env.example .env.prod  # if example exists
nano .env.prod              # fill in all values from the template above
```

### 5. Build and start

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

This will:
- Build the FastAPI app Docker image
- Start PostgreSQL, Redis, Nginx, and the app
- Run Alembic migrations automatically (migrate service)

### 6. Get SSL certificate

```bash
# Make sure DNS is pointing to your server first (api.chattosales.com → YOUR_IP)
# Wait 5-10 minutes for propagation, then:

docker run --rm \
  -v chattosales_certbot_webroot:/var/www/certbot \
  -v chattosales_certbot_certs:/etc/letsencrypt \
  certbot/certbot certonly \
  --webroot -w /var/www/certbot \
  -d api.chattosales.com \
  --agree-tos --email your@email.com
```

### 7. Activate SSL

```bash
cp nginx/conf.d/app-ssl.conf.example nginx/conf.d/app.conf
docker compose -f docker-compose.prod.yml restart nginx
```

### 8. Verify

```bash
curl https://api.chattosales.com/health
# Should return: {"status":"ok","checks":{"database":"ok","redis":"ok"}}
```

## Meta WhatsApp Setup

### 1. Create System User token (permanent)

1. Go to business.facebook.com → Settings → System Users
2. Create a system user with Admin access
3. Add Assets:
   - Your WhatsApp Business Account → Full Control
   - Your App → Full Control
4. Generate Token with permissions:
   - `whatsapp_business_messaging`
   - `whatsapp_business_management`
5. Set expiry to Never
6. Save this token as `WHATSAPP_ACCESS_TOKEN` in `.env.prod`

### 2. Configure webhook

1. Go to Meta Developer Console → Your App → WhatsApp → Configuration
2. Callback URL: `https://api.chattosales.com/api/v1/webhooks/whatsapp`
3. Verify token: same as `WHATSAPP_VERIFY_TOKEN` in `.env.prod`
4. Click "Verify and save"
5. Under Webhook fields, subscribe to **messages**

### 3. Subscribe WABA to app

This step tells Meta to forward inbound messages to your webhook. Without it, you can send but not receive.

```bash
curl -X POST "https://graph.facebook.com/v25.0/YOUR_WABA_ID/subscribed_apps" \
  -H "Authorization: Bearer YOUR_PERMANENT_TOKEN"
```

Replace `YOUR_WABA_ID` with your WhatsApp Business Account ID (find it on the API Setup page).

You should get `{"success":true}`.

### 4. Verify end-to-end

Send a WhatsApp message to your business number. Check logs:

```bash
docker compose -f docker-compose.prod.yml logs app --tail=20 -f
```

You should see the message received, processed, and a reply sent.

## Routine Operations

### Deploy new code

```bash
cd /opt/chattosales
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

Migrations run automatically on every deploy (the migrate service).

### View logs

```bash
# App logs
docker compose -f docker-compose.prod.yml logs app --tail=50

# Follow logs in real-time
docker compose -f docker-compose.prod.yml logs app -f

# Nginx logs
docker compose -f docker-compose.prod.yml logs nginx --tail=20

# All services
docker compose -f docker-compose.prod.yml logs --tail=20
```

### Restart a service

```bash
# Restart just the app (after .env change)
docker compose -f docker-compose.prod.yml restart app

# Restart everything
docker compose -f docker-compose.prod.yml restart
```

### Database backup (manual)

```bash
docker compose -f docker-compose.prod.yml --profile backup run --rm db-backup
```

Backups are stored in the `db_backups` Docker volume. Automated backup runs daily at 3am via cron.

### Restore from backup

```bash
# List backups
docker run --rm -v chattosales_db_backups:/backups alpine ls -lt /backups/

# Restore a specific backup
docker compose -f docker-compose.prod.yml exec -T postgres \
  psql -U postgres chattosales < <(docker run --rm -v chattosales_db_backups:/backups alpine \
  zcat /backups/chattosales_20260521_030000.sql.gz)
```

### Renew SSL certificate

Certificates expire every 90 days. Renew with:

```bash
docker run --rm \
  -v chattosales_certbot_webroot:/var/www/certbot \
  -v chattosales_certbot_certs:/etc/letsencrypt \
  certbot/certbot renew

docker compose -f docker-compose.prod.yml restart nginx
```

Set up auto-renewal with cron:

```bash
crontab -e
# Add this line:
0 4 1 * * docker run --rm -v chattosales_certbot_webroot:/var/www/certbot -v chattosales_certbot_certs:/etc/letsencrypt certbot/certbot renew && cd /opt/chattosales && docker compose -f docker-compose.prod.yml restart nginx
```

### Check disk space

```bash
df -h
# If disk is full:
docker system prune -a -f
```

### Check health

```bash
curl https://api.chattosales.com/health
```

Returns:
```json
{
  "status": "ok",
  "app": "ChatToSales",
  "version": "0.1.0",
  "environment": "production",
  "checks": {
    "database": "ok",
    "redis": "ok"
  }
}
```

If status is "degraded", check which service is down and restart it.

## Cron Jobs

| Schedule | Job | What it does |
|----------|-----|-------------|
| 3:00 AM daily | DB backup | Dumps PostgreSQL, keeps last 7 backups |
| 1st of month 4:00 AM | SSL renewal | Renews Let's Encrypt certificate |

View cron jobs:
```bash
crontab -l
```

## Docker Services

| Service | Container | Port | Purpose |
|---------|-----------|------|---------|
| nginx | chattosales_nginx | 80, 443 | Reverse proxy + SSL |
| app | chattosales_app | 8000 (internal) | FastAPI application |
| postgres | chattosales_postgres | 5432 (internal) | Database |
| redis | chattosales_redis | 6379 (internal) | Cache + event bus |
| migrate | chattosales_migrate | — | Runs migrations on deploy |
| db-backup | chattosales_db_backup | — | On-demand backup (via --profile) |

Only Nginx is exposed to the internet. All other services communicate on the internal Docker network.

## Troubleshooting

### Messages not received from WhatsApp

1. Check Meta webhook is subscribed: Meta Console → WhatsApp → Configuration → messages field must be "Subscribed"
2. Check WABA subscription: `curl -X POST "https://graph.facebook.com/v25.0/WABA_ID/subscribed_apps" -H "Authorization: Bearer TOKEN"` — must return `{"success":true}`
3. Check nginx logs for incoming requests: `docker compose -f docker-compose.prod.yml logs nginx --tail=20`
4. Check app logs for errors: `docker compose -f docker-compose.prod.yml logs app --tail=20`

### Messages received but replies fail (401 Unauthorized)

The WhatsApp access token stored in the database (tenant channel) is expired or wrong.

1. Generate a new permanent token from Meta Business → System Users
2. Update `.env.prod` with the new token
3. Reconnect the channel: restart the app or call the channel connect endpoint

### App won't start

```bash
docker compose -f docker-compose.prod.yml logs app --tail=50
```

Common causes:
- Missing environment variable (check .env.prod)
- Database migration failed (check migrate logs)
- Port conflict

### Disk full

```bash
df -h
docker system prune -a -f
```

### Can't reach api.chattosales.com

1. Check DNS: `dig api.chattosales.com` — should return your Hetzner IP
2. Check Nginx is running: `docker compose -f docker-compose.prod.yml ps`
3. Check firewall: ports 80 and 443 must be open
4. Check SSL cert: `curl -vI https://api.chattosales.com 2>&1 | grep "SSL certificate"`
