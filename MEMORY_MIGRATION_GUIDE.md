# Guía de Migración - Sistema de Memoria v2.0

## 🎯 TL;DR

**El nuevo sistema YA ESTÁ ACTIVO** - no necesitas hacer cambios manuales.

- ✅ `MemoryManager` actualizado internamente
- ✅ Agentes funcionan sin cambios
- ✅ API mantiene misma interfaz
- ✅ Plan state ahora en DB (no memoria)
- ✅ Caché se invalida automáticamente

**Solo lee esta guía si necesitas entender el nuevo sistema o hacer optimizaciones.**

---

## 🔍 ¿Qué Cambió?

### Antes (v1) - Sistema Inconsistente

```python
# ❌ PROBLEMA 1: PlanMemoryManager in-memory
from src.agents.plan_memory import PlanMemoryManager

plan_mgr = PlanMemoryManager.get_instance(session_id)
# ⚠️ Se pierde entre workers/reinicios

# ❌ PROBLEMA 2: ConversationMemory con race conditions
memory = ConversationMemory(repository, cache)
context = await memory.get_session_context(session_id)
# ⚠️ A veces no carga historial correctamente

# ❌ PROBLEMA 3: Sin compresión automática
# → Context overflow errors
# → Tokens exceden límite del modelo
```

### Después (v2) - Sistema Robusto

```python
# ✅ SOLUCIÓN: Todo integrado en MemoryManager
memory_manager = MemoryManager(repository, cache)

context = await memory_manager.build_agent_context(
    user_id=user_uuid,
    session_id=session_uuid,
    current_query=query,
    current_language="es"
)

# ✅ Automáticamente:
# - Carga desde DB o cache
# - Comprime si excede límite
# - Extrae plan state desde metadata
# - Formatea para agentes
```

---

## 📋 Checklist de Compatibilidad

### ✅ Tu código es compatible si:

- Usas `MemoryManager.build_agent_context()`
- Pasas `history_messages` a agentes
- Guardas `extra_metadata` en `save_turn()`
- Haces commit después de `save_turn()`

### ⚠️ Necesitas actualizar si:

- Usas `PlanMemoryManager` directamente
- Modificas `ConversationMemory` internamente
- Dependes de estado en memoria (no DB)
- No invalidas caché después de escribir

---

## 🛠️ Casos de Uso Comunes

### Caso 1: Agente Simple con Historial

**Antes:**

```python
from src.agents.memory import ConversationMemory

memory = ConversationMemory(repository, cache)
turns = await memory.get_session_history(session_id)
messages = memory._build_messages_from_turns(turns)

# Pasar a agente...
```

**Después:**

```python
from src.agents.memory import MemoryManager

memory_manager = MemoryManager(repository, cache)
context = await memory_manager.build_agent_context(
    user_id=user_uuid,
    session_id=session_uuid,
    current_query=query,
    current_language="es"
)

# context["history_messages"] ya está listo
messages = [SystemMessage(content=system_prompt)]
messages.extend(context["history_messages"])
messages.append(HumanMessage(content=query))
```

---

### Caso 2: Plan Agent con Estado

**Antes (NO FUNCIONA EN PRODUCCIÓN):**

```python
from src.agents.plan_memory import PlanMemoryManager

plan_mgr = PlanMemoryManager.get_instance(session_id)

# ❌ Estado solo existe en este worker
if plan_mgr.has_asked_about("duration"):
    # Skip asking again
    pass

plan_mgr.update_plan_context(duration="2 hours")
```

**Después (FUNCIONA EN TODOS LOS WORKERS):**

```python
from src.agents.context_builder import PlanContextExtractor, ContextBuilder

# 1. Extraer plan state desde query
extracted = PlanContextExtractor.extract_from_query(query, "es")

# 2. Guardar en DB (metadata)
await conversation_repo.save_turn(
    ...,
    extra_metadata={
        "plan_params": extracted,
        "plan": plan_json
    }
)

# 3. Próximo mensaje - recuperar desde DB
context = await memory_manager.build_agent_context(...)
builder = ContextBuilder()
plan_state = builder.extract_plan_state(context)

# ✅ plan_state contiene info de todos los mensajes previos
if plan_state["duration"]:
    # Ya tenemos duration
    pass
```

---

### Caso 3: Streaming con Memoria

**Antes:**

```python
async def stream_response():
    # Cargar memoria
    memory = ConversationMemory(repository, cache)
    history = await memory.get_session_messages(session_id)

    # Ejecutar agente
    result = await agent.run(query, context={"history_messages": history})

    # Guardar resultado
    await repository.save_turn(...)
    await session.commit()

    # ❌ Caché no se invalida → próximo request usa caché viejo
```

**Después:**

