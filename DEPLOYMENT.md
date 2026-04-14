# ChatToSales — Hetzner Deployment Guide

**Server:** CX23 · IP `204.168.201.192` · Ubuntu 22.04

---

## Architecture

```
Internet
   │  80 / 443
   ▼
Nginx (container)
   │  http://app:8000
   ▼
FastAPI app (container)
   ├── PostgreSQL (container, internal only)
   └── Redis (container, internal only, password-protected)
```

---

## Part 1 — One-time manual steps on your local machine

### Step 1 — Add your SSH public key to the server

When you created the server in Hetzner Cloud Console you should have been given the option to inject an SSH key. If you did not, do it now:

```bash
# On your local machine
ssh-copy-id root@204.168.201.192
# Verify login works
ssh root@204.168.201.192
```

### Step 2 — Push code to GitHub

The deploy script pulls from Git. Make sure all these new files are committed and pushed to `main`:

```bash
# On your local machine, from the project root
git add docker-compose.prod.yml nginx/ deploy/ .env.prod.example .gitignore
git commit -m "chore: add production deployment config"
git push origin main
```

---

## Part 2 — One-time server bootstrap (run once as root)

SSH into the server, then run the bootstrap script:

```bash
ssh root@204.168.201.192
```

```bash
# On the server as root

# Option A — copy & run the setup script you already have in the repo
# (after Step 2 above the script is on GitHub)
curl -fsSL https://raw.githubusercontent.com/olacodes/chat-to-sales/main/deploy/setup.sh | bash

# Option B — if the repo is private, SCP the file first
# scp deploy/setup.sh root@204.168.201.192:/root/
# ssh root@204.168.201.192 bash /root/setup.sh
```

The script will:

- Update the OS and install security tools
- Install Docker + Docker Compose plugin
- Create an unprivileged `deploy` user (copies your SSH key to it)
- Configure UFW firewall (allow 22, 80, 443; deny everything else)
- Enable fail2ban
- Create a 2 GB swapfile
- Create `/opt/chattosales`

---

## Part 3 — First deployment (run once as deploy user)

### Step 3 — Switch to the deploy user

```bash
# Still on the server
su - deploy
# Verify you can run docker without sudo
docker ps
```

### Step 4 — Clone the repository

```bash
cd /opt/chattosales

# Public repo
git clone https://github.com/olacodes/chat-to-sales.git .

# Private repo — generate a deploy key (see note below)
# git clone git@github.com:olacodes/chat-to-sales.git .
```

> **Private repo?** Generate a deploy key on the server:
>
> ```bash
> ssh-keygen -t ed25519 -C "deploy@204.168.201.192" -f ~/.ssh/deploy_key -N ""
> cat ~/.ssh/deploy_key.pub   # add this as a Deploy Key in GitHub repo Settings → Deploy keys
> eval "$(ssh-agent -s)" && ssh-add ~/.ssh/deploy_key
> ```

### Step 5 — Create the production environment file

```bash
cp .env.prod.example .env.prod
nano .env.prod          # or: vim .env.prod
```

Fill in **every** `CHANGE_ME` value:

| Variable                   | How to generate / where to find                               |
| -------------------------- | ------------------------------------------------------------- |
| `SECRET_KEY`               | `python3 -c "import secrets; print(secrets.token_hex(48))"`   |
| `POSTGRES_PASSWORD`        | Choose a strong random password                               |
| `REDIS_PASSWORD`           | Choose a strong random password                               |
| `DATABASE_URL`             | Same user/password as above, keep host `postgres`             |
| `REDIS_URL`                | Same password as `REDIS_PASSWORD`, keep host `redis`          |
| `WHATSAPP_VERIFY_TOKEN`    | Your webhook verify token (any string you choose)             |
| `WHATSAPP_APP_SECRET`      | Meta Developer Console → App → WhatsApp → App Secret          |
| `WHATSAPP_PHONE_NUMBER_ID` | Meta Developer Console → WhatsApp → Phone number ID           |
| `WHATSAPP_ACCESS_TOKEN`    | Meta Developer Console → WhatsApp → Temporary/Permanent token |
| `PAYSTACK_SECRET_KEY`      | Paystack Dashboard → Settings → API Keys                      |

**Double-check no `CHANGE_ME` remains:**

