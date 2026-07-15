# backend/update_firestore_logos.py
import os
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
from google.cloud import storage

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/Users/santiagorovira/media_impact/media-impact-test-keys.json"
project_id = "llyc-ai-first-core"
bucket_name = "llyc-mcp-public-assets"

# Initialize Firebase and Storage
if not firebase_admin._apps:
    cred = credentials.ApplicationDefault()
    firebase_admin.initialize_app(cred, {
        'projectId': project_id,
    })

db = firestore.client()
gcs_client = storage.Client(project=project_id)
bucket = gcs_client.bucket(bucket_name)

# Read the local sanitas logo
logo_path = "/Users/santiagorovira/media_impact/frontend/public/logo_sanitas.svg"
if os.path.exists(logo_path):
    with open(logo_path, "rb") as f:
        file_content = f.read()
else:
    raise FileNotFoundError("Local Sanitas SVG logo not found!")

try:
    # 1. Upload for sanitas
    print("Uploading logos/sanitas.svg to GCS...")
    blob_sanitas = bucket.blob("logos/sanitas.svg")
    blob_sanitas.upload_from_string(file_content, content_type="image/svg+xml")
    blob_sanitas.make_public()
    url_sanitas = blob_sanitas.public_url
    print(f"Uploaded! Public URL: {url_sanitas}")

    # 2. Upload for test
    print("Uploading logos/test.svg to GCS...")
    blob_test = bucket.blob("logos/test.svg")
    blob_test.upload_from_string(file_content, content_type="image/svg+xml")
    blob_test.make_public()
    url_test = blob_test.public_url
    print(f"Uploaded! Public URL: {url_test}")

    # 3. Update Firestore documents
    print("Updating Firestore records...")
    db.collection("tenants").document("sanitas").update({"logo_url": url_sanitas})
    print("Updated sanitas logo_url in Firestore!")

    db.collection("tenants").document("test").update({"logo_url": url_test})
    print("Updated test logo_url in Firestore!")

except Exception as e:
    print(f"Error updating Firestore or uploading logos: {e}")
