"""
Streamlit Chat Interface for Auphere Agent
Optimized interface connecting to the FastAPI microservice.
"""

import streamlit as st
import os
import uuid
import requests
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Agent API Configuration
AGENT_API_URL = os.getenv("AGENT_API_URL", "http://localhost:8001")

# ========================================
# PAGE CONFIGURATION
# ========================================
st.set_page_config(
    page_title="Auphere - Place Finder Agent",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ========================================
# CUSTOM CSS FOR BETTER UI
# ========================================
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1.1rem;
        margin-bottom: 2rem;
        opacity: 0.8;
    }
    .stButton>button {
        width: 100%;
        border-radius: 8px;
        height: 3rem;
        font-weight: 600;
    }
    /* Boxes styles compatible with dark/light mode */
    .info-box {
        background-color: rgba(59, 130, 246, 0.1);
        border-left: 4px solid #3B82F6;
        padding: 1rem;
        border-radius: 4px;
        margin: 1rem 0;
    }
    .success-box {
        background-color: rgba(16, 185, 129, 0.1);
        border-left: 4px solid #10B981;
        padding: 1rem;
        border-radius: 4px;
        margin: 1rem 0;
    }
    .warning-box {
        background-color: rgba(245, 158, 11, 0.1);
        border-left: 4px solid #F59E0B;
        padding: 1rem;
        border-radius: 4px;
        margin: 1rem 0;
    }
    .metric-card {
        background-color: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        padding: 1rem;
        border-radius: 8px;
        margin: 0.5rem 0;
    }
    /* Fix text colors for better contrast */
    h1, h2, h3, h4, h5, h6, p, li {
        color: inherit;
    }
