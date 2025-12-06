# Auphere Agent Service

FastAPI microservice that isolates the AI agent responsibilities (intent classification, routing, tool orchestration) from the core backend. The implementation follows the refactored architecture documented in `docs/Prompt-Cursor-Auphere-Agent.md`.

> **Status**: ✅ Steps 1-3 implemented (Context Validation + Intent Classification + LLM Routing + ReAct Agent + Places Tool). The pipeline is fully functional end-to-end.

## Project Structure

```
auphere-agent/
├── api/                     # FastAPI surface
├── src/
│   ├── config/              # Settings, constants, model config
│   ├── validators/          # Context validation (Step 1)
│   ├── utils/               # Logging, helpers
│   ├── agents/              # ReAct agent (Step 3 - placeholder)
│   ├── classifiers/         # Intent classifier (Step 2 - placeholder)
│   ├── routers/             # LLM router (Step 2 - placeholder)
│   ├── tools/               # Tool registry (Step 3 - placeholder)
│   ├── i18n/                # Language helpers (Step 4 - placeholder)
│   └── database/            # DAL (placeholder)
├── streamlit/               # Streamlit testing interface (implemented)
├── tests/                   # Pytest suites
├── env.example              # Environment template (rename to `.env`)
├── requirements.txt
└── run_agent.sh
```

## Getting Started

> **Python**: use 3.11 or 3.12 **ONLY**. The pandas/numpy wheels in `requirements.txt` are not yet compatible with Python 3.13/3.14 (C-API breaking changes). Use **Python 3.11** or **3.12** to avoid compilation errors.

```bash
cd auphere-agent

# Use Python 3.11 or 3.12 (NOT 3.13/3.14)
python3.11 -m venv .venv   # or python3.12
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

cp env.example .env  # `.env` filenames are blocked in this workspace, so copy manually
```

## Running the API

```bash
PYTHONPATH=. uvicorn api.main:app --host 0.0.0.0 --port 8001 --reload
```

Or use the helper script:

```bash
chmod +x run_agent.sh
./run_agent.sh
```

## Running the Streamlit Testing Interface

Para probar el agente con una interfaz gráfica antes de integrarlo con el frontend:

```bash
# Asegúrate de que el agent y places estén corriendo primero
./run_streamlit.sh
```

La interfaz se abrirá en `http://localhost:8501` con 4 páginas:
- 🤖 **Main App**: Testing end-to-end del agente completo
- 🎯 **Intent Classifier**: Validación de clasificación de intenciones
- ⚙️ **Model Router**: Visualización de selección de modelos LLM
- 📍 **Places Tool**: Testing directo del servicio de lugares

Ver documentación completa en [`streamlit/README.md`](streamlit/README.md)

## Testing

```bash
PYTHONPATH=. pytest
```

## Environment Variables

The service relies on the variables exposed in `env.example` (copy to `.env`). Key values:

- `SUPPORTED_LANGUAGES`: Comma-separated list used by the context validator.
- `DEFAULT_LANGUAGE`: Fallback when no language is supplied.
- `PLACES_API_URL`, `BACKEND_URL`: Targets for outbound integrations (placeholders for later steps).

## Arquitectura Implementada

### Pipeline Completo (Steps 1-3)

```
Usuario: "Buscar restaurantes en Zaragoza"
              ↓
[Step 1] Context Validation ✅
  └─ Valida user_id, session, idioma, ubicación
              ↓
[Step 2a] Intent Classification ✅
  └─ gpt-4o-mini clasifica: SEARCH, RECOMMEND, PLAN, CHITCHAT
              ↓
[Step 2b] LLM Routing ✅
  └─ Selecciona modelo óptimo según intención y complejidad
              ↓
[Step 3] ReAct Agent Execution ✅
  ├─ LangGraph state machine
  ├─ Place Tool (integración con Rust API)
  ├─ Razonamiento multi-step (ReAct pattern)
  └─ Respuesta natural en idioma del usuario
              ↓
Response: JSON con respuesta, lugares, metadata
```

### Componentes

- ✅ **Context Validator**: Validación de sesión, idioma, coordenadas
- ✅ **Intent Classifier**: Clasificación en 4 categorías con reasoning
- ✅ **LLM Router**: Selección dinámica de modelo (5 opciones)
- ✅ **ReAct Agent**: LangGraph agent con pattern ReAct
- ✅ **Place Tool**: Integración con `auphere-places` Rust API
- ✅ **Multi-language**: Prompts en es, en, ca, gl
- ✅ **Structured Logging**: Logs centralizados con structlog

## Next Steps

1. ✅ ~~Context Validation~~
2. ✅ ~~Intent Classification + LLM Routing~~
3. ✅ ~~ReAct Agent + Places Tool~~
4. ⏳ **Plan Generation Tool** – herramienta para crear itinerarios multi-lugar
5. ⏳ **Caching Layer** – Redis cache para responses frecuentes
6. ⏳ **Feedback Loop** – almacenar ratings de respuestas
7. ⏳ **Integration Tests** – suite completa de tests de integración
8. ⏳ **Frontend Integration** – conectar con Next.js + WebSocket streaming
