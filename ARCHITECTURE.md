# Auphere Agent Architecture

## 🎯 Role: AI Agent & Tool Orchestration

### ✅ **Core Responsibilities**

1. **Intent Classification**

   - Detect user intent (SEARCH, PLAN, RECOMMEND, CHITCHAT)
   - Emotion detection
   - Complexity assessment

2. **Agent Execution**

   - SupervisorAgent: Routes to specialized agents
   - ReAct Pattern: Reasoning + Acting cycles
   - Tool orchestration

3. **Memory Management**

   - Conversation history
   - User preferences
   - Plan memory

4. **LLM Routing**
   - Select appropriate model (GPT-4, GPT-4o-mini, Claude)
   - Cost optimization
   - Performance balancing

### 🛠️ **Tool Architecture**

#### Correct Tool Usage ✅

```
src/tools/
├── place_tool.py          ✅ Calls auphere-places microservice
├── plan_tool.py           ✅ Planning logic (agent domain)
├── context_tool.py        ✅ Context retrieval (agent domain)
├── database/
│   ├── local_db.py       ✅ Calls auphere-places
│   ├── preferences.py    ✅ User preferences (agent domain)
│   └── metrics.py        ✅ Analytics (agent domain)
├── processing/
│   ├── scoring.py        ✅ Recommendation scoring (agent domain)
│   ├── routing.py        ✅ Route calculation (agent domain)
│   └── itinerary.py      ✅ Itinerary generation (agent domain)
└── search/
    ├── web_search.py     ✅ DuckDuckGo for context (agent domain)
    ├── weather.py        ✅ Weather context (agent domain)
    ├── foursquare.py     ⚠️  External API (consider consolidating)
    ├── yelp_fusion.py    ⚠️  External API (consider consolidating)
    └── google_places.py  ❌ REMOVED - Was duplicating auphere-places
```

### ❌ **What Should NOT Be in Agent**

1. **Direct place data storage** - Use auphere-places
2. **Direct Google Places API calls** - Use auphere-places
3. **Place enrichment logic** - Use auphere-places
4. **CRUD operations on places** - Use auphere-places

### ✅ **What SHOULD Be in Agent**

1. **AI/LLM interactions**
2. **Tool orchestration**
3. **Conversation management**
4. **User preferences**
5. **Recommendation algorithms**
6. **Planning logic**

---

## 🏗️ Agent Flow

```
User Query
    │
    ▼
┌──────────────────┐
│ Intent Classifier│  ← Detect: SEARCH, PLAN, RECOMMEND
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ SupervisorAgent  │  ← Route to specialized agent
└────────┬─────────┘
         │
         ├─────────┬─────────┬──────────┐
         ▼         ▼         ▼          ▼
    ┌────────┐ ┌──────┐ ┌─────────┐ ┌─────────┐
    │ Search │ │ Plan │ │Recommend│ │ ReAct   │
    │ Agent  │ │Agent │ │ Agent   │ │(Fallback│
    └────┬───┘ └───┬──┘ └────┬────┘ └────┬────┘
         │         │         │           │
         └─────────┴─────────┴───────────┘
                      │
                      ▼
              ┌──────────────┐
              │  Tool Calls  │
              └──────┬───────┘
                     │
         ┌───────────┼───────────┐
         ▼           ▼           ▼
  ┌──────────┐ ┌──────────┐ ┌──────────┐
  │  Place   │ │   Web    │ │  Plan    │
  │  Tool    │ │  Search  │ │  Tool    │
  └─────┬────┘ └─────┬────┘ └────┬─────┘
        │            │            │
        ▼            │            │
  ┌──────────────┐   │            │
  │ auphere-     │   │            │
  │ places       │   │            │
  └──────────────┘   │            │
                     ▼            ▼
              External APIs   Agent Logic
```

---

## 🔌 Integration Points

### With auphere-places (Rust)

- **Endpoint**: `http://localhost:8002`
- **Used by**: `place_tool.py`, `local_db.py`
- **Purpose**: Get place data, search, enrichment
- **Pattern**: Tool → HTTP → auphere-places

