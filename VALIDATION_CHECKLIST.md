# ✅ Validation Checklist - Auphere Agent Enhancements

## Pre-Deployment Validation

Use this checklist to verify that all enhancements are working correctly before deploying to production.

---

## 1️⃣ File Structure Validation

### New Files Created ✨
- [ ] `src/classifiers/emotion_detector.py` exists and is readable
- [ ] `src/agents/plan_memory.py` exists and is readable
- [ ] `pages/04_plan_flow.py` exists and is readable
- [ ] `tests/test_plan_flow.py` exists and is readable
- [ ] `AGENT_IMPROVEMENTS.md` exists and is complete
- [ ] `IMPLEMENTATION_SUMMARY.md` exists and is complete
- [ ] `QUICK_START.md` exists and is complete
- [ ] `ARCHITECTURE.md` exists and is complete

### Modified Files Updated ⭐
- [ ] `src/agents/prompts/system_prompts.py` has enhanced Spanish prompt
- [ ] `src/agents/react_agent.py` imports emotion detector and plan memory
- [ ] `src/tools/plan_tool.py` has enhanced parameters

---

## 2️⃣ Import Validation

```bash
cd /Users/lmatos/Workspace/auphere/auphere-agent
python3 -c "from src.classifiers.emotion_detector import EmotionDetector; print('✅ EmotionDetector OK')"
python3 -c "from src.agents.plan_memory import PlanMemoryManager; print('✅ PlanMemoryManager OK')"
python3 -c "from src.agents.react_agent import ReactAgent; print('✅ ReactAgent OK')"
```

**Expected Output:**
```
✅ EmotionDetector OK
✅ PlanMemoryManager OK
✅ ReactAgent OK
```

- [ ] All imports succeed without errors
- [ ] No circular dependencies
- [ ] No missing modules

---

## 3️⃣ Unit Tests Validation

```bash
cd /Users/lmatos/Workspace/auphere/auphere-agent
pytest tests/test_plan_flow.py -v
```

**Expected Results:**

### EmotionDetector Tests (9 tests)
- [ ] `test_detect_bored` PASSED
- [ ] `test_detect_romantic` PASSED
- [ ] `test_detect_stressed` PASSED
- [ ] `test_detect_excited` PASSED
- [ ] `test_neutral_no_emotion` PASSED
- [ ] `test_tone_adaptation` PASSED
- [ ] `test_detect_adventurous` PASSED
- [ ] `test_detect_tired` PASSED
- [ ] `test_detect_celebratory` PASSED

### PlanMemoryManager Tests (12 tests)
- [ ] `test_update_context` PASSED
- [ ] `test_missing_fields` PASSED
- [ ] `test_plan_ready` PASSED
- [ ] `test_plan_not_ready` PASSED
- [ ] `test_conversation_history` PASSED
- [ ] `test_track_questions_asked` PASSED
- [ ] `test_context_summary` PASSED
- [ ] `test_reset` PASSED
- [ ] `test_multiple_cities` PASSED
- [ ] `test_multiple_place_types` PASSED
- [ ] `test_budget_levels` PASSED
- [ ] `test_transport_modes` PASSED

### PlanContext Tests (6 tests)
- [ ] `test_to_dict` PASSED
- [ ] `test_is_plan_ready_all_fields` PASSED
- [ ] `test_is_plan_ready_missing_fields` PASSED
- [ ] `test_default_values` PASSED
- [ ] `test_emotion_tracking` PASSED

### Tone Adaptation Tests (4 tests)
- [ ] `test_all_emotions_have_tones` PASSED
- [ ] `test_bored_tone_is_enthusiastic` PASSED
- [ ] `test_stressed_tone_is_concise` PASSED
- [ ] `test_romantic_tone_is_elegant` PASSED

**Total:** 30+ tests should pass

---

## 4️⃣ Agent API Validation

```bash
# Start agent
uvicorn api.main:app --reload --port 8001
```

### Health Check
```bash
curl http://localhost:8001/agent/health
```

**Expected Response:**
```json
{
  "status": "healthy",
  "database_status": "online" or "offline"
}
```

- [ ] Agent starts without errors
- [ ] Health endpoint returns 200
- [ ] Database connection status shown

### Query Test
```bash
curl -X POST http://localhost:8001/agent/query \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test-user",
    "session_id": "test-session",
    "query": "Estoy aburrido",
    "language": "es"
  }'
```

**Expected Response Fields:**
```json
{
  "response_text": "...",
  "detected_emotion": "bored",
  "emotion_confidence": 0.8,
  "tool_calls": 0,
  "reasoning_steps": 3
}
```

