# 🤖 Auphere Agent

**AI Conversational Agent Service**

Microservicio de agente de IA conversacional de Auphere, construido con FastAPI, LangGraph y LangChain para proporcionar recomendaciones inteligentes de lugares.

---

## 📋 **Tabla de Contenidos**

- [Descripción](#descripción)
- [Tecnologías](#tecnologías)
- [Requisitos Previos](#requisitos-previos)
- [Instalación](#instalación)
- [Configuración](#configuración)
- [Ejecución](#ejecución)
- [API Endpoints](#api-endpoints)
- [Arquitectura del Agent](#arquitectura-del-agent)
- [Testing](#testing)
- [Docker](#docker)
- [Troubleshooting](#troubleshooting)

---

## 📝 **Descripción**

El Agent de Auphere es un sistema de IA conversacional que:

- **Entiende lenguaje natural** en múltiples idiomas (ES, EN, CA, GL)
- **Detecta intenciones** de usuario (búsqueda, recomendación, planificación)
- **Integra con LLMs** (OpenAI GPT-4, Anthropic Claude)
- **Gestiona contexto** de conversaciones con memoria persistente
- **Orquesta tools** para búsqueda de lugares y planificación

---

## 🛠️ **Tecnologías**

- **Framework:** FastAPI 0.115+
- **IA/ML:** LangChain 0.3+, LangGraph 0.2+
- **LLMs:** OpenAI GPT-4, Anthropic Claude
- **Base de datos:** PostgreSQL (con SQLAlchemy)
- **Caché:** Redis
- **Python:** 3.11+

### **Dependencias Principales**

```
fastapi==0.115.6
langchain==0.3.15
langchain-core==0.3.31
langgraph==0.2.61
langchain-openai==0.3.1
langchain-anthropic==0.3.4
sqlalchemy==2.0.36
asyncpg==0.30.0
redis==5.2.1
```

---

## ✅ **Requisitos Previos**

### **Opción 1: Docker**
- Docker >= 24.0
- Docker Compose >= 2.20

### **Opción 2: Local**
- Python 3.11+
- PostgreSQL 17+
- Redis 7+
- API Keys de OpenAI y/o Anthropic

---

## 📦 **Instalación**

### **Opción 1: Con Docker (Recomendado)**

Ver [README principal](../README.md) para instrucciones de Docker Compose.

### **Opción 2: Desarrollo Local**

```bash
# Navegar al directorio del agent
cd auphere-agent

# Crear entorno virtual
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate

# Instalar dependencias
pip install --upgrade pip
pip install -r requirements.txt
```

---

## ⚙️ **Configuración**

### **Variables de Entorno**

Crea un archivo `.env` en `auphere-agent/`:

```env
# ============================================
# Service Metadata
# ============================================
SERVICE_NAME=auphere-agent
VERSION=0.1.0
ENVIRONMENT=development
LOG_LEVEL=INFO

# ============================================
# Networking
# ============================================
AGENT_HOST=0.0.0.0
AGENT_PORT=8001
FRONTEND_URL=http://localhost:3000

# ============================================
# LLM API Keys
# ============================================
OPENAI_API_KEY=sk-your_openai_api_key
ANTHROPIC_API_KEY=sk-ant-your_anthropic_api_key

# ============================================
# External API Keys (Optional)
# ============================================
GOOGLE_PLACES_API_KEY=your_google_places_api_key

# ============================================
# Internal Services
# ============================================
DATABASE_URL=postgresql+asyncpg://auphere:password@localhost:5432/auphere-agent
REDIS_URL=redis://localhost:6379/0
REDIS_ENABLED=true
REDIS_KEY_PREFIX=auphere:agent

PLACES_API_URL=http://localhost:8002
PLACES_API_TIMEOUT=10
BACKEND_URL=http://localhost:8000

# ============================================
# Cache TTLs (in seconds)
# ============================================
CACHE_TTL_INTENT=3600
CACHE_TTL_PLACES=1800
CACHE_TTL_TRANSLATION=86400
CACHE_TTL_USER_CONTEXT=3600

# ============================================
# Localization
# ============================================
SUPPORTED_LANGUAGES=es,en,ca,gl
DEFAULT_LANGUAGE=es

# ============================================
# Model Configuration
# ============================================
BUDGET_MODE=false
PREFERRED_MODEL=gpt-4o-mini

# ============================================
# Observability
# ============================================
ENABLE_TRACING=true
TRACE_LEVEL=debug
```

### **Tabla de Variables**

| Variable | Descripción | Requerido | Valor por Defecto |
|----------|-------------|-----------|-------------------|
| `OPENAI_API_KEY` | API Key de OpenAI | ✅ | - |
| `ANTHROPIC_API_KEY` | API Key de Anthropic | ⚠️ | - |
| `DATABASE_URL` | URL de PostgreSQL | ✅ | `postgresql+asyncpg://localhost:5432/auphere-agent` |
| `REDIS_URL` | URL de Redis | ✅ | `redis://localhost:6379/0` |
| `REDIS_ENABLED` | Habilitar Redis | ✅ | `true` |
| `PLACES_API_URL` | URL del microservicio Places | ✅ | `http://localhost:8002` |
| `BACKEND_URL` | URL del Backend | ✅ | `http://localhost:8000` |
| `SUPPORTED_LANGUAGES` | Idiomas soportados (CSV) | ✅ | `es,en,ca,gl` |
| `DEFAULT_LANGUAGE` | Idioma por defecto | ✅ | `es` |
| `PREFERRED_MODEL` | Modelo LLM por defecto | ✅ | `gpt-4o-mini` |
| `BUDGET_MODE` | Modo económico (usa modelos más baratos) | ✅ | `false` |

---

## 🏃 **Ejecución**

### **Desarrollo Local**

```bash
# Activar entorno virtual
source venv/bin/activate

# Ejecutar con hot reload
python -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8001

# O usar el entry point
python api/main.py
```

### **Con Docker**

```bash
# Desde la raíz del proyecto
docker-compose up agent

# O build y run
docker build -t auphere-agent .
docker run -p 8001:8001 --env-file .env auphere-agent
```

### **Verificar que funciona**

```bash
# Health check
curl http://localhost:8001/health

# API docs
open http://localhost:8001/docs
```

---

## 📚 **API Endpoints**

### **Chat & Agent**

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| POST | `/chat` | Enviar mensaje al agent |
| POST | `/chat/stream` | Chat con streaming |
| GET | `/chats` | Listar chats del usuario |
| GET | `/chats/{session_id}` | Obtener historial de chat |
| POST | `/chats/create` | Crear nuevo chat |

### **Agent Tools**

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| POST | `/tools/search-places` | Buscar lugares |
| POST | `/tools/recommend` | Obtener recomendaciones |
| POST | `/tools/create-plan` | Crear plan de viaje |

### **User Preferences**

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/user/preferences` | Obtener preferencias |
| PUT | `/user/preferences` | Actualizar preferencias |

### **Metrics & Debug**

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/metrics` | Métricas del agent |
| GET | `/metrics/usage` | Uso de modelos y costos |

### **Health & Docs**

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/` | Root endpoint |
| GET | `/health` | Health check |
| GET | `/docs` | Swagger UI |
| GET | `/redoc` | ReDoc UI |

---

## 🧠 **Arquitectura del Agent**

### **Flujo de Conversación**

```
User Query
    ↓
[Intent Detection] ← LangChain
    ↓
[Context Loading] ← SQLAlchemy + Redis
    ↓
[LangGraph Router]
    ├─→ [Search Tool] → Places API
    ├─→ [Recommend Tool] → LLM + Places
    ├─→ [Plan Tool] → LLM + Planning
    └─→ [Chitchat] → LLM
    ↓
[Response Generation] ← LLM
    ↓
[Save to Database] → PostgreSQL
    ↓
Response to User
```

### **Componentes Principales**

#### **1. Intent Detection**
Detecta la intención del usuario usando LLM:
- `search` - Buscar lugares específicos
- `recommend` - Recomendaciones personalizadas
- `plan` - Crear planes de viaje
- `chitchat` - Conversación casual

#### **2. LangGraph State Machine**
Orquesta el flujo conversacional con nodos y edges.

#### **3. Tools (Herramientas)**
- `search_places`: Búsqueda en Places API
- `get_place_details`: Detalles de un lugar
- `create_plan`: Generación de itinerarios

#### **4. Memory & Context**
- **Short-term:** Redis para sesiones activas
- **Long-term:** PostgreSQL para historial

---

## 🧪 **Testing**

```bash
# Instalar dependencias de testing
pip install pytest pytest-asyncio

# Ejecutar tests
pytest

# Con coverage
pytest --cov=src --cov=api --cov-report=html

# Ver reporte
open htmlcov/index.html
```

### **Estructura de Tests**

```
auphere-agent/
├── tests/
│   ├── test_agent.py
│   ├── test_intent_detection.py
│   ├── test_tools.py
│   └── test_cache.py
```

---

## 🐳 **Docker**

### **Build**

```bash
docker build -t auphere-agent:latest .
```

### **Run**

```bash
docker run -p 8001:8001 \
  -e OPENAI_API_KEY=sk-your-key \
  -e DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/auphere-agent \
  -e REDIS_URL=redis://redis:6379/0 \
  -e PLACES_API_URL=http://places:8002 \
  auphere-agent:latest
```

---

## 🔧 **Troubleshooting**

### **Error: OpenAI API key not set**

```bash
# Verificar que la key existe
echo $OPENAI_API_KEY

# Debe empezar con sk-
# Si no está configurada, añadirla al .env
```

### **Error: Database connection failed**

```bash
# Verificar que PostgreSQL está corriendo
docker-compose ps postgres

# Verificar DATABASE_URL
echo $DATABASE_URL

# Probar conexión manualmente
psql postgresql://auphere:password@localhost:5432/auphere-agent
```

### **Error: Redis connection failed**

```bash
# Verificar que Redis está corriendo
redis-cli ping

# Verificar REDIS_URL
echo $REDIS_URL

# El agent puede funcionar sin Redis (sin caché)
export REDIS_ENABLED=false
```

### **Error: Places API not responding**

```bash
# Verificar que Places está corriendo
curl http://localhost:8002/health

# Verificar PLACES_API_URL
echo $PLACES_API_URL
```

### **Warning: No supported language**

```bash
# Verificar idiomas soportados
echo $SUPPORTED_LANGUAGES

# Debe ser una lista separada por comas: es,en,ca,gl
```

---

## 📁 **Estructura del Proyecto**

```
auphere-agent/
├── api/
│   ├── main.py              # FastAPI app
│   ├── routes.py            # Endpoints principales
│   ├── chat_routes.py       # Endpoints de chat
│   ├── streaming_routes.py  # Streaming endpoints
│   └── models.py            # Pydantic models
├── src/
│   ├── agent/               # Lógica del agent
│   │   ├── graph.py         # LangGraph state machine
│   │   ├── tools.py         # Herramientas del agent
│   │   └── prompts.py       # Prompts de LLM
│   ├── config/
│   │   └── settings.py      # Configuración
│   ├── database/
│   │   ├── connection.py    # Setup de SQLAlchemy
│   │   └── models.py        # Modelos de BD
│   └── utils/
│       ├── cache_manager.py # Gestión de Redis
│       └── logger.py        # Logging estructurado
├── tests/                   # Tests
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## 📊 **Modelos Soportados**

### **OpenAI**
- `gpt-4o` - Más capaz, más caro
- `gpt-4o-mini` - Balance precio/rendimiento ⭐
- `gpt-3.5-turbo` - Económico

### **Anthropic**
- `claude-3-opus` - Más capaz
- `claude-3-sonnet` - Balance ⭐
- `claude-3-haiku` - Económico

### **Configuración de Modelo**

El modelo se selecciona automáticamente según:
1. Preferencia del usuario (`preferred_model`)
2. Modo presupuesto (`budget_mode`)
3. Complejidad de la query

---

## 🔗 **Enlaces Útiles**

- [LangChain Documentation](https://python.langchain.com/)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [OpenAI API Reference](https://platform.openai.com/docs/api-reference)
- [Anthropic API Reference](https://docs.anthropic.com/)

---

## 📝 **Notas de Desarrollo**

### **Agregar nuevas herramientas**

1. Define la tool en `src/agent/tools.py`
2. Registra la tool en el LangGraph
3. Actualiza los prompts si es necesario

### **Cambiar modelos**

Modifica `PREFERRED_MODEL` en `.env` o ajusta la lógica en `src/agent/graph.py`.

### **Multilenguaje**

El agent soporta ES, EN, CA, GL. Añade más idiomas en `SUPPORTED_LANGUAGES`.

---

## 🤝 **Contribuir**

1. Fork el proyecto
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request
