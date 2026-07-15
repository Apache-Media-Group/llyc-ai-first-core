# backend/test_upload.py
import os
from google.cloud import storage

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/Users/santiagorovira/media_impact/media-impact-test-keys.json"
project_id = "llyc-ai-first-core"
bucket_name = "llyc-mcp-public-assets"

client = storage.Client(project=project_id)
bucket = client.bucket(bucket_name)

# Read the local sanitas logo
logo_path = "/Users/santiagorovira/media_impact/frontend/public/logo_sanitas.svg"
if os.path.exists(logo_path):
    with open(logo_path, "rb") as f:
        file_content = f.read()
else:
    file_content = b"<svg>Dummy Logo</svg>"

try:
    print(f"Uploading logo to {bucket_name}/logos/sanitas.svg...")
    blob = bucket.blob("logos/sanitas.svg")
    blob.upload_from_string(file_content, content_type="image/svg+xml")
    print("Upload completed!")
    
    # Try making it public via ACL
    print("Making blob public...")
    try:
        blob.make_public()
        print(f"Success! Public URL: {blob.public_url}")
    except Exception as acl_e:
        print(f"Failed to make blob public via blob.make_public(): {acl_e}")
        # Let's see if we can use predefined ACLs
        try:
            print("Trying upload with predefined ACL publicRead...")
            blob.upload_from_string(file_content, content_type="image/svg+xml", predefined_acl="publicRead")
            print(f"Success! Public URL: {blob.public_url}")
        except Exception as pre_e:
            print(f"Failed predefined ACL: {pre_e}")
            
except Exception as e:
    print(f"Error during upload process: {e}")
