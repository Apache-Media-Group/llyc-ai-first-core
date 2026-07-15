# backend/test_gcs.py
import os
from google.cloud import storage

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/Users/santiagorovira/media_impact/media-impact-test-keys.json"
project_id = "llyc-ai-first-core"

try:
    client = storage.Client(project=project_id)
    print("Buckets in project:")
    for bucket in client.list_buckets():
        print(f" - {bucket.name}")
except Exception as e:
    print(f"Error: {e}")