```python
async def stream_response():
    # Cargar memoria (con caché inteligente)
    context = await memory_manager.build_agent_context(
        user_id=user_uuid,
        session_id=session_uuid,
        current_query=query,
        current_language="es"
    )

    # Ejecutar agente
    result = await agent.run(query, context=context)

    # Guardar resultado
    await repository.save_turn(...)
    await session.commit()

    # ✅ Invalidar caché para próximo request
    await memory_manager.invalidate_session_cache(session_uuid)
```

---

### Caso 4: Conversación Larga (>30 mensajes)

**Antes:**

```python
# ❌ Context overflow
turns = await repository.get_session_history(session_id, limit=50)
# → Genera prompt de 10,000 tokens
# → Model error: context length exceeded
```

**Después:**

```python
# ✅ Compresión automática
buffer = ConversationBuffer(
    repository,
    cache,
    max_short_term_turns=10,  # Solo últimos 10 en detalle
    max_tokens=4000            # Límite de tokens
)

context = await buffer.load_context(...)
# → Últimos 10 mensajes + resumen de anteriores
# → Total: ~3,000 tokens (dentro del límite)
```

---

## 🎨 Personalización Avanzada

### Ajustar Ventana de Memoria

```python
# Para chatbot simple (conservar recursos)
memory_manager = MemoryManager(repository, cache)
memory_manager.buffer.max_short_term_turns = 5
memory_manager.buffer.max_tokens = 2000

# Para agente complejo (más contexto)
memory_manager.buffer.max_short_term_turns = 15
memory_manager.buffer.max_tokens = 6000
```

### Custom Context Building

```python
from src.agents.conversation_buffer import ConversationBuffer
from src.agents.context_builder import ContextBuilder

# Cargar contexto
buffer = ConversationBuffer(repository, cache)
conv_context = await buffer.load_context(...)

# Formatear custom
builder = ContextBuilder()
messages = builder.build_messages(
    context=conv_context,
    system_prompt="Tu prompt personalizado..."
)

# Añadir contexto adicional
messages.insert(1, SystemMessage(content="Contexto extra"))
```

### Extraer y Validar Plan State

```python
from src.agents.context_builder import PlanContextExtractor

# 1. Extraer desde query
extracted = PlanContextExtractor.extract_from_query(
    query="Plan para 2 personas en Zaragoza",
    language="es"
)
# → {"num_people": 2, "cities": ["Zaragoza"]}

# 2. Merge con estado existente
plan_state = {"vibe": "romantic"}
merged = PlanContextExtractor.merge_plan_state(plan_state, extracted)
# → {"vibe": "romantic", "num_people": 2, "cities": ["Zaragoza"]}

# 3. Validar completitud
is_ready, missing = PlanContextExtractor.is_plan_ready(merged)
if not is_ready:
    prompt = PlanContextExtractor.format_missing_fields_prompt(missing, "es")
    # → "Para crear el plan perfecto, necesito saber: duración del plan..."
```

---

## 🐛 Debugging Common Issues

### Issue 1: "Agente no recuerda nada"

**Síntomas:**

```
Usuario: Busca bares en Madrid
Agente: Aquí tienes bares...
Usuario: Dame más info del segundo
Agente: ¿De qué lugar hablas?  ← ❌ No recordó
```

**Debug:**

```python
# 1. Verificar que session_id sea consistente
logger.info("session_check", session_id=str(session_uuid))

# 2. Verificar que se guardó en DB
turns = await repository.get_session_history(session_uuid)
assert len(turns) > 0, "No hay turnos guardados"

# 3. Verificar que se carga en contexto
context = await memory_manager.build_agent_context(...)
assert len(context["history_messages"]) > 0, "Historial vacío"
logger.info("history_loaded", count=len(context["history_messages"]))

# 4. Verificar que agente recibe el contexto
# En agent.run(), loggear:
self.logger.info("agent_received_history", count=len(history_messages))
```

**Solución:**

```python
# Asegurar commit después de save_turn
await conversation_repo.save_turn(...)
await session.commit()  # ← CRÍTICO

# Verificar session_id consistente
# En frontend: mantener session_id durante toda la conversación
```

---

### Issue 2: "Token limit exceeded"

**Síntomas:**

```
openai.error.InvalidRequestError:
This model's maximum context length is 8192 tokens,
however you requested 10000 tokens.
```

**Debug:**

```python
# Verificar tokens estimados
context = await memory_manager.build_agent_context(...)
logger.info("token_estimate",
    estimated=context["estimated_tokens"],
    remaining=context["tokens_remaining"]
)

# Si estimated > 8000:
# → Reducir ventana o aumentar compresión
```

**Solución:**

```python
# Opción 1: Reducir ventana
memory_manager.buffer.max_short_term_turns = 5

# Opción 2: Reducir límite de tokens (forzar compresión)
memory_manager.buffer.max_tokens = 3000

# Opción 3: Usar modelo con contexto más grande
llm = ChatOpenAI(model="gpt-4-turbo")  # 128k context
```

---

### Issue 3: "Plan context se pierde"

**Síntomas:**

```
Usuario: Quiero plan para 2 personas
Agente: Genial, ¿cuántas personas?  ← ❌ Ya dijo 2
```

