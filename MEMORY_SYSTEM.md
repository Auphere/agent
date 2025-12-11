# Sistema de Memoria de Conversación - Arquitectura v2.0

## 🎯 Resumen Ejecutivo

Este documento describe el nuevo sistema de memoria de conversación diseñado para resolver el problema de "memoria inconsistente" que afectaba al agente. El sistema anterior (v1) tenía problemas porque:

1. **PlanMemoryManager** usaba singleton en memoria → se perdía entre workers/reinicios
2. **ConversationMemory** tenía race conditions y caché inconsistente
3. **No había estrategia clara** de ventana de contexto y compresión

El nuevo sistema (v2) es **production-grade**, inspirado en Cursor, Perplexity y OpenAI, con:

- ✅ Persistencia en base de datos (PostgreSQL)
- ✅ Caché inteligente con Redis
- ✅ Ventana deslizante con compresión automática
- ✅ 3 niveles de memoria (working, short-term, long-term)
- ✅ Compatible con múltiples workers/procesos

---

## 🏗️ Arquitectura del Sistema

### Componentes Principales

```
┌─────────────────────────────────────────────────────────────┐
│                    Agent Request Handler                     │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                     MemoryManager                            │
│  - Orquestador principal                                     │
│  - Interfaz de alto nivel                                    │
└──────┬──────────────────────────────────────┬───────────────┘
       │                                       │
       ▼                                       ▼
┌─────────────────────┐            ┌─────────────────────────┐
│ ConversationBuffer  │            │   ContextBuilder        │
│                     │            │                         │
│ - Carga contexto    │            │ - Construye prompts     │
│ - Gestiona ventana  │            │ - Formatea mensajes     │
│ - Comprime memoria  │            │ - Extrae estado plan    │
└──────┬──────────────┘            └─────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│              Persistence Layer                               │
│  ┌──────────────┐      ┌──────────────┐                    │
│  │  PostgreSQL  │      │    Redis     │                    │
│  │  (Source of  │      │  (Fast       │                    │
│  │   Truth)     │      │   Cache)     │                    │
│  └──────────────┘      └──────────────┘                    │
└─────────────────────────────────────────────────────────────┘
```

---

## 📦 Módulos y Responsabilidades

### 1. `conversation_buffer.py`

**Clase Principal: `ConversationBuffer`**

Responsable de cargar y gestionar el contexto de conversación desde la base de datos y caché.

**Características:**

- ✅ Carga contexto con ventana deslizante configurable
- ✅ Compresión automática cuando se excede el presupuesto de tokens
- ✅ Caché en Redis para respuestas rápidas (5 min TTL)
- ✅ Extrae lugares mencionados para resolución de referencias
- ✅ Genera resúmenes de conversaciones largas

**Configuración por Defecto:**

```python
DEFAULT_SHORT_TERM_TURNS = 10   # Últimos 10 turnos en detalle completo
DEFAULT_LONG_TERM_TURNS = 50    # Hasta 50 turnos para resumen
DEFAULT_MAX_TOKENS = 4000       # Presupuesto máximo de tokens
COMPRESSION_THRESHOLD = 0.8     # Comprime al 80% del presupuesto
```

**Métodos Clave:**

- `load_context()`: Punto de entrada principal - carga todo el contexto
- `_build_from_database()`: Construye contexto desde DB (slow path)
- `_compress_context()`: Comprime contexto cuando excede límite
- `invalidate_cache()`: Invalida caché después de nuevo mensaje

**Ejemplo de Uso:**

```python
buffer = ConversationBuffer(repository=repo, cache=cache)

context = await buffer.load_context(
    user_id=user_uuid,
    session_id=session_uuid,
    current_query="Busca bares cerca de Sol",
    current_language="es"
)
# context.recent_messages contiene los últimos mensajes
# context.previous_places contiene lugares mencionados
# context.session_summary contiene resumen de conversación larga
```

---

### 2. `context_builder.py`

**Clase Principal: `ContextBuilder`**

