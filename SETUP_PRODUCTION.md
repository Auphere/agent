# 🚀 Auphere Agent - Setup para Producción

Guía completa para desplegar el agente en producción con todos los servicios necesarios.

## 📋 Requisitos Previos

- Python 3.11 o 3.12
- PostgreSQL 14+ (o Docker)
- Redis 6+ (o Docker)
- Rust Places API corriendo en puerto 3001
- API Keys: OpenAI y/o Anthropic

---

## 🐳 Opción 1: Docker Compose (Recomendado)

### 1. Crear `docker-compose.yml` en la raíz del proyecto

```yaml
version: "3.8"

services:
  # PostgreSQL Database
  postgres:
    image: postgres:16-alpine
    container_name: auphere-db
    environment:
      POSTGRES_USER: auphere
      POSTGRES_PASSWORD: ${DB_PASSWORD:-auphere_secure_password}
      POSTGRES_DB: auphere-agent
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U auphere"]
      interval: 10s
      timeout: 5s
      retries: 5

  # Redis Cache
  redis:
    image: redis:7-alpine
    container_name: auphere-redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5

  # Auphere Agent (Python FastAPI)
  agent:
    build:
      context: ./auphere-agent
      dockerfile: Dockerfile
    container_name: auphere-agent
    ports:
      - "8001:8001"
    environment:
      - DATABASE_URL=postgresql://auphere:${DB_PASSWORD:-auphere_secure_password}@postgres:5432/auphere-agent
      - REDIS_URL=redis://redis:6379/0
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - PLACES_API_URL=http://places:3001
      - ENVIRONMENT=production
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - ./auphere-agent:/app
    command: uvicorn api.main:app --host 0.0.0.0 --port 8001

volumes:
  postgres_data:
  redis_data:
```

### 2. Crear `Dockerfile` en `auphere-agent/`

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

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create .env from example if not exists
RUN if [ ! -f .env ]; then cp env.example .env; fi

# Initialize database on startup
CMD ["sh", "-c", "python scripts/init_db.py && uvicorn api.main:app --host 0.0.0.0 --port 8001"]
```

### 3. Iniciar servicios

```bash
# Crear .env en la raíz con tus API keys
cat > .env << EOF
OPENAI_API_KEY=sk-your-key-here
ANTHROPIC_API_KEY=sk-ant-your-key-here
DB_PASSWORD=auphere_secure_password
EOF

# Iniciar todos los servicios
docker-compose up -d

# Ver logs
docker-compose logs -f agent

# Verificar que todo esté corriendo
docker-compose ps
```

---

## 💻 Opción 2: Setup Manual (Sin Docker)

### 1. PostgreSQL

#### macOS (Homebrew)

```bash
brew install postgresql@16
brew services start postgresql@16

# Crear base de datos
createdb auphere-agent
```

#### Ubuntu/Debian

```bash
sudo apt-get update
sudo apt-get install postgresql postgresql-contrib
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Crear usuario y base de datos
sudo -u postgres psql -c "CREATE DATABASE \"auphere-agent\";"
sudo -u postgres psql -c "CREATE USER auphere WITH PASSWORD 'password';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE \"auphere-agent\" TO auphere;"
```

#### Windows

Descarga e instala PostgreSQL desde [postgresql.org](https://www.postgresql.org/download/windows/)

### 2. Redis

#### macOS (Homebrew)

```bash
brew install redis
brew services start redis
```

#### Ubuntu/Debian

```bash
sudo apt-get install redis-server
sudo systemctl start redis-server
sudo systemctl enable redis-server
```

#### Windows

Descarga desde [redis.io](https://redis.io/download) o usa WSL2

### 3. Python Environment

```bash
cd auphere-agent

# Crear virtual environment
python3.11 -m venv .venv
source .venv/bin/activate  # En Windows: .venv\Scripts\activate

# Instalar dependencias
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

### 4. Configuración

```bash
# Copiar template de environment
cp env.example .env

# Editar .env con tus valores
nano .env  # o vim, code, etc.
```

**Valores clave a configurar en `.env`:**

```bash
# API Keys (REQUERIDO)
OPENAI_API_KEY=sk-your-openai-key
ANTHROPIC_API_KEY=sk-ant-your-anthropic-key

# Database (ajustar si es necesario)
DATABASE_URL=postgresql://auphere:password@localhost:5432/auphere-agent

# Redis (ajustar si es necesario)
REDIS_URL=redis://localhost:6379/0
REDIS_ENABLED=true

# External Services
PLACES_API_URL=http://localhost:3001
BACKEND_URL=http://localhost:8000

# Environment
ENVIRONMENT=production
LOG_LEVEL=INFO
```

### 5. Inicializar Base de Datos

```bash
# Asegúrate de que PostgreSQL esté corriendo
python scripts/init_db.py
```

### 6. Iniciar el Agente

```bash
# Modo desarrollo (con reload)
uvicorn api.main:app --host 0.0.0.0 --port 8001 --reload

# Modo producción (con workers)
uvicorn api.main:app --host 0.0.0.0 --port 8001 --workers 4
```

---

## ✅ Verificación de Setup

### 1. Health Check

```bash
curl http://localhost:8001/agent/health
```

**Respuesta esperada:**

```json
{
  "status": "healthy",
  "service": "auphere-agent",
  "version": "0.1.0",
  "environment": "production",
  "metrics": {
    "total_queries": 0,
    "uptime_seconds": 42
  }
}
```

### 2. Test Query

```bash
curl -X POST "http://localhost:8001/agent/query" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "query": "Hola, cómo estás?",
    "language": "es"
  }'
```

