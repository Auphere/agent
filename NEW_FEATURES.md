# 🚀 Auphere Agent - Plan-and-Execute System

## 🎯 New Features

### Advanced Plan-and-Execute Agent

El agente ahora utiliza un sistema avanzado de Plan-and-Execute usando LangGraph que:

1. **Planifica** - Crea un plan multi-paso para responder la consulta del usuario
2. **Ejecuta** - Ejecuta cada paso usando las herramientas apropiadas
3. **Replanifica** - Adapta el plan basado en resultados intermedios
4. **Sintetiza** - Combina toda la información en una respuesta comprehensiva

Similar a cómo funcionan Perplexity, OpenAI y Claude.

### Nuevas Fuentes de Datos

#### Foursquare Places API (FSQ API)

- 🌍 **105M+ POIs globales**
- ⭐ Ratings y popularidad
- 📝 Tips y reseñas de usuarios
- 📸 Fotos de alta calidad
- 🕐 Horarios de apertura
- 👥 Datos de crowdedness (cuánta gente hay ahora)

#### Apify Web Scraping

- 📸 **Instagram**: Posts recientes, likes, comentarios, hashtags
- 🎵 **TikTok**: Videos virales, views, shares, trending content
- ⭐ **TripAdvisor**: Reseñas detalladas, ratings, feedback de usuarios

## 📦 Instalación

### 1. Instalar Dependencias

```bash
cd auphere-agent
pip install -r requirements.txt
```

### 2. Configurar API Keys

Crea un archivo `.env` en el directorio `auphere-agent/` con:

```env
# LLM APIs (REQUIRED)
OPENAI_API_KEY=sk-your_key_here

# Foursquare API (NEW)
FOURSQUARE_API_KEY=your_foursquare_key_here

# Apify API (NEW)
APIFY_API_KEY=your_apify_key_here

# Otras configuraciones
DATABASE_URL=postgresql+asyncpg://auphere:password@localhost:5432/auphere-agent
REDIS_URL=redis://localhost:6379/0
PLACES_API_URL=http://localhost:8002
```

### 3. Obtener API Keys

#### Foursquare API