- [ ] Response contains `detected_emotion`
- [ ] Response contains `emotion_confidence`
- [ ] Response is natural and empathetic
- [ ] No errors in logs

---

## 5️⃣ Streamlit UI Validation

```bash
# Start Streamlit
streamlit run streamlit_app.py
```

### Main Chat Page
- [ ] Main page loads at http://localhost:8501
- [ ] Can send messages
- [ ] Agent responds correctly
- [ ] No console errors

### Plan Flow Test Page
- [ ] Navigate to "Plan Flow Test" in sidebar
- [ ] Page loads without errors
- [ ] Conversation container displays
- [ ] Metrics panel displays

### Quick Scenarios
- [ ] "Bored User" button works
- [ ] "Create Plan" button works
- [ ] "Romantic" button works
- [ ] "In a Hurry" button works

### Metrics Display
- [ ] Emotion detected shows in metadata
- [ ] Confidence score displays
- [ ] Model used shows
- [ ] Processing time shows

### Reset Functionality
- [ ] "Reset Conversation" clears history
- [ ] New session ID generated
- [ ] Conversation count resets to 0

---

## 6️⃣ End-to-End Flow Validation

### Test Flow 1: Bored User
```
User: "Estoy aburrido, no sé qué hacer esta noche"
```

**Validate:**
- [ ] Emotion detected: `bored`
- [ ] Confidence > 0.3
- [ ] Response tone is enthusiastic
- [ ] Suggests variety of options
- [ ] Response is natural (not robotic)

### Test Flow 2: Plan Creation
```
Turn 1: "Quiero un plan para esta noche"
Turn 2: "2 personas, 2 horas"
Turn 3: "Zaragoza"
Turn 4: "Bares"
Turn 5: "Romántico"
```

**Validate:**
- [ ] Agent asks strategic questions (groups related)
- [ ] Doesn't ask all 7 questions at once
- [ ] Plan context updates after each turn
- [ ] Missing fields tracked correctly
- [ ] Creates plan when all required fields present
- [ ] Plan includes personalization

### Test Flow 3: Romantic Plan
```
User: "Quiero un plan romántico para una cita especial"
```

**Validate:**
- [ ] Emotion detected: `romantic`
- [ ] Response tone is elegant
- [ ] Suggests special/premium places
- [ ] Asks about group size and duration
- [ ] Creates romantic atmosphere in suggestions

### Test Flow 4: Stressed User
```
User: "Tengo prisa, necesito algo rápido para 30 minutos"
```

**Validate:**
- [ ] Emotion detected: `stressed`
- [ ] Response is concise and direct
- [ ] Doesn't ask unnecessary questions
- [ ] Prioritizes speed and efficiency
- [ ] Suggests quick options

---

## 7️⃣ System Prompt Validation

### Spanish Prompt Sections
- [ ] "TU PERSONALIDAD" section present
- [ ] "CÓMO ENTIENDES AL USUARIO" section present
- [ ] "FLUJO DE CREACIÓN DE PLANES" section present
- [ ] "DETECCIÓN DE EMOCIONES" section present
- [ ] "REGLAS DE ORO" section present
- [ ] Placeholders for preferences and location work
- [ ] No typos or formatting errors

### Tone Adaptation
- [ ] System prompt includes tone instruction
- [ ] Tone varies based on detected emotion
- [ ] Agent response matches recommended tone

---

## 8️⃣ Memory Management Validation

### Session Memory
- [ ] Plan context persists within session
- [ ] Conversation history tracked
- [ ] Questions asked tracked
- [ ] Context summary accurate

### Context Validation
- [ ] Can update duration
- [ ] Can update num_people
- [ ] Can update cities (list)
- [ ] Can update place_types (list)
- [ ] Can update vibe
- [ ] Can update budget
- [ ] Can update transport

### Ready Validation
- [ ] `is_plan_ready()` returns False when missing fields
- [ ] `is_plan_ready()` returns True when all 5 required fields present
- [ ] `get_missing_for_plan()` returns correct missing fields

---

## 9️⃣ Plan Tool Enhancement Validation

### New Parameters Work
```python
await plan_tool.create_plan(
    query="bar hopping",
    city="Zaragoza",
    duration="2 hours",      # NEW
    num_people=3,            # NEW
    vibe="party",            # NEW
    budget="medium",         # NEW
    transport="walking"      # NEW
)
```