### With auphere-backend (Python)

- **Endpoint**: N/A (backend calls agent, not vice versa)
- **Pattern**: backend → agent (for chat)

### External APIs (Considered for Consolidation)

- **Google Places**: ❌ Removed (use auphere-places)
- **DuckDuckGo**: ✅ Keep (for general web context)
- **Weather API**: ✅ Keep (for context)
- **Foursquare**: ⚠️ Consider moving to auphere-places
- **Yelp**: ⚠️ Consider moving to auphere-places

---

## 🔄 Recent Changes (Refactoring)

### ✅ Completed

1. **Removed `google_places.py`** ❌

   - Was duplicating auphere-places functionality
   - All place searches now go through `place_tool.py`

2. **Cleaned tool registry**
   - Removed references to duplicate tools
   - Documented correct usage patterns

### ⚠️ To Consider

1. **Consolidate external API calls**

   - Move Foursquare/Yelp to auphere-places?
   - Or keep for AI context enrichment?

2. **Add circuit breakers**
   - For calls to auphere-places
   - For external APIs

---

## 📊 Specialized Agents

### SearchAgent

- **Purpose**: Fast, focused place searches
- **Tools**: place_tool, web_search
- **Model**: GPT-4o-mini (fast & cheap)
- **Use case**: "busca bares en zaragoza"

### PlanAgent

- **Purpose**: Complex itinerary planning
- **Tools**: place_tool, plan_tool, routing, weather
- **Model**: GPT-4 (smart & thorough)
- **Use case**: "planifica mi noche perfecta"

### RecommendAgent

- **Purpose**: Personalized recommendations
- **Tools**: place_tool, preferences, scoring
- **Model**: GPT-4o (balanced)
- **Use case**: "recomiéndame algo romántico"

### ReactAgent (Fallback)

- **Purpose**: Handle complex/unknown intents
- **Tools**: All available
- **Model**: GPT-4
- **Use case**: Edge cases

---

## 🗄️ Data Storage

### PostgreSQL (via src/database/)

- **Tables**: chats, conversations, metrics
- **Purpose**: Agent-specific data only
- **What's stored**:
  - ✅ Chat sessions
  - ✅ Conversation history
  - ✅ Agent metrics
  - ❌ Places data (in auphere-places)

### Redis (via src/utils/cache_manager.py)

- **Purpose**: Caching & performance
- **What's cached**:
  - Intent classifications
  - LLM responses (when appropriate)
  - Tool call results (short TTL)

---

## 🚀 Running the Agent

### Development

```bash
cd auphere-agent
source .venv/bin/activate
uvicorn api.main:app --reload --port 8001
```

### Environment Variables

```env
# LLM APIs
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# Database
DATABASE_URL=postgresql://...

# Redis
REDIS_ENABLED=true
REDIS_HOST=localhost
REDIS_PORT=6379

# Microservices
PLACES_SERVICE_URL=http://localhost:8002

# REMOVED: No longer needed
# GOOGLE_PLACES_API_KEY=AIza...  ❌ (use auphere-places)
```

---

## 📝 Migration Notes

### From google_places.py to place_tool.py

**Before** (WRONG ❌):

```python
from src.tools.search.google_places import search_google_places_tool

result = await search_google_places_tool.ainvoke({
    "query": "bares romanticos",
    "location": "Zaragoza"
})
```

**After** (CORRECT ✅):

```python
from src.tools.place_tool import search_your_db_tool

result = await search_your_db_tool.ainvoke({
    "query": "bares romanticos",
    "city": "Zaragoza"
})
```

---

## 📚 Related Documentation

- `/api/routes.py` - Main API endpoints
- `/api/streaming_routes.py` - Streaming SSE endpoints
- `/src/agents/supervisor_agent.py` - Agent routing logic
- `/src/tools/TOOLS_README.md` - Tool documentation
- `auphere-backend/ARCHITECTURE.md` - Backend architecture
- `auphere-places/README.md` - Places service

---

**Last Updated**: Dec 10, 2024  
**Status**: Refactored - Removed Duplications  
**Next Review**: After consolidating external APIs
