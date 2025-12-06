#!/usr/bin/env python3
"""
Comprehensive test suite for the Auphere Agent.
Tests 10 different scenarios to validate memory, tools, and behavior.
"""

import asyncio
import sys
import uuid
from pathlib import Path
from typing import Dict, List, Tuple

import httpx

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))


class AgentTester:
    """Test harness for the Auphere Agent."""

    def __init__(self, base_url: str = "http://localhost:8001"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=30.0, verify=False)
        self.passed = 0
        self.failed = 0
        self.warnings = 0

    async def test_health(self) -> bool:
        """Test 0: Health check and DB connection."""
        print("\n" + "=" * 80)
        print("TEST 0: Health Check & Database Connection")
        print("=" * 80)

        try:
            response = await self.client.get(f"{self.base_url}/agent/health")
            response.raise_for_status()
            data = response.json()

            print(f"✅ Status: {data['status']}")
            print(f"   Service: {data['service']}")
            print(f"   Version: {data['version']}")
            print(f"   Environment: {data['environment']}")
            print(f"   Database: {data.get('database_status', 'UNKNOWN')}")
            print(f"   Redis: {data.get('redis_status', 'UNKNOWN')}")

            db_status = data.get("database_status", "unknown")
            if db_status == "online":
                print("\n✅ Database is ONLINE - Memory will persist")
                return True
            elif db_status == "disabled":
                print("\n⚠️  Database is DISABLED - Agent will have no memory")
                self.warnings += 1
                return False
            else:
                print(f"\n❌ Database is {db_status.upper()} - Tests may fail")
                self.failed += 1
                return False

        except Exception as e:
            print(f"\n❌ Health check failed: {e}")
            self.failed += 1
            return False

    async def run_conversation(
        self,
        test_name: str,
        turns: List[Tuple[str, List[str]]],
        session_id: str = None,
        user_id: str = None,
    ) -> bool:
        """
        Run a multi-turn conversation and validate responses.

        Args:
            test_name: Name of the test
            turns: List of (query, expected_keywords) tuples
            session_id: Optional session ID (generates new if None)
            user_id: Optional user ID (generates new if None)

        Returns:
            True if test passed, False otherwise
        """
        print("\n" + "=" * 80)
        print(f"TEST: {test_name}")
        print("=" * 80)

        session_id = session_id or str(uuid.uuid4())
        user_id = user_id or str(uuid.uuid4())

        print(f"Session ID: {session_id}")
        print(f"User ID: {user_id}\n")

        test_passed = True

        for turn_num, (query, expected_keywords) in enumerate(turns, 1):
            print(f"🔵 Turn {turn_num}: {query}")

            payload = {
                "user_id": user_id,
                "session_id": session_id,
                "query": query,
                "language": "es",
            }

            try:
                response = await self.client.post(
                    f"{self.base_url}/agent/query", json=payload
                )
                response.raise_for_status()
                data = response.json()

                response_text = data.get("response_text", "")
                intention = data.get("intention", "UNKNOWN")
                model = data.get("model_used", "UNKNOWN")
                processing_time = data.get("processing_time_ms", 0)
                places = data.get("places", [])
                metadata = data.get("metadata", {})
                had_history = metadata.get("had_conversation_history", False)

                print(f"🟢 Agent Response ({processing_time}ms):")
                print(f"   {response_text[:200]}{'...' if len(response_text) > 200 else ''}")
                print(f"\n   📊 Intention: {intention}")
                print(f"   🤖 Model: {model}")
                print(f"   🔧 Places Found: {len(places)}")
                print(f"   💭 Had History: {had_history}")

                # Validate expected keywords
                missing_keywords = []
                for keyword in expected_keywords:
                    if keyword.lower() not in response_text.lower():
                        missing_keywords.append(keyword)

                if missing_keywords:
                    print(f"\n   ⚠️  Missing expected keywords: {missing_keywords}")
                    test_passed = False
                else:
                    print(f"   ✅ All expected keywords found")

                # For multi-turn tests, validate history is being used
                if turn_num > 1 and not had_history:
                    print(f"   ⚠️  WARNING: Turn {turn_num} should have history but doesn't!")
                    test_passed = False

                print()

            except httpx.HTTPStatusError as e:
                print(f"   ❌ HTTP Error: {e.response.status_code}")
                print(f"   {e.response.text}\n")
                test_passed = False
            except Exception as e:
                print(f"   ❌ Error: {e}\n")
                test_passed = False

        if test_passed:
            print("✅ TEST PASSED\n")
            self.passed += 1
        else:
            print("❌ TEST FAILED\n")
            self.failed += 1

        return test_passed

    async def run_all_tests(self):
        """Run all test scenarios."""
        print("\n" + "🚀" * 40)
        print("AUPHERE AGENT - COMPREHENSIVE TEST SUITE")
        print("🚀" * 40)

        # Test 0: Health Check
        db_online = await self.test_health()

        if not db_online:
            print(
                "\n⚠️  WARNING: Database is not online. Memory tests will likely fail."
            )
            print("Continue anyway? (yes/no): ", end="")
            # For automated tests, we'll continue
            # In interactive mode, you could add input() here

        # Test 1: Simple place search (single turn)
        await self.run_conversation(
            test_name="1. Simple Place Search (Single Turn)",
            turns=[
                (
                    "Busco bares en Zaragoza",
                    ["bar", "zaragoza", "encontré", "⭐"],  # Expecting results
                )
            ],
        )

        # Test 2: Multi-turn conversation with context (CRITICAL for memory)
        await self.run_conversation(
            test_name="2. Multi-Turn Conversation (Memory Test)",
            turns=[
                (
                    "Hola, busco un restaurante romántico",
                    ["ciudad", "dónde"],  # Should ask for location
                ),
                (
                    "En Zaragoza, por el centro histórico",
                    ["restaurante", "zaragoza"],  # Should remember "romántico"
                ),
            ],
        )

        # Test 3: Greeting (CHITCHAT)
        await self.run_conversation(
            test_name="3. Greeting / Chitchat",
            turns=[
                (
                    "Hola, ¿cómo estás?",
                    ["hola", "ayud"],  # Should respond friendly
                )
            ],
        )

        # Test 4: City limitation enforcement
        await self.run_conversation(
            test_name="4. City Limitation (Not Zaragoza)",
            turns=[
                (
                    "Busco cafeterías en Madrid",
                    ["zaragoza", "momento"],  # Should say only Zaragoza available
                )
            ],
        )

        # Test 5: Missing location - should ask
        await self.run_conversation(
            test_name="5. Missing Location (Should Ask)",
            turns=[
                (
                    "Quiero ir a un museo",
                    ["ciudad", "dónde", "zona"],  # Should ask where
                )
            ],
        )

        # Test 6: Specific neighborhood search
        await self.run_conversation(
            test_name="6. Neighborhood-Specific Search",
            turns=[
                (
                    "Dame cafeterías en el barrio de Delicias, Zaragoza",
                    ["café", "zaragoza"],  # Should search cafes
                )
            ],
        )

        # Test 7: Three-turn conversation (extended memory)
        session_id = str(uuid.uuid4())
        await self.run_conversation(
            test_name="7. Three-Turn Conversation (Extended Memory)",
            turns=[
                ("Busco un lugar para cenar", ["ciudad", "dónde"]),
                ("En Zaragoza", ["tipo", "comida", "preferencia"]),
                (
                    "Algo tranquilo y no muy caro",
                    ["restaurante", "zaragoza"],
                ),  # Should combine all context
            ],
            session_id=session_id,
        )

        # Test 8: Recommendation intent
        await self.run_conversation(
            test_name="8. Recommendation Request",
            turns=[
                (
                    "¿Cuáles son los mejores bares de tapas en Zaragoza?",
                    ["bar", "zaragoza", "⭐"],  # Should return places
                )
            ],
        )

        # Test 9: Plan/Itinerary request (if enabled)
        await self.run_conversation(
            test_name="9. Plan/Itinerary Request",
            turns=[
                (
                    "Crea un plan para salir de bares por Zaragoza",
                    ["plan", "zaragoza", "bar"],  # Should attempt plan
                )
            ],
        )

        # Test 10: Context switch (new topic in same session)
        session_id = str(uuid.uuid4())
        await self.run_conversation(
            test_name="10. Context Switch (Same Session, New Topic)",
            turns=[
                ("Busco restaurantes en Zaragoza", ["restaurante", "zaragoza"]),
                (
                    "Ahora quiero museos",
                    ["museo", "zaragoza"],
                ),  # Should switch topic but keep location
            ],
            session_id=session_id,
        )

        # Print summary
        await self.print_summary()

    async def print_summary(self):
        """Print test summary."""
        print("\n" + "=" * 80)
        print("TEST SUMMARY")
        print("=" * 80)
        print(f"✅ Passed:   {self.passed}")
        print(f"❌ Failed:   {self.failed}")
        print(f"⚠️  Warnings: {self.warnings}")
        print(f"📊 Total:    {self.passed + self.failed}")

        success_rate = (
            (self.passed / (self.passed + self.failed)) * 100
            if (self.passed + self.failed) > 0
            else 0
        )
        print(f"🎯 Success Rate: {success_rate:.1f}%")

        if self.failed == 0:
            print("\n🎉 ALL TESTS PASSED! Agent is working correctly.")
        elif success_rate >= 70:
            print(
                "\n⚠️  Some tests failed, but agent is mostly functional. Check logs for details."
            )
        else:
            print(
                "\n❌ Multiple critical failures. Agent needs debugging. Check health and database connection."
            )

        print("=" * 80 + "\n")

    async def cleanup(self):
        """Cleanup resources."""
        await self.client.aclose()


async def main():
    """Main entry point."""
    tester = AgentTester(base_url="http://localhost:8001")

    try:
        await tester.run_all_tests()
    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrupted by user.")
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}")
    finally:
        await tester.cleanup()


if __name__ == "__main__":
    asyncio.run(main())