- [ ] Duration parsing works for multiple formats
- [ ] Personalization based on vibe
- [ ] Group size affects recommendations
- [ ] Budget affects cost estimate
- [ ] Transport affects route optimization

### Response Enhancement
- [ ] `estimated_cost` field present
- [ ] `metadata` object includes all new fields
- [ ] Personalization notes on steps
- [ ] Group notes when num_people > 4
- [ ] Budget notes on steps

---

## 🔟 Performance Validation

### Response Times
- [ ] Emotion detection < 50ms
- [ ] Plan memory update < 10ms
- [ ] System prompt build < 50ms
- [ ] Full agent response < 5s (with LLM)

### Memory Usage
- [ ] No memory leaks in long sessions
- [ ] Session memory < 1MB per user
- [ ] Plan memory resets correctly

### Concurrent Users
- [ ] Multiple sessions work independently
- [ ] No state leakage between sessions
- [ ] Thread-safe operations

---

## 1️⃣1️⃣ Error Handling Validation

### Edge Cases
- [ ] Empty query handled gracefully
- [ ] Missing session_id creates default
- [ ] Invalid emotion query defaults to neutral
- [ ] Plan with missing fields shows clear error
- [ ] Tool failures return helpful messages

### Logging
- [ ] Emotion detection logged
- [ ] Plan context updates logged
- [ ] Turn additions logged
- [ ] No sensitive data in logs

---

## 1️⃣2️⃣ Backward Compatibility Validation

### Existing Functionality
- [ ] Old system prompt still available
- [ ] Place search tool still works
- [ ] Original plan creation still works
- [ ] Intent classification unchanged
- [ ] Memory system unchanged

### API Compatibility
- [ ] Old API requests still work
- [ ] New fields are additive only
- [ ] No breaking changes
- [ ] Optional parameters truly optional

---

## 1️⃣3️⃣ Documentation Validation

### Completeness
- [ ] AGENT_IMPROVEMENTS.md is complete
- [ ] IMPLEMENTATION_SUMMARY.md is complete
- [ ] QUICK_START.md is complete
- [ ] ARCHITECTURE.md is complete
- [ ] All code has docstrings
- [ ] All functions have type hints

### Accuracy
- [ ] Examples in docs work
- [ ] API references match code
- [ ] File paths are correct
- [ ] Commands are tested

---

## 1️⃣4️⃣ Security Validation

### Input Validation
- [ ] Query length limits enforced
- [ ] No SQL injection possible
- [ ] No XSS possible in Streamlit
- [ ] API key not exposed in logs

### Data Privacy
- [ ] No PII in emotion detection
- [ ] Session data isolated
- [ ] User data follows privacy policy
- [ ] Logs don't contain sensitive info

---

## Final Checklist Summary

### Critical (Must Pass)
- [ ] All unit tests pass (30+)
- [ ] Agent API starts successfully
- [ ] Streamlit loads without errors
- [ ] Emotion detection works
- [ ] Plan memory works
- [ ] No breaking changes

### Important (Should Pass)
- [ ] All documentation complete
- [ ] Performance within limits
- [ ] Error handling works
- [ ] Logging is appropriate
- [ ] Security validated

### Nice to Have (Can Fix Later)
- [ ] All edge cases handled
- [ ] Optimal performance tuning
- [ ] Additional test scenarios
- [ ] Extended documentation

---

## Sign-Off

**Validation Completed By:** ___________________  
**Date:** ___________________  
**All Critical Items:** ☐ Pass ☐ Fail  
**All Important Items:** ☐ Pass ☐ Fail  
**Ready for Production:** ☐ Yes ☐ No ☐ With Notes  

**Notes:**
```
_________________________________________________________________
_________________________________________________________________
_________________________________________________________________
```

---

## Troubleshooting Common Issues

### Issue: Tests Fail
**Solution:**
```bash
pip install -r requirements.txt
pytest tests/test_plan_flow.py -v -s
```

### Issue: Import Errors
**Solution:**
```bash
export PYTHONPATH="${PYTHONPATH}:/Users/lmatos/Workspace/auphere/auphere-agent"
```

### Issue: Agent Won't Start
**Solution:**
```bash
# Check port availability
lsof -ti:8001 | xargs kill -9
uvicorn api.main:app --reload --port 8001
```

### Issue: Streamlit Page Not Showing
**Solution:**
```bash
# Verify pages directory
ls -la pages/04_plan_flow.py
# Restart Streamlit
streamlit run streamlit_app.py --server.runOnSave true
```

---

**✅ Use this checklist before deploying to production!**