1. Ve a [Foursquare Developers](https://foursquare.com/developers/)
2. Crea una cuenta o inicia sesión
3. Crea un nuevo proyecto
4. Copia tu API key
5. Pega en `.env` como `FOURSQUARE_API_KEY`

**Plan Gratuito**: 50,000 llamadas/mes

#### Apify API

1. Ve a [Apify](https://apify.com/)
2. Crea una cuenta
3. Ve a Settings > Integrations
4. Copia tu API token
5. Pega en `.env` como `APIFY_API_KEY`

**Plan Gratuito**: $5 de crédito mensual

## 🚀 Ejecutar el Agente

```bash
# Desarrollo
python -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8001

# O con el entry point
python api/main.py
```

## 📊 Nuevas Herramientas Disponibles

### Search Tools

- `search_foursquare_places` - Buscar en 105M+ POIs
- `get_foursquare_place_enrichment` - Detalles completos de un lugar

### Social Media Tools

- `scrape_instagram_place` - Posts de Instagram
- `scrape_tiktok_place` - Videos de TikTok
- `scrape_tripadvisor_reviews` - Reseñas de TripAdvisor
- `get_social_media_summary` - Resumen de todas las redes

## 🧪 Testing

### Test Manual con Streamlit

```bash
streamlit run streamlit_app.py
```

### Test del Nuevo Agente

```python
from src.agents.specialized.plan_and_execute_agent import PlanAndExecuteAgent

agent = PlanAndExecuteAgent()

result = await agent.run(
    query="Planifica una noche perfecta en Zaragoza para una pareja romántica",
    language="es",
    context={
        "city": "Zaragoza",
        "preferences": ["romantic", "cozy", "good_food"]
    }
)

print(result["response_text"])
print(f"Lugares encontrados: {len(result['places'])}")
```

### Test de Foursquare

```python
from src.tools.search.foursquare_v2 import search_foursquare_places

result = await search_foursquare_places(
    query="romantic restaurant",
    latitude=41.6488,
    longitude=-0.8891,
    radius=3000,
    limit=10
)

print(result)
```

### Test de Apify

```python
from src.tools.search.apify_enrichment import scrape_instagram_place

result = await scrape_instagram_place(
    place_name="Cafe Central",
    location="Zaragoza",
    max_posts=10
)

print(result)
```

## 📝 Arquitectura del Plan-and-Execute Agent

```
User Query
    ↓
[PLANNER] (GPT-4o)
    ↓
Create multi-step plan
    ↓
[EXECUTOR] (GPT-4o-mini) ←→ [TOOLS]
    ↓                          ├─ Foursquare API
Execute each step              ├─ Instagram Scraping
    ↓                          ├─ TikTok Scraping
Check if done                  ├─ TripAdvisor Scraping
    ↓                          ├─ Google Places
[REPLANNER]                    └─ Local DB
    ↓
Replan if needed
    ↓
[SYNTHESIZER] (GPT-4o)
    ↓
Comprehensive response
```

## 🔧 Troubleshooting

### Error: Foursquare API key not configured

```bash
# Verifica que la key esté en .env
echo $FOURSQUARE_API_KEY

# Si no está, añade:
export FOURSQUARE_API_KEY=your_key_here
```

### Error: Apify API key not configured

```bash
# Verifica que la key esté en .env
echo $APIFY_API_KEY

# Si no está, añade:
export APIFY_API_KEY=your_key_here
```

### Error: langgraph-checkpoint not found

```bash
pip install langgraph-checkpoint==0.1.0
```

### Apify scraping timeout

- Los scrapers de Apify pueden tardar 60-120 segundos
- Es normal, están extrayendo datos en tiempo real
- Ajusta el timeout si es necesario en el código

## 📈 Mejoras vs Versión Anterior

| Feature                 | Anterior     | Nuevo                     |
| ----------------------- | ------------ | ------------------------- |
| POIs disponibles        | ~1K (local)  | 105M+ (Foursquare)        |
| Datos de redes sociales | ❌ No        | ✅ Instagram, TikTok      |
| Reseñas detalladas      | ❌ Limitadas | ✅ TripAdvisor completo   |
| Planning strategy       | ReAct simple | Plan-and-Execute avanzado |
| Calidad de respuestas   | Buena        | Excelente                 |
| Fuentes de datos        | 1-2          | 5+                        |
| Tiempo de respuesta     | ~5s          | ~15-30s (más completo)    |

## 🎯 Próximos Pasos

1. ✅ Plan-and-Execute agent con LangGraph
2. ✅ Integración Foursquare API
3. ✅ Integración Apify (Instagram, TikTok, TripAdvisor)
4. ✅ Actualizar supervisor_agent
5. ✅ Mejorar SSE streaming
6. 🔄 Actualizar backend para consumir nuevo agente
7. 🔄 Actualizar frontend para mostrar datos enriquecidos

## 📚 Recursos

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [Foursquare Places API](https://location.foursquare.com/developer/reference/places-api-overview)
- [Apify Documentation](https://docs.apify.com/)
- [Plan-and-Execute Pattern](https://langchain-ai.github.io/langgraph/tutorials/plan-and-execute/plan-and-execute/)

## 💡 Tips de Uso

### Para Mejores Resultados

1. **Sé específico** - "restaurante romántico italiano en Zaragoza" > "restaurante"
2. **Incluye contexto** - Menciona ocasión, presupuesto, preferencias
3. **Modo Plan** - Usa el modo Plan para itinerarios completos
4. **Paciencia** - El nuevo agente toma 15-30s pero da resultados mucho mejores

### Ejemplos de Queries Efectivas

```
✅ "Planifica una noche romántica en Zaragoza con cena y cócteles"
✅ "Busca bares de tapas modernos cerca del centro con buenas reseñas"
✅ "Recomienda cafeterías con wifi para trabajar en Zaragoza"

❌ "lugares"
❌ "algo bueno"
❌ "donde ir"
```

---

**Last Updated**: December 21, 2024
**Version**: 2.0.0 (Plan-and-Execute)
