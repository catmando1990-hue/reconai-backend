# ReconAI Backend - Deployment Guide

Complete guide for deploying the ReconAI multi-tenant backend to production.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Local Development Setup](#local-development-setup)
3. [Environment Configuration](#environment-configuration)
4. [Database Setup](#database-setup)
5. [Authentication Setup (Clerk)](#authentication-setup-clerk)
6. [Production Deployment](#production-deployment)
7. [Monitoring & Maintenance](#monitoring--maintenance)
8. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required

- **Python 3.10+** (3.11 recommended)
- **pip** (Python package manager)
- **Git**

### Recommended

- **Virtual environment** (venv or conda)
- **PostgreSQL** (for production) or **SQLite** (for development)
- **Redis** (for rate limiting and caching)
- **Docker** (optional, for containerized deployment)

### External Services

- **Clerk** account (https://clerk.com) - Authentication
- **Anthropic API** key (https://console.anthropic.com) - AI classification
- **Plaid** account (https://plaid.com) - Bank connections (optional)
- **Stripe** account (https://stripe.com) - Payments (optional)

---

## Local Development Setup

### 1. Clone Repository

```bash
git clone https://github.com/your-org/reconai-backend.git
cd reconai-backend
```

### 2. Create Virtual Environment

```bash
# Using venv
python -m venv venv

# Activate on Windows
venv\Scripts\activate

# Activate on macOS/Linux
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment

```bash
# Copy example env file
cp .env.example .env

# Edit .env with your actual values
# At minimum, set:
# - CLERK_SECRET_KEY
# - CLERK_PUBLISHABLE_KEY
# - ANTHROPIC_API_KEY
```

### 5. Initialize Database

```bash
# Database will be created automatically on first run
# Located at: ./data/reconai.db
```

### 6. Run Development Server

```bash
# Using uvicorn directly
uvicorn app.main:app --reload --port 8000

# Or using the run script (if you create one)
python run.py
```

The API will be available at:
- **API:** http://localhost:8000
- **Docs:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

---

## Environment Configuration

### Critical Settings

#### 1. Clerk Authentication

Sign up at https://clerk.com and create an application.

```env
CLERK_SECRET_KEY=sk_test_xxxxx  # From Clerk Dashboard
CLERK_PUBLISHABLE_KEY=pk_test_xxxxx
CLERK_JWKS_URL=https://api.clerk.com/v1/jwks
```

**Clerk Setup:**
1. Create application in Clerk Dashboard
2. Enable authentication methods (Email, Google, etc.)
3. Add redirect URLs (your frontend URLs)
4. Copy API keys to `.env`

#### 2. Anthropic AI

Get API key from https://console.anthropic.com

```env
ANTHROPIC_API_KEY=sk-ant-xxxxx
CLAUDE_MODEL=claude-3-5-sonnet-20241022
```

#### 3. CORS Configuration

```env
# For development (default values)
CORS_ORIGINS=

# For production
CORS_ORIGINS=https://app.reconai.com,https://reconai.com
```

#### 4. Database

```env
# Development (SQLite)
DB_PATH=./data/reconai.db

# Production (PostgreSQL) - future migration
# DATABASE_URL=postgresql://user:pass@localhost:5432/reconai
```

---

## Database Setup

### SQLite (Development)

Database is created automatically on first run. No additional setup needed.

**Location:** `./data/reconai.db`

**Tables Created:**
- `organizations` - Tenant organizations
- `users` - User accounts
- `organization_members` - User-organization relationships
- `entities` - Legal entities within organizations
- `dimensions` - Departments, classes, locations, projects
- `custom_fields` - User-defined fields
- `approval_rules` - Workflow rules
- `approvals` - Approval tracking
- Plus legacy tables (tokens, feedback, uploads)

### PostgreSQL (Production) - Future

For production deployment, you'll want to migrate to PostgreSQL:

1. **Install PostgreSQL**
   ```bash
   # Ubuntu/Debian
   sudo apt install postgresql postgresql-contrib

   # macOS
   brew install postgresql
   ```

2. **Create Database**
   ```bash
   sudo -u postgres psql
   CREATE DATABASE reconai;
   CREATE USER reconai_user WITH PASSWORD 'secure_password';
   GRANT ALL PRIVILEGES ON DATABASE reconai TO reconai_user;
   ```

3. **Update Environment**
   ```env
   DATABASE_URL=postgresql://reconai_user:secure_password@localhost:5432/reconai
   ```

4. **Migration** (to be implemented)
   ```bash
   # Future: Use Alembic for migrations
   alembic upgrade head
   ```

### Database Backups

**SQLite Backup:**
```bash
# Simple file copy
cp ./data/reconai.db ./backups/reconai_$(date +%Y%m%d).db

# Or using sqlite3
sqlite3 ./data/reconai.db ".backup ./backups/reconai_$(date +%Y%m%d).db"
```

**PostgreSQL Backup:**
```bash
pg_dump -U reconai_user reconai > backup_$(date +%Y%m%d).sql
```

---

## Authentication Setup (Clerk)

### 1. Create Clerk Application

1. Go to https://clerk.com/dashboard
2. Click "Add application"
3. Choose authentication methods:
   - ✅ Email/Password
   - ✅ Google OAuth
   - ✅ GitHub OAuth (optional)
   - ✅ Microsoft OAuth (for enterprise)

### 2. Configure Redirect URLs

Add your frontend URLs:

**Development:**
- `http://localhost:3000`
- `http://localhost:5173` (Vite)

**Production:**
- `https://app.reconai.com`
- `https://reconai.com`

### 3. Configure Session Settings

- **Session lifetime:** 7 days (recommended)
- **Multi-session:** Enabled
- **Refresh tokens:** Enabled

### 4. Get API Keys

From Clerk Dashboard → API Keys:

```env
CLERK_SECRET_KEY=sk_test_xxxxx
CLERK_PUBLISHABLE_KEY=pk_test_xxxxx
```

### 5. Test Authentication

```bash
# Start backend
uvicorn app.main:app --reload

# Test token verification
curl -X POST http://localhost:8000/api/auth/verify \
  -H "Authorization: Bearer <clerk_jwt_token>"
```

---

## Production Deployment

### Option 1: Traditional Server (Ubuntu/Debian)

#### 1. Server Setup

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python 3.11
sudo apt install python3.11 python3.11-venv python3-pip

# Install PostgreSQL
sudo apt install postgresql postgresql-contrib

# Install Redis (optional)
sudo apt install redis-server

# Install Nginx
sudo apt install nginx
```

#### 2. Application Setup

```bash
# Create app user
sudo useradd -m -s /bin/bash reconai
sudo su - reconai

# Clone repository
git clone https://github.com/your-org/reconai-backend.git
cd reconai-backend

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
nano .env  # Edit with production values
```

#### 3. Systemd Service

Create `/etc/systemd/system/reconai.service`:

```ini
[Unit]
Description=ReconAI Backend API
After=network.target postgresql.service

[Service]
User=reconai
Group=reconai
WorkingDirectory=/home/reconai/reconai-backend
Environment="PATH=/home/reconai/reconai-backend/venv/bin"
ExecStart=/home/reconai/reconai-backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4

Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start service
sudo systemctl enable reconai
sudo systemctl start reconai
sudo systemctl status reconai
```

#### 4. Nginx Configuration

Create `/etc/nginx/sites-available/reconai`:

```nginx
server {
    listen 80;
    server_name api.reconai.com;

    # Redirect to HTTPS
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name api.reconai.com;

    # SSL certificates (use Let's Encrypt)
    ssl_certificate /etc/letsencrypt/live/api.reconai.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.reconai.com/privkey.pem;

    # SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Proxy to FastAPI
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # File upload size
    client_max_body_size 25M;

    # Logging
    access_log /var/log/nginx/reconai_access.log;
    error_log /var/log/nginx/reconai_error.log;
}
```

```bash
# Enable site
sudo ln -s /etc/nginx/sites-available/reconai /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

#### 5. SSL Certificate (Let's Encrypt)

```bash
# Install certbot
sudo apt install certbot python3-certbot-nginx

# Get certificate
sudo certbot --nginx -d api.reconai.com

# Auto-renewal (already configured)
sudo systemctl status certbot.timer
```

---

### Option 2: Docker Deployment

#### Dockerfile

Create `Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create data directory
RUN mkdir -p /app/data

# Expose port
EXPOSE 8000

# Run application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

#### docker-compose.yml

```yaml
version: '3.8'

services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DB_PATH=/app/data/reconai.db
      - CLERK_SECRET_KEY=${CLERK_SECRET_KEY}
      - CLERK_PUBLISHABLE_KEY=${CLERK_PUBLISHABLE_KEY}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    volumes:
      - ./data:/app/data
      - ./uploads:/app/uploads
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./ssl:/etc/nginx/ssl
    depends_on:
      - api
    restart: unless-stopped
```

```bash
# Build and run
docker-compose up -d

# View logs
docker-compose logs -f api

# Stop
docker-compose down
```

---

### Option 3: Cloud Platforms

#### Render.com

1. Create new Web Service
2. Connect GitHub repository
3. Configure:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 4`
4. Add environment variables from `.env.example`
5. Deploy

#### Railway.app

```yaml
# railway.json
{
  "build": {
    "builder": "NIXPACKS"
  },
  "deploy": {
    "startCommand": "uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 4",
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  }
}
```

#### AWS EC2

Similar to traditional server setup, but:
1. Launch EC2 instance (Ubuntu 22.04)
2. Configure security groups (ports 80, 443, 22)
3. Assign Elastic IP
4. Follow traditional server setup steps
5. Use RDS for PostgreSQL (recommended)
6. Use S3 for file uploads

---

## Monitoring & Maintenance

### Application Logs

```bash
# Systemd service logs
sudo journalctl -u reconai -f

# Nginx logs
sudo tail -f /var/log/nginx/reconai_access.log
sudo tail -f /var/log/nginx/reconai_error.log

# Application logs (if configured)
tail -f /var/log/reconai/app.log
```

### Health Checks

```bash
# Health endpoint
curl https://api.reconai.com/health

# Expected response
{"status":"healthy","service":"reconai-backend"}
```

### Database Maintenance

```bash
# Vacuum SQLite (optimize)
sqlite3 /path/to/reconai.db "VACUUM;"

# PostgreSQL maintenance
sudo -u postgres psql reconai -c "VACUUM ANALYZE;"
```

### Backup Automation

Create `/home/reconai/backup.sh`:

```bash
#!/bin/bash

BACKUP_DIR="/home/reconai/backups"
DB_PATH="/home/reconai/reconai-backend/data/reconai.db"
DATE=$(date +%Y%m%d_%H%M%S)

# Create backup directory
mkdir -p $BACKUP_DIR

# Backup database
sqlite3 $DB_PATH ".backup $BACKUP_DIR/reconai_$DATE.db"

# Compress
gzip $BACKUP_DIR/reconai_$DATE.db

# Delete backups older than 30 days
find $BACKUP_DIR -name "*.gz" -mtime +30 -delete

# Upload to S3 (optional)
# aws s3 cp $BACKUP_DIR/reconai_$DATE.db.gz s3://reconai-backups/
```

Add to crontab:
```bash
# Run daily at 2 AM
0 2 * * * /home/reconai/backup.sh
```

---

## Troubleshooting

### Common Issues

#### 1. Authentication Errors

**Error:** `401 Unauthorized - Invalid token`

**Solution:**
- Verify Clerk API keys in `.env`
- Check Clerk JWKS URL is correct
- Ensure frontend is using correct Clerk publishable key
- Verify token hasn't expired

#### 2. CORS Errors

**Error:** `CORS policy: No 'Access-Control-Allow-Origin' header`

**Solution:**
```env
# Add frontend domain to CORS_ORIGINS
CORS_ORIGINS=https://app.reconai.com
```

#### 3. Database Locked

**Error:** `database is locked`

**Solution:**
- SQLite doesn't handle concurrent writes well
- Consider PostgreSQL for production
- Reduce worker count if using SQLite

#### 4. Import Errors

**Error:** `ModuleNotFoundError: No module named 'app'`

**Solution:**
```bash
# Ensure you're in the correct directory
cd /path/to/reconai-backend

# Activate virtual environment
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

#### 5. Permission Denied

**Error:** `403 Forbidden - Permission denied: create_transactions`

**Solution:**
- Check user's role in organization
- Verify role has required permission
- Owner role has all permissions

### Performance Issues

#### Slow API Responses

1. **Enable caching:**
   ```env
   CACHE_BACKEND=redis
   REDIS_URL=redis://localhost:6379/0
   ```

2. **Add database indexes:**
   - Already configured in `db.py`
   - Consider additional indexes for frequent queries

3. **Increase workers:**
   ```bash
   # In systemd service or docker-compose
   --workers 8  # Instead of 4
   ```

#### High Memory Usage

1. **Reduce workers:**
   ```bash
   --workers 2
   ```

2. **Use production ASGI server:**
   ```bash
   pip install gunicorn
   gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker
   ```

---

## Security Checklist

- [ ] Change all default passwords and secrets
- [ ] Enable HTTPS (SSL certificates)
- [ ] Configure firewall (UFW or security groups)
- [ ] Set up fail2ban for SSH protection
- [ ] Enable rate limiting
- [ ] Configure CORS properly
- [ ] Set strong JWT secret key
- [ ] Enable database backups
- [ ] Set up monitoring/alerting
- [ ] Review and limit API permissions
- [ ] Enable audit logging
- [ ] Keep dependencies updated

---

## Support

For deployment assistance:
- **Email:** support@reconai.com
- **Veterans:** veterans@reconai.com (Priority support)
- **Documentation:** https://docs.reconai.com

---

**🚀 Happy Deploying!**
# Backend Deployment Fri, Dec 26, 2025  2:41:28 PM