### 3. Verificar Database

```bash
# Conectar a PostgreSQL
psql -U auphere -d auphere-agent

# Ver tablas
\dt

# Ver conversaciones (debería estar vacía al inicio)
SELECT COUNT(*) FROM conversation_turns;

# Salir
\q
```

### 4. Verificar Redis

```bash
# Conectar a Redis
redis-cli

# Ver keys (debería estar vacío al inicio)
KEYS auphere:agent:*

# Info
INFO

# Salir
exit
```

---

## 🔐 Seguridad en Producción

### 1. Variables de Entorno Seguras

**NO** comitear `.env` al repositorio. Usar:

- **AWS Secrets Manager**
- **HashiCorp Vault**
- **Kubernetes Secrets**
- **Azure Key Vault**

### 2. Database

```bash
# Cambiar password por defecto
ALTER USER auphere WITH PASSWORD 'strong_password_here';

# Habilitar SSL
# En postgresql.conf:
ssl = on
```

### 3. Redis

```bash
# Configurar password
# En redis.conf:
requirepass your_strong_password_here

# Actualizar REDIS_URL en .env
REDIS_URL=redis://:your_strong_password_here@localhost:6379/0
```

### 4. Firewall

```bash
# Permitir solo tráfico necesario
ufw allow 8001/tcp  # Agent API
ufw allow 5432/tcp  # PostgreSQL (solo si acceso externo necesario)
ufw allow 6379/tcp  # Redis (solo si acceso externo necesario)
```

---

## 📊 Monitoring en Producción

### 1. Logs

```bash
# Ver logs en tiempo real
tail -f logs/agent.log

# Con Docker
docker-compose logs -f agent
```

### 2. Metrics Endpoints

```bash
# Summary últimos 7 días
curl http://localhost:8001/agent/metrics/summary?days_back=7

# Performance stats
curl http://localhost:8001/agent/metrics/performance
```

### 3. Grafana Dashboard (Opcional)

Integrar con Prometheus + Grafana:

1. Instalar `prometheus-fastapi-instrumentator`
2. Exponer métricas en `/metrics`
3. Configurar Prometheus scraping
4. Crear dashboard en Grafana

---

## 🔄 Actualización y Mantenimiento

### Rolling Update

```bash
# 1. Pull latest changes
git pull origin main

# 2. Install new dependencies
source .venv/bin/activate
pip install -r requirements.txt

# 3. Run migrations (si hay cambios en DB)
python scripts/migrate_db.py  # Crear este script si es necesario

# 4. Restart service
# Con systemd:
sudo systemctl restart auphere-agent

# Con Docker:
docker-compose restart agent

# Con PM2:
pm2 restart auphere-agent
```

### Backup Database

```bash
# Backup manual
pg_dump -U auphere auphere-agent > backup_$(date +%Y%m%d).sql

# Restore
psql -U auphere auphere-agent < backup_20240101.sql

# Automated backup (crontab)
0 2 * * * pg_dump -U auphere auphere-agent > /backups/auphere_$(date +\%Y\%m\%d).sql
```

### Cache Management

```bash
# Limpiar cache completo (Redis)
redis-cli FLUSHDB

# Limpiar solo keys del agent
redis-cli KEYS "auphere:agent:*" | xargs redis-cli DEL
```

---

## 🚨 Troubleshooting

### Agent no inicia

```bash
# Verificar logs
tail -f logs/agent.log

# Verificar dependencias
pip check

# Verificar puertos
lsof -i :8001
```

### Database connection failed

```bash
# Verificar PostgreSQL corriendo
systemctl status postgresql

# Verificar credenciales
psql -U auphere -d auphere-agent -h localhost

# Verificar DATABASE_URL en .env
cat .env | grep DATABASE_URL
```

### Redis connection failed

```bash
# Verificar Redis corriendo
systemctl status redis

# Test connection
redis-cli ping

# Verificar REDIS_URL en .env
cat .env | grep REDIS_URL
```

### High latency

1. Verificar índices en PostgreSQL
2. Aumentar Redis cache TTLs
3. Activar Budget Mode (`BUDGET_MODE=true`)
4. Escalar horizontalmente (más workers)

### High costs

1. Verificar cache hit rate en métricas
2. Activar Budget Mode
3. Reducir complexity threshold en router
4. Analizar queries más costosas en metrics

---

## 📈 Scaling

### Horizontal Scaling

```bash
# Múltiples workers
uvicorn api.main:app --workers 8 --host 0.0.0.0 --port 8001

# Load balancer (Nginx)
# Configurar upstream con múltiples instancias del agent
```

### Database Read Replicas

```sql
-- Configurar read replica en PostgreSQL
-- Separar reads (metrics, history) de writes (save_turn)
```

### Redis Cluster

```bash
# Configurar Redis cluster para alta disponibilidad
# Actualizar REDIS_URL con cluster endpoints
```

---

## 🎯 Checklist de Producción

- [ ] PostgreSQL configurado y seguro
- [ ] Redis configurado y seguro
- [ ] `.env` con todas las variables correctas
- [ ] API keys válidas (OpenAI, Anthropic)
- [ ] Database inicializada (`init_db.py`)
- [ ] Health check respondiendo
- [ ] Test query exitoso
- [ ] Logs configurados
- [ ] Monitoring activo
- [ ] Backups automáticos configurados
- [ ] Firewall configurado
- [ ] SSL/TLS habilitado (si aplica)
- [ ] Rate limiting configurado (si aplica)

---

**¡Listo! El Auphere AI Agent está en producción** 🚀
