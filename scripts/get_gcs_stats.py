import os
import json
from google.cloud import storage
from dotenv import load_dotenv

def get_gcs_stats():
    load_dotenv()
    
    bucket_name = "tanuh-bcd-bucket"
    blob_name = "privacy-app/stats/counters.json"
    # Priority to gcs-service-account.json if it exists
    if os.path.exists("gcs-service-account.json"):
        creds_path = "gcs-service-account.json"
    else:
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "gcp-service-account.json")
    
    print(f"=== GCS Stats Retrieval ===")
    print(f"Bucket: {bucket_name}")
    print(f"Blob: {blob_name}")
    print(f"Credentials: {creds_path}")
    
    try:
        # Check if creds file exists
        if not os.path.exists(creds_path):
            # Try absolute path from workspace root
            creds_path = os.path.join(os.getcwd(), creds_path)
            if not os.path.exists(creds_path):
                print(f"❌ ERROR: Credentials file not found at {creds_path}")
                return

        client = storage.Client.from_service_account_json(creds_path)
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        
        if not blob.exists():
            print(f"❌ ERROR: Blob {blob_name} does not exist in bucket {bucket_name}")
            return
            
        content = blob.download_as_text()
        stats = json.loads(content)
        print("\n✅ Successfully retrieved stats from GCS:")
        print(json.dumps(stats, indent=2))
        
        # Also check visitor hashes to get unique count if not in counters.json
        hash_blob = bucket.blob("privacy-app/stats/visitor_hashes.json")
        if hash_blob.exists():
            hashes = json.loads(hash_blob.download_as_text())
            print(f"Unique Visitor Hashes: {len(hashes)}")

    except Exception as e:
        print(f"❌ ERROR: {e}")

if __name__ == "__main__":
    get_gcs_stats()
