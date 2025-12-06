#!/usr/bin/env python3
"""Debug script to test PlaceTool directly."""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.tools.place_tool import PlaceSearchTool


async def main():
    print("🔍 Testing PlaceTool directly...\n")
    
    tool = PlaceSearchTool()
    
    print("Test 1: Search for 'bares' in Zaragoza")
    print("-" * 50)
    
    try:
        places = await tool.search_places(query="bares", city="Zaragoza", max_results=3)
        
        if places:
            print(f"✅ Found {len(places)} places:\n")
            for place in places:
                print(f"  - {place.name}")
                print(f"    Type: {place.type}")
                print(f"    Rating: {place.google_rating}")
                print(f"    Location: {place.location}")
                print()
        else:
            print("❌ No places returned (check logs above for errors)")
            
    except Exception as e:
        print(f"❌ Exception: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())

