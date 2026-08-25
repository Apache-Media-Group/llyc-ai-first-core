// frontend/src/components/ClientLoginScreen.tsx
import React, { useState, useEffect } from 'react';
import { 
  ShieldAlert, 
  Mail, 
  Lock, 
  UserPlus, 
  LogIn, 
  ArrowLeft, 
  AlertCircle, 
  CheckCircle2, 
  ExternalLink,
  ShieldCheck,
  KeyRound,
  RefreshCw
} from 'lucide-react';
import { 
  signInWithEmailAndPassword, 
  createUserWithEmailAndPassword, 
  signInWithPopup, 
  GoogleAuthProvider,
  signOut
} from 'firebase/auth';
import { auth } from '../firebase';
import type { TenantConfig } from './admin/types';
import { secureFetch } from '../services/apiClient';

interface ClientLoginScreenProps {
  tenant: TenantConfig;
  isAccessDenied: boolean;
  onClearAccessDenied: () => void;
  is2faRequired?: boolean;
  on2faSuccess?: () => void;
}

export const ClientLoginScreen: React.FC<ClientLoginScreenProps> = ({
  tenant,
  isAccessDenied,
  onClearAccessDenied,
  is2faRequired = false,
  on2faSuccess
}) => {
  const [activeTab, setActiveTab] = useState<'signin' | 'signup'>('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Estados para 2FA OTP
  const [otpCode, setOtpCode] = useState('');
  const [otpLoading, setOtpLoading] = useState(false);
  const [otpError, setOtpError] = useState<string | null>(null);
  const [otpSuccess, setOtpSuccess] = useState<string | null>(null);
  const [resendCooldown, setResendCooldown] = useState(0);
  const [otpSentOnce, setOtpSentOnce] = useState(false);

  const primaryColor = tenant.primary_color || '#E51D24';
  const secondaryColor = tenant.secondary_color || '#1C2541';

  // Reenvío automático de OTP al cargar la vista de 2FA
  useEffect(() => {
    if (is2faRequired && !otpSentOnce) {
      handleSendOtp();
      setOtpSentOnce(true);
    }
  }, [is2faRequired, otpSentOnce]);

  // Cuenta regresiva del reenvío de OTP
  useEffect(() => {
    if (resendCooldown <= 0) return;
    const timer = setInterval(() => {
      setResendCooldown((prev) => prev - 1);
    }, 1000);
    return () => clearInterval(timer);
  }, [resendCooldown]);

  const handleSendOtp = async () => {
    if (resendCooldown > 0 || otpLoading) return;
    
    setOtpLoading(true);
    setOtpError(null);
    setOtpSuccess(null);
    
    try {
      const res = await secureFetch('/api/v1/mcp-analytics/auth/otp/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tenant: tenant.tenant_id }),
      });
      
      if (res.ok) {
        setOtpSuccess('Código de seguridad enviado a tu dirección de correo electrónico.');
        setResendCooldown(60);
      } else {
        const data = await res.json();
        setOtpError(data.detail || 'No se pudo enviar el código de verificación.');
      }
    } catch (err) {
      console.error("Error al enviar OTP:", err);
      setOtpError('Error de red al enviar el código de seguridad.');
    } finally {
      setOtpLoading(false);
    }
  };

  const handleVerifyOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    if (otpCode.length !== 6 || otpLoading) return;

    setOtpLoading(true);
    setOtpError(null);
    setOtpSuccess(null);

    try {
      const res = await secureFetch('/api/v1/mcp-analytics/auth/otp/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tenant: tenant.tenant_id,
          code: otpCode
        })
      });

      if (res.ok) {
        setOtpSuccess('Identidad verificada con éxito. Accediendo...');
        setTimeout(() => {
          if (on2faSuccess) {
            on2faSuccess();
          }
        }, 1500);
      } else {
        const data = await res.json();
        setOtpError(data.detail || 'Código incorrecto o vencido.');
      }
    } catch (err) {
      console.error("Error al verificar OTP:", err);
      setOtpError('Error de red al verificar el código.');
    } finally {
      setOtpLoading(false);
    }
  };

  // 1. Google Auth para Clientes sin restricciones de subdominio LLYC
  const handleGoogleSignIn = async () => {
    setError(null);
    setSuccess(null);
    setLoading(true);
    try {
      const clientGoogleProvider = new GoogleAuthProvider();
      // No seteamos hd para permitir cualquier dominio corporativo o cuenta de Google
      await signInWithPopup(auth, clientGoogleProvider);
    } catch (err: any) {
      console.error("Fallo Google Client Auth:", err);
      if (err.code !== 'auth/popup-closed-by-user') {
        setError('Error al autenticar con Google: ' + (err.message || 'Error de conexión.'));
      }
    } finally {
      setLoading(false);
    }
  };

  // 2. Email & Password Sign In
  const handleEmailSignIn = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) return;
    
    setError(null);
    setSuccess(null);
    setLoading(true);

    try {
      await signInWithEmailAndPassword(auth, email.trim(), password);
    } catch (err: any) {
      console.error("Fallo Email Sign In:", err);
      let translatedError = 'Credenciales incorrectas o problema de conexión.';
      if (err.code === 'auth/user-not-found' || err.code === 'auth/wrong-password') {
        translatedError = 'El correo electrónico o la contraseña son incorrectos.';
      } else if (err.code === 'auth/invalid-email') {
        translatedError = 'El formato del correo electrónico no es válido.';
      } else if (err.code === 'auth/too-many-requests') {
        translatedError = 'Acceso bloqueado temporalmente por demasiados intentos fallidos. Intenta más tarde.';
      }
      setError(translatedError);
    } finally {
      setLoading(false);
    }
  };

  // 3. Email & Password Sign Up
  const handleEmailSignUp = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password || !confirmPassword) return;

    setError(null);
    setSuccess(null);

    if (password.length < 6) {
      setError('La contraseña debe tener al menos 6 caracteres.');
      return;
    }

    if (password !== confirmPassword) {
      setError('Las contraseñas no coinciden.');
      return;
    }

    setLoading(true);

    try {
      await createUserWithEmailAndPassword(auth, email.trim(), password);
      setSuccess('¡Cuenta registrada con éxito! Comprobando permisos de acceso...');
      setTimeout(() => {
        setSuccess(null);
      }, 3000);
    } catch (err: any) {
      console.error("Fallo Email Sign Up:", err);
      let translatedError = 'No se pudo crear la cuenta de usuario.';
      if (err.code === 'auth/email-already-in-use') {
        translatedError = 'Esta dirección de correo ya está registrada en la plataforma.';
      } else if (err.code === 'auth/invalid-email') {
        translatedError = 'El formato del correo electrónico no es válido.';
      } else if (err.code === 'auth/weak-password') {
        translatedError = 'La contraseña ingresada es demasiado débil.';
      }
      setError(translatedError);
    } finally {
      setLoading(false);
    }
  };

  // 4. Cerrar Sesión y reintentar
  const handleLogoutAndRetry = async () => {
    try {
      setLoading(true);
      await signOut(auth);
      onClearAccessDenied();
      setEmail('');
      setPassword('');
      setConfirmPassword('');
      setError(null);
    } catch (err) {
      console.error("Error al cerrar sesión:", err);
    } finally {
      setLoading(false);
    }
  };

  if (isAccessDenied) {
    // VISTA DE ACCESO DENEGADO (BRANDED PREMIUM)
    return (
      <div className="fixed inset-0 bg-[#060c18] flex items-center justify-center p-5 z-[1000] overflow-y-auto">
        {/* Fondo con degradado animado y color secundario del cliente */}
        <div 
          className="absolute inset-0 opacity-20 pointer-events-none transition-all duration-1000"
          style={{
            background: `radial-gradient(circle at center, ${primaryColor} 0%, transparent 70%)`
          }}
        />

        <div className="bg-white/5 border border-white/10 rounded-3xl p-8 max-w-md w-full shadow-2xl relative backdrop-blur-md text-center">
          <div className="w-16 h-16 rounded-2xl bg-red/10 border border-red/20 flex items-center justify-center text-red mx-auto mb-6">
            <ShieldAlert className="w-8 h-8" />
          </div>

          {tenant.logo_url && (
            <img src={tenant.logo_url} alt={tenant.tenant_name} className="h-10 object-contain mb-4 mx-auto max-w-[180px]" />
          )}

          <h2 className="text-xl font-black text-white tracking-tight mb-2">Acceso Restringido</h2>
          <p className="text-[11px] text-mid mb-6 uppercase tracking-wider font-semibold text-white/50">
            {tenant.tenant_name}
          </p>

          <div className="p-4 bg-red-500/10 border border-red-500/20 text-red-400 rounded-xl flex items-start gap-2.5 text-xs text-left mb-6 font-medium leading-relaxed">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            <span>
              Tu cuenta de correo electrónico <strong>{auth.currentUser?.email}</strong> no está autorizada para visualizar este dashboard. El acceso está restringido por listas de control (ACL).
            </span>
          </div>

          <div className="text-xs text-mid text-left space-y-3 mb-8 bg-white/[0.02] border border-white/5 p-4 rounded-xl">
            <p className="font-bold text-white/80">¿Cómo puedo obtener acceso?</p>
            <ul className="list-disc pl-4 space-y-1.5 text-mid/80 text-[11px]">
              <li>Tu correo debe estar explícitamente añadido por tu consultor de LLYC.</li>
              <li>O debes iniciar sesión con una cuenta bajo tu dominio corporativo autorizado.</li>
            </ul>
          </div>

          <div className="space-y-3">
            <a 
              href={`mailto:${tenant.support_email || 'intelligence.mcp@llyc.global'}?subject=Acceso%20MCP%20-%20${tenant.tenant_name}`}
              className="flex items-center justify-center gap-2 w-full py-3 px-4 border border-white/10 hover:border-white/20 bg-white/5 hover:bg-white/10 text-white rounded-xl text-xs font-bold transition-all"
            >
              <span>Contactar Soporte</span>
              <ExternalLink className="w-3.5 h-3.5" />
            </a>

            <button
              onClick={handleLogoutAndRetry}
              disabled={loading}
              className="flex items-center justify-center gap-2 w-full py-3 px-4 text-white rounded-xl text-xs font-black transition-all"
              style={{ backgroundColor: primaryColor }}
            >
              <ArrowLeft className="w-4 h-4" />
              <span>Usar otra cuenta</span>
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (is2faRequired) {
    // VISTA DE VERIFICACIÓN 2FA OTP (BRANDED PREMIUM)
    return (
      <div className="fixed inset-0 bg-[#060c18] flex items-center justify-center p-5 z-[1000] overflow-y-auto">
        {/* Fondo con degradado animado y color secundario del cliente */}
        <div 
          className="absolute inset-0 opacity-20 pointer-events-none transition-all duration-1000"
          style={{
            background: `radial-gradient(circle at center, ${primaryColor} 0%, transparent 70%)`
          }}
        />

        <div className="bg-white/5 border border-white/10 rounded-3xl p-8 max-w-md w-full shadow-2xl relative backdrop-blur-md text-center">
          {/* Logo o Marca del Inquilino */}
          <div className="mb-6">
            {tenant.logo_url ? (
              <img src={tenant.logo_url} alt={tenant.tenant_name} className="h-10 object-contain mb-4 mx-auto max-w-[180px]" />
            ) : (
              <div className="text-white font-black text-2xl mb-3 tracking-tighter" style={{ color: primaryColor }}>
                {tenant.tenant_name}
              </div>
            )}
            <p className="text-[10px] text-mid uppercase tracking-widest font-semibold text-white/40 mt-1">
              Marketing Control Panel
            </p>
          </div>

          {/* Icono de Escudo/2FA con micro-animación */}
          <div className="relative w-16 h-16 mx-auto mb-6 flex items-center justify-center">
            <div 
              className="absolute inset-0 rounded-2xl opacity-10 animate-pulse"
              style={{ backgroundColor: primaryColor }}
            />
            <div 
              className="relative w-14 h-16 rounded-2xl bg-white/5 border flex items-center justify-center text-white"
              style={{ borderColor: `${primaryColor}40` }}
            >
              <ShieldCheck className="w-8 h-8" style={{ color: primaryColor }} />
            </div>
          </div>

          <h2 className="text-xl font-black text-white tracking-tight mb-2">Verificación de Seguridad</h2>
          <p className="text-xs text-mid mb-6 leading-relaxed">
            Hemos enviado un código OTP de 6 dígitos a tu dirección de correo electrónico vinculada: <strong className="text-white font-semibold">{auth.currentUser?.email || email}</strong>
          </p>

          {/* Alertas */}
          {otpError && (
            <div className="p-3.5 bg-red-500/10 border border-red-500/20 text-red-400 rounded-xl flex items-start gap-2.5 text-xs text-left mb-5 leading-normal font-medium">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{otpError}</span>
            </div>
          )}

          {otpSuccess && (
            <div className="p-3.5 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 rounded-xl flex items-start gap-2.5 text-xs text-left mb-5 leading-normal font-medium">
              <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5 animate-pulse" />
              <span>{otpSuccess}</span>
            </div>
          )}

          {/* Formulario de Código OTP */}
          <form onSubmit={handleVerifyOtp} className="space-y-5">
            <div>
              <label className="block text-[9px] font-black uppercase tracking-wider text-white/50 text-left mb-2">
                Código de 6 dígitos
              </label>
              <div className="relative">
                <KeyRound className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-mid" />
                <input 
                  type="text"
                  value={otpCode}
                  onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  placeholder="000000"
                  required
                  maxLength={6}
                  disabled={otpLoading}
                  className="w-full bg-[#0a1829]/60 border border-white/10 rounded-xl pl-12 pr-4 py-3 text-2xl font-black text-white tracking-[0.5em] font-mono focus:outline-none focus:border-white/30 transition-all text-center placeholder:opacity-20 placeholder:tracking-normal"
                  style={{
                    caretColor: primaryColor,
                  }}
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={otpLoading || otpCode.length !== 6}
              className="w-full py-3 rounded-xl text-white text-xs font-black flex items-center justify-center gap-2 hover:opacity-90 active:scale-[0.99] transition-all disabled:opacity-30 disabled:scale-100"
              style={{ backgroundColor: primaryColor }}
            >
              {otpLoading ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  <span>Verificando...</span>
                </>
              ) : (
                <>
                  <ShieldCheck className="w-4 h-4" />
                  <span>Verificar Código</span>
                </>
              )}
            </button>
          </form>

          {/* Reenvío de código */}
          <div className="mt-6 flex flex-col items-center gap-3">
            {resendCooldown > 0 ? (
              <p className="text-[11px] text-mid/60 font-semibold flex items-center gap-1.5">
                <RefreshCw className="w-3.5 h-3.5 text-mid/40 animate-spin" />
                <span>¿No recibiste el correo? Solicitar reenvío en <strong className="text-white">{resendCooldown}s</strong></span>
              </p>
            ) : (
              <button
                onClick={handleSendOtp}
                disabled={otpLoading}
                className="text-[11px] font-bold uppercase tracking-wider text-mid hover:text-white transition-colors flex items-center gap-1.5"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${otpLoading ? 'animate-spin' : ''}`} />
                <span>Reenviar código de seguridad</span>
              </button>
            )}

            <button
              onClick={handleLogoutAndRetry}
              disabled={otpLoading}
              className="inline-flex items-center gap-1.5 text-[10px] text-mid/55 hover:text-white uppercase tracking-wider font-semibold transition-colors mt-2"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Usar otra cuenta / Salir</span>
            </button>
          </div>
        </div>
      </div>
    );
  }

  // VISTA DE LOGIN NORMAL (CON ACCENT COLORS)
  return (
    <div className="fixed inset-0 bg-[#060c18] flex items-center justify-center p-5 z-[1000] overflow-y-auto">
      {/* Luces y degradados ambientales de fondo */}
      <div 
        className="absolute inset-0 opacity-10 pointer-events-none transition-all duration-1000"
        style={{
          background: `radial-gradient(circle at 70% 20%, ${primaryColor} 0%, transparent 60%), radial-gradient(circle at 20% 80%, ${secondaryColor} 0%, transparent 60%)`
        }}
      />

      <div className="bg-white/5 border border-white/10 rounded-3xl p-8 max-w-md w-full shadow-2xl relative backdrop-blur-md">
        {/* Encabezado con Logo y Marca */}
        <div className="text-center mb-6">
          {tenant.logo_url ? (
            <img src={tenant.logo_url} alt={tenant.tenant_name} className="h-10 object-contain mb-4 mx-auto max-w-[180px]" />
          ) : (
            <div className="text-white font-black text-3xl mb-3 tracking-tighter" style={{ color: primaryColor }}>
              {tenant.tenant_name}
            </div>
          )}
          <h2 className="text-lg font-black text-white tracking-tight">Acceso al Dashboard</h2>
          <p className="text-[10px] text-mid uppercase tracking-widest font-semibold text-white/40 mt-1">
            Marketing Control Panel
          </p>
        </div>

        {/* Notificaciones */}
        {error && (
          <div className="p-3.5 bg-red-500/10 border border-red-500/20 text-red-400 rounded-xl flex items-start gap-2 text-xs mb-4 leading-normal">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        {success && (
          <div className="p-3.5 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 rounded-xl flex items-start gap-2 text-xs mb-4 leading-normal">
            <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5 animate-pulse" />
            <span>{success}</span>
          </div>
        )}

        {/* Tabs de Selección (Iniciar Sesión vs Crear Cuenta) */}
        <div className="flex border-b border-white/10 mb-5 text-center">
          <button
            onClick={() => { setActiveTab('signin'); setError(null); }}
            className={`flex-1 pb-3 text-xs font-black tracking-wider uppercase transition-colors ${
              activeTab === 'signin' ? 'text-white border-b-2' : 'text-mid hover:text-white/80'
            }`}
            style={{ borderBottomColor: activeTab === 'signin' ? primaryColor : 'transparent' }}
          >
            Iniciar Sesión
          </button>
          <button
            onClick={() => { setActiveTab('signup'); setError(null); }}
            className={`flex-1 pb-3 text-xs font-black tracking-wider uppercase transition-colors ${
              activeTab === 'signup' ? 'text-white border-b-2' : 'text-mid hover:text-white/80'
            }`}
            style={{ borderBottomColor: activeTab === 'signup' ? primaryColor : 'transparent' }}
          >
            Crear Cuenta
          </button>
        </div>

        {/* Formularios según pestaña */}
        {activeTab === 'signin' ? (
          <form onSubmit={handleEmailSignIn} className="space-y-3.5">
            <div>
              <label className="block text-[9px] font-bold uppercase tracking-wider text-mid mb-1.5">Correo Electrónico</label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-mid" />
                <input 
                  type="email" 
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="ejemplo@empresa.com"
                  required
                  className="w-full bg-[#0a1829]/60 border border-white/10 rounded-xl pl-9 pr-4 py-2.5 text-xs text-white focus:outline-none focus:border-white/30 transition-colors"
                />
              </div>
            </div>

            <div>
              <label className="block text-[9px] font-bold uppercase tracking-wider text-mid mb-1.5">Contraseña</label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-mid" />
                <input 
                  type="password" 
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  required
                  className="w-full bg-[#0a1829]/60 border border-white/10 rounded-xl pl-9 pr-4 py-2.5 text-xs text-white focus:outline-none focus:border-white/30 transition-colors"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 rounded-xl text-white text-xs font-bold flex items-center justify-center gap-1.5 hover:opacity-90 active:scale-[0.99] transition-all disabled:opacity-50 mt-4"
              style={{ backgroundColor: primaryColor }}
            >
              <LogIn className="w-4 h-4" />
              <span>{loading ? 'Accediendo...' : 'Iniciar Sesión'}</span>
            </button>
          </form>
        ) : (
          <form onSubmit={handleEmailSignUp} className="space-y-3.5">
            <div>
              <label className="block text-[9px] font-bold uppercase tracking-wider text-mid mb-1.5">Correo Electrónico Corporativo</label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-mid" />
                <input 
                  type="email" 
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="ejemplo@empresa.com"
                  required
                  className="w-full bg-[#0a1829]/60 border border-white/10 rounded-xl pl-9 pr-4 py-2.5 text-xs text-white focus:outline-none focus:border-white/30 transition-colors"
                />
              </div>
              <p className="text-[10px] text-mid mt-1 font-medium">Usa preferiblemente tu dirección de correo de la organización.</p>
            </div>

            <div>
              <label className="block text-[9px] font-bold uppercase tracking-wider text-mid mb-1.5">Contraseña</label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-mid" />
                <input 
                  type="password" 
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Mínimo 6 caracteres"
                  required
                  className="w-full bg-[#0a1829]/60 border border-white/10 rounded-xl pl-9 pr-4 py-2.5 text-xs text-white focus:outline-none focus:border-white/30 transition-colors"
                />
              </div>
            </div>

            <div>
              <label className="block text-[9px] font-bold uppercase tracking-wider text-mid mb-1.5">Confirmar Contraseña</label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-mid" />
                <input 
                  type="password" 
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="Repite tu contraseña"
                  required
                  className="w-full bg-[#0a1829]/60 border border-white/10 rounded-xl pl-9 pr-4 py-2.5 text-xs text-white focus:outline-none focus:border-white/30 transition-colors"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 rounded-xl text-white text-xs font-bold flex items-center justify-center gap-1.5 hover:opacity-90 active:scale-[0.99] transition-all disabled:opacity-50 mt-4"
              style={{ backgroundColor: primaryColor }}
            >
              <UserPlus className="w-4 h-4" />
              <span>{loading ? 'Creando cuenta...' : 'Crear Cuenta'}</span>
            </button>
          </form>
        )}

        {/* Separador O */}
        <div className="relative flex py-5 items-center">
          <div className="flex-grow border-t border-white/10"></div>
          <span className="flex-shrink mx-3 text-[10px] uppercase font-bold text-mid tracking-widest">O accede con</span>
          <div className="flex-grow border-t border-white/10"></div>
        </div>

        {/* Google OAuth (Botón Premium) */}
        <button
          onClick={handleGoogleSignIn}
          disabled={loading}
          className="w-full py-2.5 border border-white/10 hover:border-white/20 bg-white/5 hover:bg-white/10 text-white rounded-xl text-xs font-bold flex items-center justify-center gap-2.5 transition-all group disabled:opacity-50"
        >
          <svg className="w-4.5 h-4.5 transition-transform group-hover:scale-105" viewBox="0 0 24 24" width="18" height="18">
            <path
              fill="#EA4335"
              d="M12 5.04c1.62 0 3.08.56 4.22 1.66l3.15-3.15C17.45 1.49 14.96 1 12 1 7.43 1 3.42 3.11 1.61 6.08l5.14 2.92C7.36 7.15 9.49 5.04 12 5.04z"
            />
            <path
              fill="#4285F4"
              d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31l3.4 2.64c2-1.84 3.45-4.54 3.45-7.96z"
            />
            <path
              fill="#FBBC05"
              d="M5.84 14.09c-.21-.63-.33-1.3-.33-2.09s.12-1.46.33-2.09V7.08H1.61A11.97 11.97 0 0 0 0 12c0 1.61.32 3.16.89 4.58l4.95-2.49z"
            />
            <path
              fill="#34A853"
              d="M12 23c3.24 0 5.95-1.08 7.93-2.91l-3.4-2.64c-.95.63-2.16 1.01-3.53 1.01-2.51 0-4.64-2.11-5.4-5.04l-4.95 2.49C3.42 19.89 7.43 23 12 23z"
            />
          </svg>
          <span>Continuar con Google</span>
        </button>

        {/* Enlace a Portal Base de LLYC */}
        <div className="mt-6 text-center">
          <a
            href="/"
            className="inline-flex items-center gap-1 text-[10px] text-mid hover:text-white uppercase tracking-wider font-semibold transition-colors"
          >
            <ArrowLeft className="w-3 h-3" />
            <span>Volver al inicio</span>
          </a>
        </div>
      </div>
    </div>
  );
};
