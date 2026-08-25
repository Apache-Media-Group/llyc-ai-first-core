// frontend/src/components/WelcomeScreen.tsx
import React, { useState } from 'react';
import { ShieldCheck, Users, Lock, ChevronRight, AlertCircle, CheckCircle2, ArrowRight } from 'lucide-react';
import { signInWithPopup } from 'firebase/auth';
import { auth, googleProvider } from '../firebase';
import { secureFetch } from '../services/apiClient';

interface WelcomeScreenProps {
  onSelectGA4: () => void;
  onSelectAdobe: (creds: any) => void;
  onSelectPeec: (apiKey: string) => void;
  onFileUpload: (file: File) => void;
  tenant?: {
    tenant_id: string;
    tenant_name: string;
    logo_url: string;
    primary_color: string;
  };
}

export const WelcomeScreen: React.FC<WelcomeScreenProps> = ({ 
  tenant
}) => {
  const [showTenantPrompt, setShowTenantPrompt] = useState(false);
  const [workspaceId, setWorkspaceId] = useState('');
  
  const [authError, setAuthError] = useState<string | null>(null);
  const [authSuccess, setAuthSuccess] = useState(false);
  const [signingIn, setSigningIn] = useState(false);
  
  const [validatingTenant, setValidatingTenant] = useState(false);
  const [tenantError, setTenantError] = useState<string | null>(null);

  // REAL Google OAuth (Sign-In with Google via Firebase Auth)
  const handleGoogleSignIn = async () => {
    setAuthError(null);
    setAuthSuccess(false);
    setSigningIn(true);

    try {
      // 1. Disparar el Popup oficial de Google Sign-In
      const result = await signInWithPopup(auth, googleProvider);
      const email = result.user.email;

      // 2. Validación estricta del dominio corporativo de LLYC en el backend/frontend
      if (email && (email.toLowerCase().endsWith('@llyc.global') || email.toLowerCase().endsWith('@llyc.ai'))) {
        setAuthSuccess(true);
        // Guardar email del administrador autenticado para auditoría o visualización
        localStorage.setItem('admin_user_email', email.toLowerCase());
        
        setTimeout(() => {
          window.location.hash = '#admin';
        }, 1200);
      } else {
        // Cierre de sesión inmediato por seguridad si no cumple el dominio corporativo
        await auth.signOut();
        setAuthError('Acceso denegado: Tu cuenta de Google no pertenece al dominio corporativo @llyc.global o @llyc.ai.');
      }
    } catch (err: any) {
      console.error("Fallo de Google Auth:", err);
      // Ignorar cierres del popup por el usuario
      if (err.code !== 'auth/popup-closed-by-user') {
        setAuthError('Error de autenticación: ' + (err.message || 'No se pudo conectar con los servidores de Google.'));
      }
    } finally {
      setSigningIn(false);
    }
  };

  const handleWorkspaceSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setTenantError(null);
    const cleanId = workspaceId.toLowerCase().replace(/\s+/g, '-').trim();
    if (!cleanId) return;

    try {
      setValidatingTenant(true);
      const res = await secureFetch(`/api/v1/mcp-analytics/tenant/config?tenant=${cleanId}`);
      if (res.ok) {
        const data = await res.json();
        // Si el tenant existe en Firestore o es uno de los fallbacks permitidos, redireccionar
        if (data.tenant_id === cleanId) {
          window.location.href = `/?tenant=${cleanId}`;
          return;
        }
      }
      
      // Si no existe, mostrar error estricto de organización no registrada
      setTenantError(`Workspace ID '${cleanId}' no registrado. Ponte en contacto con tu consultor de LLYC.`);
    } catch (err) {
      setTenantError("Error de conexión al validar tu organización.");
    } finally {
      setValidatingTenant(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-navy flex items-center justify-center p-5 z-[1000]">
      {/* FONDO DE LLYC DEGRADADO */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-red/10 via-navy to-navy pointer-events-none"></div>

      <div className="bg-white/5 border border-white/10 rounded-3xl p-10 max-w-lg w-full shadow-2xl relative backdrop-blur-md text-center">
        {/* LOGO DINÁMICO */}
        {tenant?.logo_url ? (
          <img src={tenant.logo_url} alt={tenant.tenant_name} className="h-12 object-contain mb-8 mx-auto max-w-[200px]" />
        ) : (
          <div className="text-red font-black text-4xl mb-8 tracking-tighter">LLYC</div>
        )}
        
        <h2 className="text-2xl font-black text-white tracking-tight mb-2">Portal Analítico Inteligente</h2>
        <p className="text-xs text-mid mb-10 uppercase tracking-widest font-semibold text-white/60">Marketing Control Panel 2026</p>

        {/* MENSAJES DE ERROR O ÉXITO DEL REAL GOOGLE AUTH */}
        {authError && (
          <div className="p-4 bg-red-500/10 border border-red-500/20 text-red-400 rounded-xl flex items-start gap-2.5 text-xs text-left mb-6">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            <span>{authError}</span>
          </div>
        )}

        {authSuccess && (
          <div className="p-4 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 rounded-xl flex items-start gap-2.5 text-xs text-left mb-6">
            <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5 animate-bounce" />
            <span>¡Superadmin verificado! Redireccionando al panel de control...</span>
          </div>
        )}

        {!showTenantPrompt ? (
          /* PANTALLA PRINCIPAL: 2 BOTONES EXCLUSIVOS */
          <div className="space-y-4 text-left">
            <button 
              onClick={() => setShowTenantPrompt(true)}
              className="w-full bg-white/5 border border-white/10 hover:border-white/30 hover:bg-white/[0.08] p-6 rounded-2xl flex items-center justify-between transition-all group group-hover:scale-[1.01]"
            >
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 rounded-xl bg-white/5 flex items-center justify-center text-white/80">
                  <Users className="w-6 h-6" />
                </div>
                <div>
                  <h3 className="font-black text-sm text-white">Portal del Cliente</h3>
                  <p className="text-[11px] text-mid mt-0.5">Accede al Dashboard con tu identificador de cliente</p>
                </div>
              </div>
              <ChevronRight className="w-5 h-5 text-mid group-hover:text-white transition-colors" />
            </button>

            <button 
              onClick={handleGoogleSignIn}
              disabled={signingIn || authSuccess}
              className="w-full bg-red/10 border border-red/20 hover:bg-red/20 p-6 rounded-2xl flex items-center justify-between transition-all group disabled:opacity-50"
            >
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 rounded-xl bg-red flex items-center justify-center text-white">
                  <Lock className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="font-black text-sm text-white">
                    {signingIn ? 'Autenticando...' : 'Admin'}
                  </h3>
                  <p className="text-[11px] text-red/80 mt-0.5">Acceso exclusivo para consultores de LLYC</p>
                </div>
              </div>
              <ChevronRight className="w-5 h-5 text-red group-hover:text-white transition-colors" />
            </button>
          </div>
        ) : (
          /* FORMULARIO DE ACCESO DE INQUILINO (TENANT ENTRANCE) */
          <div className="text-left space-y-4">
            <div className="flex items-center gap-2 mb-2">
              <button 
                onClick={() => { setShowTenantPrompt(false); setWorkspaceId(''); }}
                className="text-xs font-bold text-mid hover:text-white transition-colors"
              >
                ← Volver al Portal
              </button>
            </div>

            <div className="text-center mb-6">
              <h3 className="font-black text-white text-base">Identifica tu Organización</h3>
              <p className="text-xs text-mid mt-1">Introduce el Workspace ID o subdominio asignado por LLYC</p>
            </div>

            {tenantError && (
              <div className="p-4 bg-red-500/10 border border-red-500/20 text-red-400 rounded-xl flex items-start gap-2.5 text-xs text-left mb-4">
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                <span>{tenantError}</span>
              </div>
            )}

            <form onSubmit={handleWorkspaceSubmit} className="space-y-4">
              <div>
                <label className="block text-[10px] font-bold uppercase tracking-wider text-mid mb-1">Identificador de Organización (Tenant ID)</label>
                <div className="flex gap-2">
                  <input 
                    type="text" 
                    value={workspaceId}
                    onChange={(e) => setWorkspaceId(e.target.value)}
                    placeholder="ej: mi-organizacion"
                    required
                    disabled={validatingTenant}
                    className="flex-1 bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-xs text-white focus:outline-none focus:border-red transition-colors font-semibold disabled:opacity-50"
                  />
                  <button 
                    type="submit"
                    disabled={validatingTenant}
                    className="w-12 h-12 bg-red text-white rounded-xl hover:bg-red/90 flex items-center justify-center transition-colors shrink-0 shadow-lg shadow-red/25 disabled:opacity-50"
                  >
                    <ArrowRight className="w-5 h-5" />
                  </button>
                </div>
              </div>
            </form>
          </div>
        )}

        {/* PIE DE PORTAL */}
        <div className="mt-12 flex items-center justify-center gap-2 text-[10px] text-mid font-bold uppercase tracking-widest">
          <ShieldCheck className="w-3.5 h-3.5 text-mid" />
          LLYC Analytics · Secure Access Compliant
        </div>
      </div>
    </div>
  );
};
