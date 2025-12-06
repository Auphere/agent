# 🚀 Inicia la Interfaz de Testing Streamlit

## ⚡ Quick Start (3 comandos)

### Terminal 1: Auphere Agent (FastAPI)
```bash
cd /Users/lmatos/Workspace/auphere/auphere-agent
source .venv/bin/activate
uvicorn api.main:app --host 0.0.0.0 --port 8001 --reload
```

### Terminal 2: Auphere Places (Rust)
```bash
cd /Users/lmatos/Workspace/auphere/auphere-places
cargo run --release
```

### Terminal 3: UI estilo Assistant (template oficial)
```bash
cd /Users/lmatos/Workspace/auphere/auphere-agent
source .venv/bin/activate
./run_assistant.sh

# O directamente:
streamlit run streamlit/assistant_app.py --server.port 8502
```

**Notas**:
- `assistant_app.py` replica el template oficial de Streamlit con un look moderno.
- `chat_app.py` sigue disponible con la UI sencilla (./run_chat.sh).
- El dashboard completo con múltiples páginas sigue en `streamlit/app.py`.

## 🌐 Abre tu navegador

```
http://localhost:8501
```

## ✅ Verifica que todo funcione

En el sidebar de la interfaz deberías ver:
- ✅ Auphere Agent (8001) - OK
- ✅ Auphere Places (3001) - OK

Si ves ⚠️ en alguno, verifica que el servicio esté corriendo.

## 🎮 Prueba estos queries

### En la página principal (Main App):

1. **Búsqueda simple:**
   ```
   Buscar restaurantes en Zaragoza
   ```

2. **Recomendación:**
   ```
   Recomiéndame los mejores bares
   ```

3. **Plan:**
   ```
   Crea un plan para cenar esta noche en Zaragoza
   ```

4. **Conversación:**
   ```
   Hola, ¿cómo estás?
   ```

## 📊 Explora las 4 páginas

1. **🤖 Main App** - Testing end-to-end completo
2. **🎯 Intent Classifier** - Testing de clasificación (haz click en "Batch Test")
3. **⚙️ Model Router** - Simulador de routing de modelos
4. **📍 Places Tool** - Testing directo del Rust API

## 🐛 Troubleshooting

### Si Streamlit no inicia:
```bash
pip install streamlit streamlit-chat plotly pandas
```

### Si los servicios no responden:
```bash
# Verifica manualmente
curl http://localhost:8001/agent/health
curl http://localhost:3001/health
```

### Si el puerto 8501 está ocupado:
```bash
streamlit run streamlit/app.py --server.port 8502
```

## 📚 Más Información

- [STREAMLIT_QUICKSTART.md](STREAMLIT_QUICKSTART.md) - Guía de inicio rápido
- [streamlit/README.md](streamlit/README.md) - Documentación completa
- [README.md](README.md) - Documentación del proyecto

---

**¡Listo! 🎉 Ahora puedes testear el agente visualmente antes de integrarlo con el frontend.**

