"""
Test plan creation flow with complete conversation.
"""

import json
from datetime import datetime

import requests
import streamlit as st

st.set_page_config(page_title="Plan Flow Test", layout="wide")

st.header("🗓️ Test Plan Creation Flow")
st.write("Test the complete plan creation flow with emotion detection and memory")

# Initialize session state
if "plan_conversation" not in st.session_state:
    st.session_state.plan_conversation = []
    st.session_state.plan_context = {
        "duration": None,
        "num_people": None,
        "cities": [],
        "place_types": [],
        "vibe": None,
    }
    st.session_state.session_id = "test-session-" + datetime.now().strftime("%s")

col1, col2 = st.columns(2)

with col1:
    st.subheader("💬 Conversation")

    # Display conversation
    chat_container = st.container(height=400, border=True)
    with chat_container:
        for i, turn in enumerate(st.session_state.plan_conversation):
            with st.chat_message("user"):
                st.write(turn["user"])
            with st.chat_message("assistant"):
                st.write(turn["agent"])
                if turn.get("metadata"):
                    with st.expander("📊 Metrics"):
                        st.json(turn["metadata"])

    # Input form
    st.write("### Send Message")
    col_input, col_send = st.columns([3, 1])

    with col_input:
        user_input = st.text_input(
            "Your message:", key="user_plan_input", label_visibility="collapsed"
        )

    with col_send:
        send_clicked = st.button("Send", use_container_width=True)

    if send_clicked and user_input:
        # Call agent
        with st.spinner("🤖 Agent thinking..."):
            try:
                response = requests.post(
                    "http://localhost:8001/agent/query",
                    json={
                        "user_id": "test-user-plan",
                        "session_id": st.session_state.session_id,
                        "query": user_input,
                        "language": "es",
                    },
                    timeout=30,
                )

                if response.status_code == 200:
                    data = response.json()
                    agent_response = data.get(
                        "response_text", "Error generating response"
                    )

                    # Track conversation
                    st.session_state.plan_conversation.append(
                        {
                            "user": user_input,
                            "agent": agent_response,
                            "timestamp": datetime.now().isoformat(),
                            "metadata": {
                                "intention": data.get("intention"),
                                "confidence": data.get("confidence"),
                                "emotion": data.get("metadata", {}).get(
                                    "detected_emotion"
                                )
                                or data.get("detected_emotion"),
                                "emotion_confidence": data.get("emotion_confidence"),
                                "model": data.get("model_used"),
                                "processing_time_ms": data.get("processing_time_ms"),
                            },
                        }
                    )

                    st.rerun()
                else:
                    st.error(f"Error: {response.status_code} - {response.text}")
            except requests.exceptions.ConnectionError:
                st.error(
                    "❌ Cannot connect to agent API. Is it running on http://localhost:8001?"
                )
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")

with col2:
    st.subheader("📊 Plan Context")

    if st.session_state.plan_conversation:
        # Show last response metadata
        last_turn = st.session_state.plan_conversation[-1]

        st.write("**Last Response:**")
        for key, value in last_turn["metadata"].items():
            st.caption(f"{key}: {value}")

        st.divider()

    st.write("**Conversation Stats:**")
    st.metric("Turns", len(st.session_state.plan_conversation))

    if st.session_state.plan_conversation:
        last_response_len = len(st.session_state.plan_conversation[-1]["agent"])
        st.metric("Last Response Length", f"{last_response_len} chars")

    st.divider()

    st.write("**Session ID:**")
    st.code(st.session_state.session_id)

# Quick test scenarios
st.markdown("---")
st.subheader("🎯 Quick Test Scenarios")

col1, col2, col3, col4 = st.columns(4)

scenarios = {
    "Bored User": "Estoy aburrido, no sé qué hacer esta noche",
    "Create Plan": "Crea un plan para esta noche con mis amigos",
    "Romantic": "Quiero un plan romántico para una cita especial",
    "In a Hurry": "Tengo 30 minutos, ¿qué puedo hacer?",
}

for idx, (name, query) in enumerate(scenarios.items()):
    col = [col1, col2, col3, col4][idx]
    with col:
        if st.button(name, use_container_width=True, key=f"scenario_{idx}"):
            # Simulate sending the query
            try:
                response = requests.post(
                    "http://localhost:8001/agent/query",
                    json={
                        "user_id": "test-user-plan",
                        "session_id": st.session_state.session_id,
                        "query": query,
                        "language": "es",
                    },
                    timeout=30,
                )

                if response.status_code == 200:
                    data = response.json()
                    agent_response = data.get(
                        "response_text", "Error generating response"
                    )

                    # Track conversation
                    st.session_state.plan_conversation.append(
                        {
                            "user": query,
                            "agent": agent_response,
                            "timestamp": datetime.now().isoformat(),
                            "metadata": {
                                "intention": data.get("intention"),
                                "confidence": data.get("confidence"),
                                "emotion": data.get("metadata", {}).get(
                                    "detected_emotion"
                                )
                                or data.get("detected_emotion"),
                                "emotion_confidence": data.get("emotion_confidence"),
                                "model": data.get("model_used"),
                                "processing_time_ms": data.get("processing_time_ms"),
                            },
                        }
                    )

                    st.rerun()
            except Exception as e:
                st.error(f"Error: {str(e)}")

# Reset button
st.write("### Utils")
if st.button("🔄 Reset Conversation", use_container_width=True):
    st.session_state.plan_conversation = []
    st.session_state.plan_context = {
        "duration": None,
        "num_people": None,
        "cities": [],
        "place_types": [],
        "vibe": None,
    }
    st.session_state.session_id = "test-session-" + datetime.now().strftime("%s")
    st.rerun()

