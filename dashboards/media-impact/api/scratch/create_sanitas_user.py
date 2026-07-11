# backend/scratch/create_sanitas_user.py
import os
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

# Configuración del entorno de Firestore de producción
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/Users/santiagorovira/media_impact/media-impact-test-keys.json"
project_id = "llyc-ai-first-core"

if not firebase_admin._apps:
    cred = credentials.ApplicationDefault()
    firebase_admin.initialize_app(cred, {
        'projectId': project_id,
    })

db = firestore.client()

def whitelist_sanitas_users():
    tenant_id = "sanitas"
    doc_ref = db.collection("tenants").document(tenant_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        print(f"❌ Error: El tenant '{tenant_id}' no existe en Firestore.")
        return
        
    print(f"🔍 Tenant '{tenant_id}' encontrado.")
    
    # Definición de correos y dominios autorizados para Sanitas
    authorized_emails = [
        "usuario.sanitas@gmail.com",
        "test.sanitas@llyc.global",
        "developer@llyc.global"
    ]
    
    authorized_domains = [
        "sanitas.es",
        "sanitas.com"
    ]
    
    # Actualizar documento en Firestore
    doc_ref.update({
        "authorized_emails": authorized_emails,
        "authorized_domains": authorized_domains
    })
    
    print("✅ Firestore actualizado con éxito:")
    print(f"  📧 Correos Autorizados: {authorized_emails}")
    print(f"  🌐 Dominios Autorizados: {authorized_domains}")

if __name__ == "__main__":
    whitelist_sanitas_users()
