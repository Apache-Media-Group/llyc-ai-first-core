# backend/create_gcs_bucket.py
import os
from google.cloud import storage

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/Users/santiagorovira/media_impact/media-impact-test-keys.json"
project_id = "llyc-ai-first-core"

client = storage.Client(project=project_id)
# Let's try to create a bucket. Since bucket names are globally unique, we can try 'llyc-mcp-public-assets'.
# If that is taken, we can try 'llyc-media-impact-public-assets' or similar.
bucket_name = "llyc-mcp-public-assets"

try:
    print(f"Creating bucket {bucket_name} in project {project_id}...")
    bucket = client.create_bucket(bucket_name, location="us-central1")
    print(f"Bucket {bucket.name} created successfully!")
    
    # Make it publicly readable
    print("Setting public-read access...")
    policy = bucket.get_iam_policy(requested_policy_version=3)
    policy.bindings.append({
        "role": "roles/storage.objectViewer",
        "members": {"allUsers"}
    })
    bucket.set_iam_policy(policy)
    print("Bucket is now publicly readable!")
except Exception as e:
    print(f"Failed to create/configure {bucket_name}: {e}")
    # Let's try with a unique name
    alt_bucket_name = f"llyc-mcp-public-assets-{project_id}"
    try:
        print(f"Trying alternative bucket {alt_bucket_name}...")
        bucket = client.create_bucket(alt_bucket_name, location="us-central1")
        print(f"Bucket {bucket.name} created successfully!")
        
        # Make it publicly readable
        policy = bucket.get_iam_policy(requested_policy_version=3)
        policy.bindings.append({
            "role": "roles/storage.objectViewer",
            "members": {"allUsers"}
        })
        bucket.set_iam_policy(policy)
        print("Alternative bucket is now publicly readable!")
    except Exception as ae:
        print(f"Failed to create/configure {alt_bucket_name}: {ae}")
