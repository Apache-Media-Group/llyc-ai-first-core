// frontend/src/firebase.ts
import { initializeApp } from 'firebase/app';
import { getAuth, GoogleAuthProvider } from 'firebase/auth';

// Configuración del Web SDK de Firebase 100% dinámica y agnóstica de proyecto
const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID
};

// Inicializar Firebase
const app = initializeApp(firebaseConfig);

// Inicializar y exportar servicios de Auth
export const auth = getAuth(app);

// Configurar el proveedor de Google OAuth
export const googleProvider = new GoogleAuthProvider();

// Fuerza a Google a priorizar o sugerir cuentas bajo el dominio corporativo llyc.global en el selector
googleProvider.setCustomParameters({ hd: 'llyc.global' });
