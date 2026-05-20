import requests
import time
import sys

BASE_URL = "https://nhcxhackathon.tanuh.ai/privacy-filter"
HEALTH_URL = f"{BASE_URL}/api/health"
REDACT_URL = f"{BASE_URL}/api/redact"
STATS_URL = f"{BASE_URL}/api/stats"

def test_health():
    print(f"Checking health at {HEALTH_URL}...")
    try:
        r = requests.get(HEALTH_URL, timeout=10)
        if r.status_code == 200:
            data = r.json()
            status = data.get("status")
            print(f"  [SUCCESS] Status: {status}")
            return status == "ok"
        else:
            print(f"  [ERROR] Received HTTP {r.status_code}")
            return False
    except Exception as e:
        print(f"  [ERROR] Connection failed: {e}")
        return False

def test_redaction():
    print(f"\nTesting redaction at {REDACT_URL}...")
    payload = {
        "text": "Hello, my name is Ashwin Rajkumar. You can reach me at ashwin@example.com or 9876543210."
    }
    try:
        r = requests.post(REDACT_URL, json=payload, timeout=30)
        if r.status_code == 200:
            data = r.json()
            redacted = data.get("redacted_text", "")
            print(f"  [SUCCESS] Redacted Text: {redacted}")
            
            # Simple checks
            if "Ashwin" in redacted:
                print("  [WARNING] 'Ashwin' was not redacted!")
            if "ashwin@example.com" in redacted:
                print("  [WARNING] Email was not redacted!")
            if "9876543210" in redacted:
                print("  [WARNING] Phone number was not redacted!")
                
            return True
        else:
            print(f"  [ERROR] Received HTTP {r.status_code}: {r.text}")
            return False
    except Exception as e:
        print(f"  [ERROR] Redaction request failed: {e}")
        return False

def test_stats():
    print(f"\nChecking stats at {STATS_URL}...")
    try:
        r = requests.get(STATS_URL, timeout=10)
        if r.status_code == 200:
            data = r.json()
            print(f"  [SUCCESS] Stats: {data}")
            return True
        else:
            print(f"  [ERROR] Received HTTP {r.status_code}")
            return False
    except Exception as e:
        print(f"  [ERROR] Stats request failed: {e}")
        return False

def main():
    print("=== Privacy Filter Service Test ===\n")
    
    # 1. Health Polling
    max_retries = 10
    retry_interval = 30 # seconds
    
    for i in range(max_retries):
        is_ready = test_health()
        if is_ready:
            break
        print(f"  Service is not ready yet. Retrying in {retry_interval}s... ({i+1}/{max_retries})")
        time.sleep(retry_interval)
    else:
        print("\n[FATAL] Service did not become healthy in time. Please check server logs.")
        sys.exit(1)
        
    # 2. Functional Test
    if not test_redaction():
        print("\n[FAILURE] Redaction test failed.")
    
    # 3. Stats Test
    if not test_stats():
        print("\n[FAILURE] Stats test failed.")
        
    print("\n=== Test Sequence Complete ===")

if __name__ == "__main__":
    main()
