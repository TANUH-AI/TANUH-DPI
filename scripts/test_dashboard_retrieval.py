import httpx
import asyncio
import json
import os

async def test_dashboard_endpoints():
    print("=== Dashboard Data Retrieval Test ===")
    
    domain = "nhcxhackathon.tanuh.ai"
    
    # 1. Health Checks
    print("\n--- Phase 1: Health Checks ---")
    endpoints = [
        ("Session Logger Health", f"https://{domain}/session-logger/health"),
        ("Privacy Filter Health", f"https://{domain}/privacy-filter/api/health"),
        ("pdf2nhcx Health", f"https://{domain}/pdf2nhcx/health"),
        ("pdf2abdm Health", f"https://{domain}/pdf2abdm/health")
    ]
    
    async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
        for name, url in endpoints:
            try:
                res = await client.get(url)
                print(f"✅ {name}: {res.status_code} {res.json() if res.status_code == 200 else res.text[:50]}")
            except Exception as e:
                print(f"❌ {name}: Failed - {e}")

    # 2. Stats Checks
    print("\n--- Phase 2: Stats Retrieval ---")
    
    # 2.1 Session Logger Stats
    session_logger_url = f"https://{domain}/session-logger/logs/stats"
    print(f"\n[1] Checking Session Logger Stats: {session_logger_url}")
    try:
        async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
            res = await client.get(session_logger_url)
            print(f"Status: {res.status_code}")
            if res.status_code == 200:
                stats = res.json()
                print(f"Data: {json.dumps(stats, indent=2)}")
            else:
                print(f"❌ ERROR: Session Logger returned {res.status_code}")
    except Exception as e:
        print(f"❌ ERROR: Failed to connect to Session Logger: {e}")

    # 2.2 Privacy Filter Stats
    privacy_filter_url = f"https://{domain}/privacy-filter/api/stats"
    print(f"\n[2] Checking Privacy Filter Stats: {privacy_filter_url}")
    try:
        async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
            res = await client.get(privacy_filter_url)
            print(f"Status: {res.status_code}")
            if res.status_code == 200:
                stats = res.json()
                print(f"Data: {json.dumps(stats, indent=2)}")
            else:
                print(f"❌ ERROR: Privacy Filter returned {res.status_code}")
    except Exception as e:
        print(f"❌ ERROR: Failed to connect to Privacy Filter: {e}")

    print("\n=== Test Complete ===")

if __name__ == "__main__":
    asyncio.run(test_dashboard_endpoints())