```bash
grep CHANGE_ME .env.prod   # should print nothing
```

### Step 6 — Run your first deployment

```bash
bash deploy/deploy.sh
```

This will:

1. Build the Docker image
2. Run `alembic upgrade head` (applies all migrations)
3. Start nginx, app, postgres, redis

**Verify everything is up:**

```bash
docker compose -f docker-compose.prod.yml ps
curl http://204.168.201.192/health
```

Expected response: `{"status":"ok", ...}`

---

## Part 4 — Optional but strongly recommended

### Step 7 — Enable HTTPS with Let's Encrypt

**Domain:** `chattosales.duckdns.org`

1. **Point DuckDNS to the server IP** — log in to [https://www.duckdns.org](https://www.duckdns.org), find the `chattosales` subdomain and set its IP to `204.168.201.192`. Save. DNS is instant with DuckDNS.

2. **Verify the domain resolves** (from your local machine):

   ```bash
   nslookup chattosales.duckdns.org
   # Should return 204.168.201.192
   ```

3. **Run Certbot** (from the server as `deploy` user, after the app is running on port 80):

   ```bash
   cd /opt/chattosales

   docker run --rm \
     -v chattosales_certbot_webroot:/var/www/certbot \
     -v chattosales_certbot_certs:/etc/letsencrypt \
     certbot/certbot certonly \
       --webroot \
       --webroot-path /var/www/certbot \
       -d chattosales.duckdns.org \
       --email your@email.com \
       --agree-tos \
       --non-interactive
   ```

   > Note: DuckDNS subdomains do **not** have a `www.` equivalent — only a single `-d` flag is needed.

4. **Switch Nginx to the HTTPS config** (the domain is already filled in):

   ```bash
   cp nginx/conf.d/app-ssl.conf.example nginx/conf.d/app.conf
   docker compose -f docker-compose.prod.yml restart nginx
   ```

5. **Verify HTTPS is working:**

   ```bash
   curl https://chattosales.duckdns.org/health
   ```

6. **Set up automatic cert renewal** (cron as deploy user):
   ```bash
   crontab -e
   # Add this line:
   0 3 * * * docker run --rm \
     -v chattosales_certbot_webroot:/var/www/certbot \
     -v chattosales_certbot_certs:/etc/letsencrypt \
     certbot/certbot renew --quiet \
     && docker compose -f /opt/chattosales/docker-compose.prod.yml restart nginx
   ```

### Step 8 — ALLOWED_HOSTS

`ALLOWED_HOSTS` is already set to `["https://chattosales.duckdns.org"]` in `.env.prod.example`. No further action needed once you copy the file.

### Step 9 — Configure WhatsApp webhook

In the Meta Developer Console set your webhook URL to:

```
https://chattosales.duckdns.org/api/v1/ingestion/whatsapp/webhook
```

Use the same value you set in `WHATSAPP_VERIFY_TOKEN`.

### Step 10 — Configure Paystack webhook

In the Paystack Dashboard → Settings → Webhooks, add:

```
https://chattosales.duckdns.org/api/v1/payments/webhook/paystack
```

---

## Ongoing operations

### Deploy a new version

```bash
ssh deploy@204.168.201.192
cd /opt/chattosales
bash deploy/deploy.sh
```

### View logs

```bash
# All services
docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f

# App only
docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f app

# Nginx
docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f nginx
```

### Connect to the database

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec postgres \
    psql -U chattosales -d chattosales
```

### Run an Alembic migration manually

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm migrate alembic upgrade head
```

### Restart a single service

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod restart app
```

---

## Files created by this guide

| File                                | Purpose                                             |
| ----------------------------------- | --------------------------------------------------- |
| `docker-compose.prod.yml`           | Production compose — Nginx + App + Postgres + Redis |
| `nginx/nginx.conf`                  | Nginx main config (rate limiting, security headers) |
| `nginx/conf.d/app.conf`             | HTTP virtual host (active)                          |
| `nginx/conf.d/app-ssl.conf.example` | HTTPS virtual host template (activate in Step 7)    |
| `.env.prod.example`                 | Template — copy to `.env.prod` and fill in secrets  |
| `deploy/setup.sh`                   | One-time OS bootstrap script                        |
| `deploy/deploy.sh`                  | Deploy / update script                              |
