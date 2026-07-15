# backend/test_firestore.py
import os
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/Users/santiagorovira/media_impact/media-impact-test-keys.json"
project_id = "llyc-ai-first-core"

if not firebase_admin._apps:
    cred = credentials.ApplicationDefault()
    firebase_admin.initialize_app(cred, {
        'projectId': project_id,
    })

db = firestore.client()

try:
    tenants_ref = db.collection("tenants")
    docs = tenants_ref.stream()
    print("Tenants in Firestore:")
    for doc in docs:
        print(f"ID: {doc.id}")
        data = doc.to_dict()
        for k, v in data.items():
            print(f"  {k}: {v}")
except Exception as e:
    print(f"Error: {e}")