Responsable de construir prompts optimizados para LLMs a partir del contexto cargado.

**Características:**

- ✅ Formatea mensajes para LangChain (SystemMessage, HumanMessage, AIMessage)
- ✅ Inyecta referencias a lugares para resolución de ambigüedades
- ✅ Mejora system prompts con contexto de sesión
- ✅ Genera tanto formato de mensajes como strings

**Métodos Clave:**

- `build_messages()`: Construye lista de BaseMessage para agentes
- `build_string_context()`: Construye string de contexto (legacy)
- `build_agent_context_dict()`: Construye dict completo para agentes
- `extract_plan_state()`: Extrae estado de plan desde metadata de DB

**Ejemplo de Uso:**

```python
builder = ContextBuilder()

messages = builder.build_messages(
    context=conv_context,
    system_prompt="Eres un asistente de viajes..."
)
# messages = [SystemMessage, ...history..., HumanMessage]

agent_context = builder.build_agent_context_dict(
    context=conv_context,
    validated_context=user_location_context
)
# Contiene: history_messages, previous_places, session_summary, etc.
```

**Clase Auxiliar: `PlanContextExtractor`**

Reemplaza el antiguo `PlanMemoryManager` con un enfoque basado en DB.

- `extract_from_query()`: Extrae parámetros de plan desde query con heurísticas
- `merge_plan_state()`: Combina nuevo estado con existente
- `is_plan_ready()`: Verifica si plan tiene todos los campos requeridos
- `format_missing_fields_prompt()`: Genera pregunta amigable para campos faltantes

---

### 3. `memory.py` (Actualizado)

**Clase Principal: `MemoryManager`**

Interfaz de alto nivel que orquesta `ConversationBuffer` y `ContextBuilder`.

**Método Principal:**

```python
async def build_agent_context(
    user_id: UUID,
    session_id: UUID,
    current_query: str,
    include_history: bool = True,
    include_patterns: bool = False,
    current_language: str = "es",
) -> dict
```

**Retorna:**

```python
{
    "user_id": "...",
    "session_id": "...",
    "current_query": "...",
    "language": "es",

    # Memoria (nuevo sistema)
    "history_messages": [HumanMessage(...), AIMessage(...)],
    "conversation_history": "Usuario: ... Asistente: ...",
    "previous_places": [{name: "...", _turn_number: 2}],

    # Resumen de sesión
    "session_summary": "Conversación previa: 15 mensajes...",
    "total_turns": 15,

    # Token budget
    "estimated_tokens": 1200,
    "tokens_remaining": 2800,

    # Opcional
    "user_patterns": {...},
    "validated_context": {...}
}
```

---

## 🔄 Flujo de Ejecución

### Request de Usuario → Respuesta del Agente

```
1. Usuario envía mensaje
   ↓
2. API Route recibe request
   ↓
3. MemoryManager.build_agent_context()
   ↓
4. ConversationBuffer.load_context()
   - Intenta caché (Redis) → HIT? → Retorna
   - MISS? → Consulta DB
   - Construye ConversationContext
   - Comprime si necesario
   - Guarda en caché
   ↓
5. ContextBuilder.build_agent_context_dict()
   - Formatea mensajes
   - Inyecta referencias
   - Prepara contexto
   ↓
6. Supervisor/Agent ejecuta con contexto
   ↓
7. Guarda respuesta en DB
   ↓
8. MemoryManager.invalidate_session_cache()
   - Invalida caché de Redis
   ↓
9. Siguiente mensaje usa DB actualizado
```

---

## 🎨 Niveles de Memoria

### Level 1: Working Memory (Turno Actual)

- **Qué es**: Query actual del usuario
- **Duración**: Solo el turno actual
- **Propósito**: Contexto inmediato

### Level 2: Short-term Memory (Reciente)

- **Qué es**: Últimos N turnos (default: 10)
- **Duración**: Hasta exceder presupuesto de tokens
- **Almacenamiento**: DB + Redis cache (5 min)
- **Propósito**: Mantener coherencia conversacional