**Debug:**

```python
# 1. Verificar que se extrajo correctamente
from src.agents.context_builder import PlanContextExtractor
extracted = PlanContextExtractor.extract_from_query(query, "es")
logger.info("plan_extracted", params=extracted)

# 2. Verificar que se guardó en metadata
turn = await repository.get_turn_by_id(turn_id)
logger.info("turn_metadata", metadata=turn.extra_metadata)
assert "plan_params" in turn.extra_metadata

# 3. Verificar que se recupera
builder = ContextBuilder()
plan_state = builder.extract_plan_state(conv_context)
logger.info("plan_state_recovered", state=plan_state)
```

**Solución:**

```python
# En streaming_routes.py, asegurar:
extra_metadata = {"plan": agent_result.get("plan")}

if intent_result.intention.value == "PLAN":
    from src.agents.context_builder import PlanContextExtractor
    extracted = PlanContextExtractor.extract_from_query(query, language)
    if extracted:
        extra_metadata["plan_params"] = extracted  # ← Guardar params

await conversation_repo.save_turn(..., extra_metadata=extra_metadata)
```

---

## 📊 Monitoring en Producción

### Métricas Clave

```python
# En cada request, loggear:
logger.info("memory_metrics",
    session_id=str(session_id),
    cache_hit=cache_hit,  # True/False
    estimated_tokens=context["estimated_tokens"],
    history_size=len(context["history_messages"]),
    compression_needed=compression_triggered,
    db_query_time_ms=db_time,
)
```

### Alertas Recomendadas

```yaml
# Prometheus/Grafana
- alert: MemoryCacheMissRateHigh
  expr: memory_cache_miss_rate > 0.5
  for: 10m
  annotations:
    summary: "Cache miss rate muy alto (>50%)"
    action: "Aumentar TTL de cache o revisar invalidación"

- alert: MemoryTokenLimitExceeded
  expr: memory_estimated_tokens > 8000
  annotations:
    summary: "Tokens exceden límite del modelo"
    action: "Reducir max_short_term_turns o mejorar compresión"

- alert: MemoryDBSlowQuery
  expr: memory_db_query_time_ms > 100
  for: 5m
  annotations:
    summary: "Queries de DB muy lentas (>100ms)"
    action: "Revisar índices o conexión a DB"
```

---

## ✅ Testing Checklist

### Test 1: Memoria Básica

```bash
# Terminal 1: Iniciar agente
python -m uvicorn api.main:app

# Terminal 2: Test
curl -X POST http://localhost:8000/agent/query/stream \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Busca bares en Madrid",
    "user_id": "test-user",
    "session_id": "test-session-1"
  }'

# Siguiente request con mismo session_id
curl -X POST http://localhost:8000/agent/query/stream \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Dame más info del segundo",
    "user_id": "test-user",
    "session_id": "test-session-1"
  }'

# ✅ Debe recordar los bares del mensaje anterior
```

### Test 2: Plan State Persistence

```bash
# Request 1
curl ... -d '{"query": "Plan para 2 personas", "session_id": "test-plan"}'

# Request 2 (no debe volver a preguntar personas)
curl ... -d '{"query": "En Zaragoza", "session_id": "test-plan"}'

# Request 3
curl ... -d '{"query": "De 2 horas", "session_id": "test-plan"}'

# ✅ Debe generar plan con: 2 personas, Zaragoza, 2 horas
```

### Test 3: Compresión Automática

```python
# Generar 20 mensajes largos
import asyncio

async def test_compression():
    for i in range(20):
        await agent.query(
            query=f"Mensaje largo número {i}: " + "x" * 500,
            session_id="test-compression"
        )

    # Verificar logs
    # ✅ Debe ver "context_compressed" después de ~10 mensajes
    # ✅ estimated_tokens debe mantenerse < 4000
```

---

## 🎓 Best Practices Checklist

- [ ] Siempre usar `MemoryManager.build_agent_context()` (no direct repository access)
- [ ] Commit inmediatamente después de `save_turn()`
- [ ] Invalidar caché con `memory_manager.invalidate_session_cache()` después de escribir
- [ ] Mantener `session_id` consistente durante conversación
- [ ] Guardar plan params en `extra_metadata["plan_params"]`
- [ ] Monitorear `estimated_tokens` en logs
- [ ] Configurar Redis en producción (no solo memoria)
- [ ] Testear con conversaciones largas (>20 mensajes)

---

## 📞 Soporte

Si encuentras problemas:

1. **Revisar logs** en `agent.log` - buscar errores de memoria
2. **Verificar DB** - ¿los turns se están guardando?
3. **Verificar Redis** - ¿está corriendo? ¿hay conexión?
4. **Revisar session_id** - ¿es consistente entre requests?
5. **Leer MEMORY_SYSTEM.md** - documentación completa

---

**Última actualización**: Diciembre 2024  
**Versión**: 2.0
