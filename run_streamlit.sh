#!/usr/bin/env bash
# Script to run the Streamlit interface for Auphere Agent

set -e

echo "🚀 Starting Auphere Agent - Streamlit Interface"
echo "==============================================="
echo ""

# Check if virtual environment is activated
if [[ -z "$VIRTUAL_ENV" ]]; then
    if [[ -f ".venv/bin/activate" ]]; then
        echo "Activating .venv..."
        source .venv/bin/activate
    else
        echo "⚠️  Virtual environment not found or not activated."
        echo "   Please run: python3.11 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    fi
fi

# Check if agent is running
echo "🔍 Checking services..."
if curl -s http://localhost:8001/agent/health > /dev/null 2>&1; then
    echo "✅ Auphere Agent (8001) - OK"
else
    echo "⚠️  Auphere Agent (8001) - Not running"
    echo "   Ensure the agent is running in another terminal:"
    echo "   uvicorn api.main:app --port 8001 --reload"
fi

echo ""
echo "🌐 Starting Streamlit on http://localhost:8501"
echo "==============================================="
echo ""

# Run streamlit
streamlit run streamlit_app.py \
    --server.port 8501 \
    --server.address localhost \
    --browser.gatherUsageStats false