### Level 3: Long-term Memory (Histórico)

- **Qué es**: Resumen de turnos anteriores
- **Duración**: Hasta 50 turnos históricos
- **Almacenamiento**: DB (generado on-demand)
- **Propósito**: Personalización y contexto de sesión larga

---

## 🔧 Configuración y Optimización

### Variables de Entorno

```bash
# Redis (recomendado para producción)
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=

# PostgreSQL
DATABASE_URL=postgresql://...
```

### Tunning de Parámetros

**Para conversaciones cortas (< 10 mensajes):**

```python
ConversationBuffer(
    max_short_term_turns=5,
    max_long_term_turns=20,
    max_tokens=2000
)
```

**Para conversaciones largas (> 30 mensajes):**

```python
ConversationBuffer(
    max_short_term_turns=15,
    max_long_term_turns=100,
    max_tokens=6000
)
```

**Para ambientes con workers limitados:**

- Aumentar CACHE_TTL_SHORT a 600 (10 min)
- Reducir max_short_term_turns a 5
- Habilitar compresión agresiva

---

## 🚀 Migración desde Sistema Antiguo

### Paso 1: Actualizar Dependencias

El sistema ya está actualizado en:

- ✅ `memory.py` - MemoryManager usa ConversationBuffer internamente
- ✅ `react_agent.py` - Ya no usa PlanMemoryManager
- ✅ `streaming_routes.py` - Pasa `current_language` y invalida caché
- ✅ Plan state se guarda en `ConversationTurn.extra_metadata`

### Paso 2: No Requiere Cambios en API

El sistema mantiene **backward compatibility**:

- La interfaz `MemoryManager.build_agent_context()` es la misma
- El formato de retorno es compatible (añade campos nuevos)
- Los agentes existentes funcionan sin cambios

### Paso 3: Deprecated Modules

**NO USAR:**

- ❌ `PlanMemoryManager` - Reemplazado por `PlanContextExtractor`
- ❌ `ConversationMemory` directamente - Usar `ConversationBuffer`

**USAR:**

- ✅ `MemoryManager.build_agent_context()` - Interfaz principal
- ✅ `ConversationBuffer` - Para casos de uso avanzados
- ✅ `ContextBuilder` - Para formateo personalizado de prompts

---

## 🧪 Testing y Validación

### Test de Memoria Persistente

```python
# 1. Enviar mensaje
response = await agent.query("Busca bares en Madrid")

# 2. Enviar seguimiento (mismo session_id)
response = await agent.query("Dame más info del segundo")
# ✅ Debe recordar los bares del mensaje anterior

# 3. Reiniciar workers
# 4. Enviar otro seguimiento
response = await agent.query("Y el primero?")
# ✅ Debe seguir recordando (desde DB, no memoria)
```

### Test de Compresión

```python
# Enviar 20 mensajes largos
for i in range(20):
    await agent.query(f"Mensaje largo número {i}...")

# Verificar logs
# ✅ Debe ver "context_compressed" en logs
# ✅ Token count debe mantenerse < max_tokens
```

### Test de Cache Invalidation

```python
# 1. Enviar mensaje
await agent.query("Hola")

# 2. Verificar caché (debe existir)
cache_key = f"conversation_context:{session_id}"
cached = await redis.get(cache_key)
# ✅ cached != None

# 3. Enviar otro mensaje
await agent.query("Cómo estás?")

# 4. Verificar caché invalidado
# ✅ Sistema debe haber invalidado y recreado caché
```

---

## 📊 Monitoreo y Debugging

### Logs Importantes

**Carga de contexto exitosa:**

```
INFO: context_loaded_from_database
  session_id=...
  recent_turns=10
  estimated_tokens=1500
```

**Cache hit:**

```
DEBUG: context_loaded_from_cache
  session_id=...
```

**Compresión activada:**

```
INFO: context_needs_compression
  estimated_tokens=3500
  max_tokens=4000
```

**Memoria inválida (problema):**

