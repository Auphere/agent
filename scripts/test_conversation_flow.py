import asyncio
import uuid
import sys
from pathlib import Path
import httpx

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.config.settings import get_settings

async def run_conversation_test():
    settings = get_settings()
    base_url = "http://localhost:8001/agent"  # Adjust port if needed
    
    # Generate a consistent session ID for this test run
    session_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    
    print(f"🚀 Starting Conversation Test")
    print(f"📝 Session ID: {session_id}")
    print(f"👤 User ID: {user_id}")
    print("-" * 50)

    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        # --- TURN 1 ---
        query1 = "hola estoy buscando un lugar romantico para ir con mi pareja"
        print(f"\n🔵 User (Turn 1): {query1}")
        
        payload1 = {
            "user_id": user_id,
            "session_id": session_id,
            "query": query1,
            "language": "es"
        }
        
        try:
            response1 = await client.post(f"{base_url}/query", json=payload1)
            response1.raise_for_status()
            data1 = response1.json()
            print(f"🟢 Agent (Turn 1): {data1['response_text']}")
            print(f"   [Intention: {data1['intention']}]")
        except Exception as e:
            print(f"❌ Error in Turn 1: {e}")
            return

        # --- TURN 2 ---
        query2 = "estaba pensando por el casco historico de zaragoza"
        print(f"\n🔵 User (Turn 2): {query2}")
        
        payload2 = {
            "user_id": user_id,
            "session_id": session_id,
            "query": query2,
            "language": "es"
        }
        
        try:
            response2 = await client.post(f"{base_url}/query", json=payload2)
            response2.raise_for_status()
            data2 = response2.json()
            
            print(f"🟢 Agent (Turn 2): {data2['response_text']}")
            print(f"   [Intention: {data2['intention']}]")
            print(f"   [Model Used: {data2['model_used']}]")
            
            # Check if context/history was actually used
            context_used = data2.get("metadata", {}).get("had_conversation_history", False)
            print(f"   [History Used: {context_used}]")
            
            places = data2.get("places", [])
            if places:
                print(f"   ✅ SUCCESS: Found {len(places)} places!")
                for p in places:
                    print(f"      - {p['name']}")
            else:
                print(f"   ⚠️ WARNING: No places returned. The agent might have lost context.")
                
        except Exception as e:
            print(f"❌ Error in Turn 2: {e}")

if __name__ == "__main__":
    asyncio.run(run_conversation_test())

