# 🚀 Quick Start - Auphere Agent Enhancements

## ⚡ 3-Minute Setup

### 1. Start the Agent
```bash
cd /Users/lmatos/Workspace/auphere/auphere-agent
uvicorn api.main:app --reload --port 8001
```

### 2. Start Streamlit
```bash
# In a new terminal
cd /Users/lmatos/Workspace/auphere/auphere-agent
streamlit run streamlit_app.py
```

### 3. Test the Enhancements
1. Open browser: http://localhost:8501
2. Click "Plan Flow Test" in sidebar
3. Try the quick scenarios or type your own

---

## 🎯 What's New?

### ✨ Emotion Detection
Agent now understands emotions and adapts its tone:
- 😴 Bored → Enthusiastic, suggests variety
- 💕 Romantic → Elegant, suggests special places
- 😰 Stressed → Concise, efficient, direct
- 🎉 Excited → Matches energy, expressive
- And 4 more emotions!

### 🧠 Smart Plan Creation
Instead of asking 7 questions at once, now asks strategically:
1. "¿Cuántas personas y cuánto tiempo?" (groups related)
2. "¿Qué ciudad?"
3. "¿Qué tipo de lugares?"
4. "¿Qué vibe buscas?"

### 📋 Plan Memory
Remembers the entire conversation context and never asks the same question twice.

---

## 🧪 Quick Tests

### Test Scenario 1: Bored User
**Type:** "Estoy aburrido, no sé qué hacer esta noche"

**Expected:**
- Emotion: `bored`
- Tone: Enthusiastic, suggests variety
- Response: Multiple exciting options

### Test Scenario 2: Create Plan
**Type:** "Crea un plan para esta noche con mis amigos"

**Expected:**
- Strategic questions (not all at once)
- Tracks what was already asked
- Creates plan when has minimum info

### Test Scenario 3: Romantic
**Type:** "Quiero un plan romántico para una cita especial"

**Expected:**
- Emotion: `romantic`
- Tone: Elegant and thoughtful
- Suggests premium, special places

### Test Scenario 4: In a Hurry
**Type:** "Tengo 30 minutos, ¿qué puedo hacer?"

**Expected:**
- Emotion: `stressed`
- Tone: Concise and direct
- Quick suggestions, no long explanations

---

## 📊 Check Status

### Agent API Health
```bash
curl http://localhost:8001/agent/health
```

### View Logs
```bash
# Agent logs
tail -f agent.log

# Streamlit logs
# Check terminal where streamlit is running
```

---

## 🧪 Run Tests

```bash
# All tests
pytest tests/test_plan_flow.py -v

# Just emotion detection
pytest tests/test_plan_flow.py::TestEmotionDetection -v

# Just plan memory
pytest tests/test_plan_flow.py::TestPlanMemory -v
```

---

## 📁 New Files

| File | Purpose |
|------|---------|
| `src/classifiers/emotion_detector.py` | Emotion detection logic |
| `src/agents/plan_memory.py` | Plan context tracking |
| `pages/04_plan_flow.py` | Testing interface |
| `tests/test_plan_flow.py` | Unit tests |
| `AGENT_IMPROVEMENTS.md` | Full documentation |
| `IMPLEMENTATION_SUMMARY.md` | What was built |
| `QUICK_START.md` | This file |

---

## 🎯 Quick API Reference

### Emotion Detection
```python
from src.classifiers.emotion_detector import EmotionDetector

detector = EmotionDetector()
emotion, confidence = detector.detect("Estoy aburrido")
# Returns: (UserEmotion.BORED, 0.8)
```

### Plan Memory
```python
from src.agents.plan_memory import PlanMemoryManager

manager = PlanMemoryManager()
manager.update_plan_context(duration="2h", num_people=4)
ready, missing = manager.plan_context.is_plan_ready()
```

### Agent Response
```python
# Response now includes:
{
    "response_text": "...",
    "detected_emotion": "bored",
    "emotion_confidence": 0.8
}
```

---

## ⚠️ Troubleshooting

### Port 8001 already in use?
```bash
# Find process using port
lsof -ti:8001 | xargs kill -9

# Or use different port
uvicorn api.main:app --reload --port 8002
# Update Streamlit page to use 8002
```

### Tests failing?
```bash
# Install pytest
pip install pytest

# Run with verbose output
pytest tests/test_plan_flow.py -v -s
```

### Streamlit page not showing?
```bash
# Verify pages directory exists
ls -la pages/

# Should see: 04_plan_flow.py
```

---

## 📚 Full Documentation

- **Complete Guide**: `AGENT_IMPROVEMENTS.md`
- **Implementation Details**: `IMPLEMENTATION_SUMMARY.md`
- **This Quick Start**: `QUICK_START.md`

---

## ✅ Success Checklist

- [ ] Agent API running on port 8001
- [ ] Streamlit running on port 8501
- [ ] Can access Plan Flow Test page
- [ ] Test scenario "Bored User" works
- [ ] Emotion detection shows in metrics
- [ ] Plan creation asks strategic questions
- [ ] All unit tests pass

---

**That's it! You're ready to test the enhanced agent! 🎉**

Need help? Check `AGENT_IMPROVEMENTS.md` for detailed documentation.