</style>
""", unsafe_allow_html=True)

# ========================================
# HEADER
# ========================================
col1, col2 = st.columns([4, 1])
with col1:
    st.markdown('<div class="main-header">🗺️ Auphere - Place Finder</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Tu asistente inteligente para encontrar lugares recreativos perfectos</div>', unsafe_allow_html=True)

with col2:
    # Placeholder logo if needed
    st.image("https://via.placeholder.com/100x100.png?text=Logo", width=100)

# ========================================
# SIDEBAR CONFIGURATION
# ========================================
with st.sidebar:
    st.header("⚙️ Configuration")
    
    # Check connection to Agent API
    try:
        response = requests.get(f"{AGENT_API_URL}/agent/health", timeout=2)
        if response.status_code == 200:
            health_data = response.json()
            db_status = health_data.get("database_status", "unknown")
            
            status_icon = "✅"
            if db_status != "online":
                status_icon = "⚠️"
                
            st.markdown(f'<div class="success-box">{status_icon} Agent Online<br><small>DB: {db_status.upper()}</small></div>', unsafe_allow_html=True)
            
            if db_status != "online":
                 st.warning("⚠️ La base de datos no está conectada. El agente no recordará el contexto de la conversación.")
        else:
            st.markdown('<div class="warning-box">⚠️ Agent API Error</div>', unsafe_allow_html=True)
    except requests.exceptions.ConnectionError:
        st.markdown(f'<div class="warning-box">❌ Agent API Offline<br>Is uvicorn running on {AGENT_API_URL}?</div>', unsafe_allow_html=True)
    
    st.divider()
    
    # User Management
    st.subheader("👤 User Management")
    
    # User ID
    if "user_id" not in st.session_state:
        st.session_state.user_id = str(uuid.uuid4())
    
    user_id = st.text_input(
        "User ID",
        value=st.session_state.user_id,
        help="Unique identifier for long-term memory"
    )
    st.session_state.user_id = user_id
    
    # Session ID
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    
    session_id = st.text_input(
        "Session ID",
        value=st.session_state.session_id[:8] + "...",
        disabled=True,
        help="Current conversation session"
    )
    
    st.divider()
    
    # Session Controls
    st.subheader("🔄 Session Controls")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🆕 New Session", use_container_width=True):
            st.session_state.session_id = str(uuid.uuid4())
            st.session_state.messages = []
            st.success("New session started!")
            st.rerun()
    
    with col2:
        if st.button("🗑️ Clear Chat", use_container_width=True):
            st.session_state.messages = []
            st.success("Chat cleared!")
            st.rerun()
    
    st.divider()
    
    # Statistics
    if "messages" in st.session_state:
        st.subheader("📊 Session Stats")
        
        user_msgs = len([m for m in st.session_state.messages if m["role"] == "user"])
        ai_msgs = len([m for m in st.session_state.messages if m["role"] == "assistant"])
        
        col1, col2 = st.columns(2)
        col1.metric("Your Messages", user_msgs)
        col2.metric("AI Responses", ai_msgs)
    
    st.divider()
    
    # Help Section
    with st.expander("💡 Quick Tips", expanded=False):
        st.markdown("""
        **Try asking:**
        - "Encuentra restaurantes románticos en Madrid"
        - "Planea una cita para 2 personas en Zaragoza"
        - "¿Qué museos hay cerca?"
        - "Compara los 3 mejores restaurantes"
        - "¿Dónde puedo pasear con niños?"
        """)

# ========================================
# MAIN CHAT INTERFACE
# ========================================

# Initialize Chat History
if "messages" not in st.session_state:
    st.session_state.messages = []

# Welcome Message
if not st.session_state.messages:
    st.markdown("""
    <div class="info-box">
        <h4>👋 ¡Bienvenido a Auphere!</h4>
        <p>Soy tu asistente inteligente para encontrar lugares recreativos perfectos.</p>
        <p><strong>Puedo ayudarte con:</strong></p>
        <ul>
            <li>🍽️ Restaurantes, cafés, bares</li>
            <li>🎬 Cines, teatros, museos</li>
            <li>🌳 Parques, playas, miradores</li>
            <li>🛍️ Centros comerciales, librerías</li>
            <li>🎯 Planificar salidas completas</li>
        </ul>
        <p><em>Pregúntame lo que necesites y te ayudaré a encontrar el lugar perfecto.</em></p>
    </div>
    """, unsafe_allow_html=True)

# Display Chat Messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Chat Input
if prompt := st.chat_input("¿Qué estás buscando? Ej: 'Restaurantes románticos en Zaragoza'"):
    # Add user message to history
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # Generate AI Response
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        
        try:
            with st.spinner("🤔 Pensando..."):
                # Call Agent API
                payload = {
                    "user_id": st.session_state.user_id,
                    "session_id": st.session_state.session_id,
                    "query": prompt,
                    "language": "es"  # Default to Spanish based on UI
                }
                
                response = requests.post(
                    f"{AGENT_API_URL}/agent/query",
                    json=payload,
                    timeout=120  # Increased for complex queries
                )
                
                if response.status_code == 200:
                    data = response.json()
                    full_response = data.get("response_text", "No response text received.")
                    
                    # Optional: Display places if available in a nice format
                    places = data.get("places", [])
                    if places:
                        full_response += "\n\n**📍 Lugares encontrados:**\n"
                        for i, place in enumerate(places, 1):
                            name = place.get("name", "Unknown")
                            rating = place.get("google_rating") or place.get("rating")
                            rating_str = f" ⭐ {rating}/5" if rating else ""
                            full_response += f"{i}. **{name}**{rating_str}\n"
                else:
                    full_response = f"❌ Error del servidor: {response.status_code} - {response.text}"

            # Display response
            message_placeholder.markdown(full_response)
            
            # Add to history
            st.session_state.messages.append({
                "role": "assistant",
                "content": full_response
            })
            
        except requests.exceptions.ConnectionError:
            error_msg = "❌ Error: No se pudo conectar con el servicio del Agente. Verifica que esté corriendo en el puerto 8001."
            message_placeholder.markdown(error_msg)
            st.session_state.messages.append({"role": "assistant", "content": error_msg})
            
        except Exception as e:
            error_msg = f"❌ **Error:** {str(e)}"
            message_placeholder.markdown(error_msg)
            
            st.session_state.messages.append({
                "role": "assistant",
                "content": error_msg
            })
            
            with st.expander("🔍 Error Details"):
                st.exception(e)

# ========================================
# FOOTER
# ========================================
st.divider()

footer_col1, footer_col2, footer_col3 = st.columns(3)

with footer_col1:
    st.markdown("**🗺️ Auphere**")
    st.caption("Place Finder Agent")

with footer_col2:
    st.markdown("**📚 Resources**")
    st.caption("Microservice Architecture")

with footer_col3:
    st.markdown("**💬 Support**")
    st.caption("v0.1.0 Beta")