```
WARNING: conversation_buffer_load_failed
ERROR: database_connection_check_failed
```

### Métricas a Monitorear

1. **Cache Hit Rate**: Debe ser > 60% en producción
2. **Compression Frequency**: < 10% de requests
3. **Average Tokens**: Debe mantenerse estable
4. **DB Query Time**: < 50ms para get_session_history

---

## 🐛 Troubleshooting

### Problema: "El agente no recuerda conversaciones anteriores"

**Causa posible:**

1. Session_id cambia entre requests
2. DB commits no se están ejecutando
3. Cache invalidation no funciona

**Solución:**

```python
# Verificar session_id consistente
logger.info("session_id", session_id=str(session_id))

# Verificar commit después de save_turn
await conversation_repo.save_turn(...)
await session.commit()  # ← CRÍTICO

# Verificar invalidación de caché
await memory_manager.invalidate_session_cache(session_id)
```

### Problema: "Memory excede token limit"

**Causa posible:**

1. max_tokens muy bajo
2. Compresión deshabilitada
3. Mensajes extremadamente largos

**Solución:**

```python
# Aumentar presupuesto
ConversationBuffer(max_tokens=6000)

# Reducir ventana
ConversationBuffer(max_short_term_turns=5)

# Verificar logs de compresión
# Debe ver "context_compressed" cuando se acerca al límite
```

### Problema: "Plan context se pierde"

**Causa posible:**

1. Extra_metadata no se guarda correctamente
2. PlanContextExtractor no extrae campos

**Solución:**

```python
# Verificar metadata en DB
turn = await repo.get_turn_by_id(turn_id)
assert turn.extra_metadata is not None
assert "plan_params" in turn.extra_metadata

# Mejorar extracción
from src.agents.context_builder import PlanContextExtractor
extracted = PlanContextExtractor.extract_from_query(query, "es")
# Verificar que extrae correctamente
```

---

## 🎯 Best Practices

### ✅ DO

1. **Siempre usar MemoryManager** como interfaz principal
2. **Commit inmediatamente** después de save_turn
3. **Invalidar caché** después de guardar nuevo mensaje
4. **Usar session_id consistente** a lo largo de la conversación
5. **Monitorear token usage** en logs
6. **Guardar plan state** en extra_metadata

### ❌ DON'T

1. **No usar PlanMemoryManager** (deprecated)
2. **No modificar ConversationBuffer** sin entender flujo completo
3. **No saltarse cache invalidation**
4. **No asumir que caché está actualizado** siempre
5. **No usar memoria in-process** para estado compartido
6. **No exceder max_tokens** sin comprimir

---

## 📚 Referencias

### Inspiración

- **Cursor**: Sistema de memoria con ventana deslizante
- **Perplexity**: Compresión inteligente de contexto
- **OpenAI Assistants**: Threads + mensajes persistentes
- **LangChain**: MessageHistory + ConversationBuffer

### Documentación Relacionada

- `src/agents/conversation_buffer.py` - Implementación completa
- `src/agents/context_builder.py` - Formateo de prompts
- `src/database/repositories.py` - Persistencia de turnos
- `api/streaming_routes.py` - Integración en API

---

## 🔮 Roadmap Futuro

### Mejoras Planificadas

1. **Summarization con LLM** (en lugar de rule-based)

   - Usar GPT-4 para resumir conversaciones largas
   - Mejorar calidad de long-term memory

2. **Semantic Compression**

   - Comprimir por similaridad semántica
   - Mantener información más relevante

3. **User Memory Profiles**

   - Memoria a largo plazo por usuario (no solo sesión)
   - Preferencias, lugares favoritos, patrones

4. **Hierarchical Summarization**

   - Resúmenes por niveles (hora → día → semana)
   - Para usuarios con mucha historia

5. **Memory Pruning Inteligente**
   - Eliminar información redundante automáticamente
   - Mantener solo lo relevante

---

**Última actualización**: Diciembre 2024  
**Versión**: 2.0  
**Autor**: Sistema de IA
