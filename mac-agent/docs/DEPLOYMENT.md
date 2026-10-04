# Deployment Guide

Production deployment instructions for Diving Analytics Platform.

---

## Production Checklist

- [ ] Docker & Docker Compose installed
- [ ] Server has 2GB RAM minimum
- [ ] Ports 6090, 6002, 6432 available
- [ ] Environment variables configured
- [ ] SSL/TLS certificates obtained (optional)
- [ ] Backup strategy in place
- [ ] Monitoring setup

---

## Docker Deployment

### 1. Prepare Server

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Verify installation
docker --version
docker-compose --version
```

### 2. Clone Repository

```bash
git clone https://github.com/maxime-c16/diving-analyser.git
cd diving-analyser
```

### 3. Configure Environment

```bash
# Copy template
cp .env.example .env

# Edit with production values
nano .env
```

**Production Settings:**
```bash
POSTGRES_USER=diving
POSTGRES_PASSWORD=CHANGE_ME_PRODUCTION_PASSWORD
POSTGRES_DB=diving_analyzer_db

# Backend
DATABASE_URL=postgresql://diving:PRODUCTION_PASSWORD@postgres:5432/diving_analyzer_db
API_TITLE=Diving Analytics API
API_VERSION=1.0.0

# Frontend
VITE_API_URL=/api
VITE_WS_URL=/api/v1/ws
VITE_HMR_HOST=192.168.1.57
```

### 4. Start Services

```bash
# Start in background
docker-compose up -d

# Check logs
docker-compose logs -f

# Verify all services running
docker-compose ps
```

### 5. Initialize Database

```bash
# Run migrations
docker-compose exec backend alembic upgrade head

# Import sample data (optional)
docker-compose exec backend python -c "from app.services.import_service import import_sample_data; import_sample_data()"
```

---

## SSL/TLS Setup (Optional)

### Using Let's Encrypt

```bash
# Install certbot
sudo apt install certbot

# Obtain certificate
sudo certbot certonly --standalone -d your-domain.com

# Update nginx configuration
# Edit nginx/conf.d/default.conf:

server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # ... rest of config
}
```

---

## Monitoring

### Health Checks

```bash
# Backend health
curl http://localhost:6002/api/health

# Database health
docker-compose exec postgres pg_isready -U diving

# Check all services
docker-compose ps
```

### Logs

```bash
# All logs
docker-compose logs -f

# Specific service
docker-compose logs -f backend

# Last 100 lines
docker-compose logs --tail=100 backend
```

---

## Backup & Restore

### Backup Database

```bash
# Create backup
docker-compose exec postgres pg_dump -U diving diving_analyzer_db > backup_$(date +%Y%m%d).sql

# Backup to tar.gz
tar -czf backup_$(date +%Y%m%d).tar.gz backup_*.sql
```

### Restore Database

```bash
# Stop services
docker-compose down

# Start only postgres
docker-compose up -d postgres

# Restore from backup
cat backup_20260201.sql | docker-compose exec -T postgres psql -U diving diving_analyzer_db

# Start all services
docker-compose up -d
```

---

## Updates

```bash
# Pull latest code
git pull origin main

# Rebuild containers
docker-compose build

# Restart services
docker-compose up -d

# Run migrations
docker-compose exec backend alembic upgrade head
```

---

## Scaling

### Resource Limits

Edit `docker-compose.yml`:

```yaml
services:
  backend:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 1G
        reservations:
          cpus: '1'
          memory: 512M
```

### Multiple Workers

```yaml
services:
  backend:
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

---

See [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md) for disaster recovery procedures.
