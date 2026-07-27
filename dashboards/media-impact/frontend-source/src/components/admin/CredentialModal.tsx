// frontend/src/components/admin/CredentialModal.tsx
import React, { useState, useEffect } from 'react';
import { Key, RefreshCw, Save, CheckSquare } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { secureFetch } from '../../services/apiClient';

interface CredentialModalProps {
  isOpen: boolean;
  onClose: () => void;
  tenantId: string | null;
  configuredSecrets?: Record<string, boolean>;
  forceEditMode?: boolean;
  onSaveSuccess: (message: string) => void;
  onSaveError: (error: string) => void;
}

export const CredentialModal: React.FC<CredentialModalProps> = ({
  isOpen,
  onClose,
  tenantId,
  configuredSecrets = {},
  forceEditMode = false,
  onSaveSuccess,
  onSaveError,
}) => {
  const [secretType, setSecretType] = useState('brandlight-key');
  const [secretValue, setSecretValue] = useState('');
  const [saving, setSaving] = useState(false);
  const [redeploying, setRedeploying] = useState(false);
  const [isEditMode, setIsEditMode] = useState(false);

  // Estados de Adobe Analytics
  const [adobeClientId, setAdobeClientId] = useState('');
  const [adobeClientSecret, setAdobeClientSecret] = useState('');
  const [adobeOrgId, setAdobeOrgId] = useState('');
  const [adobeCompaniesList, setAdobeCompaniesList] = useState<any[]>([]);
  const [adobeSuitesList, setAdobeSuitesList] = useState<any[]>([]);
  const [validatingAdobe, setValidatingAdobe] = useState(false);
  const [selectedAdobeCompany, setSelectedAdobeCompany] = useState('');
  const [selectedAdobeSuite, setSelectedAdobeSuite] = useState('');

  // Estados de Peec.ai
  const [peecProjectsList, setPeecProjectsList] = useState<any[]>([]);
  const [validatingPeec, setValidatingPeec] = useState(false);
  const [selectedPeecProject, setSelectedPeecProject] = useState('');

  // Estados de GA4 (Nueva arquitectura multichoice)
  const [selectedGa4Connection, setSelectedGa4Connection] = useState('');
  const [ga4PropertiesList, setGa4PropertiesList] = useState<any[]>([]);
  const [loadingGa4Properties, setLoadingGa4Properties] = useState(false);
  const [selectedGa4Properties, setSelectedGa4Properties] = useState<string[]>([]);

  // Estados de GA4 (OAuth Tradicional)
  const [ga4OauthAccountsList, setGa4OauthAccountsList] = useState<any[]>([]);
  const [ga4OauthPropertiesList, setGa4OauthPropertiesList] = useState<any[]>([]);
  const [validatingGa4Oauth, setValidatingGa4Oauth] = useState(false);
  const [selectedGa4OauthAccount, setSelectedGa4OauthAccount] = useState('');
  const [selectedGa4OauthProperty, setSelectedGa4OauthProperty] = useState('');

  // Fetch Conexiones Globales de GA4
  const { data: ga4Connections = [] } = useQuery({
    queryKey: ['ga4Connections'],
    queryFn: async () => {
      const res = await secureFetch('/api/v1/mcp-analytics/connections/ga4');
      if (!res.ok) return [];
      return res.json();
    },
    enabled: isOpen && secretType === 'ga4-creds'
  });

  // Fetch Propiedades cuando se selecciona una conexión
  useEffect(() => {
    if (selectedGa4Connection) {
      const fetchProperties = async () => {
        setLoadingGa4Properties(true);
        try {
          const res = await secureFetch(`/api/v1/mcp-analytics/connections/ga4/${selectedGa4Connection}/properties`);
          if (res.ok) {
            const data = await res.json();
            // Flatten accounts and properties
            const props: any[] = [];
            if (data.accounts) {
              data.accounts.forEach((acc: any) => {
                if (acc.properties) {
                  acc.properties.forEach((p: any) => {
                    props.push({ ...p, account_name: acc.account_name });
                  });
                }
              });
            }
            setGa4PropertiesList(props);
          }
        } catch (err) {
          console.error('Error fetching GA4 properties:', err);
        } finally {
          setLoadingGa4Properties(false);
        }
      };
      fetchProperties();
    } else {
      setGa4PropertiesList([]);
    }
  }, [selectedGa4Connection]);

  // Resetear estados cuando cambia el tenant o se abre el modal
  useEffect(() => {
    if (isOpen) {
      // Determine the first option to select
      let firstOption = '';
      if (forceEditMode) {
        if (configuredSecrets['brandlight-key']) firstOption = 'brandlight-key';
        else if (configuredSecrets['peec-key']) firstOption = 'peec-key';
        else if (configuredSecrets['ga4-creds']) firstOption = 'ga4-creds';
        else if (configuredSecrets['ga4-oauth']) firstOption = 'ga4-oauth';
        else if (configuredSecrets['adobe-creds']) firstOption = 'adobe-creds';
      } else {
        if (!configuredSecrets['brandlight-key']) firstOption = 'brandlight-key';
        else if (!configuredSecrets['peec-key']) firstOption = 'peec-key';
        else if (!configuredSecrets['ga4-creds']) firstOption = 'ga4-creds';
        else if (!configuredSecrets['ga4-oauth']) firstOption = 'ga4-oauth';
        else if (!configuredSecrets['adobe-creds']) firstOption = 'adobe-creds';
      }

      setSecretType(firstOption);
      setSecretValue('');
      setAdobeClientId('');
      setAdobeClientSecret('');
      setAdobeOrgId('');
      setAdobeCompaniesList([]);
      setAdobeSuitesList([]);
      setSelectedAdobeCompany('');
      setSelectedAdobeSuite('');
      
      setSelectedGa4Connection('');
      setGa4PropertiesList([]);
      setSelectedGa4Properties([]);
      
      setGa4OauthAccountsList([]);
      setGa4OauthPropertiesList([]);
      setSelectedGa4OauthAccount('');
      setSelectedGa4OauthProperty('');
      
      setPeecProjectsList([]);
      setSelectedPeecProject('');
      
      setRedeploying(false);
      setSaving(false);
      setIsEditMode(false);
    }
  }, [isOpen, tenantId, forceEditMode, configuredSecrets]);
  
  // Resetea isEditMode cuando cambia el tipo de secreto o fuerza la edición si corresponde
  useEffect(() => {
    if (forceEditMode && configuredSecrets[secretType]) {
      handleEditConfig();
    } else {
      setIsEditMode(false);
      setSecretValue('');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [secretType]);

  if (!isOpen || !tenantId) return null;

  const handleToggleGa4Property = (propertyId: string) => {
    setSelectedGa4Properties(prev => 
      prev.includes(propertyId) 
        ? prev.filter(id => id !== propertyId) 
        : [...prev, propertyId]
    );
  };

  const handleValidateGa4OauthCredentials = async () => {
    if (!secretValue) {
      alert("Por favor pega el JSON de credenciales OAuth de Google para validar.");
      return;
    }
    
    try {
      setValidatingGa4Oauth(true);
      const res = await secureFetch(`/api/v1/mcp-analytics/admin/tenants/validate-ga4-credentials`, {
        method: 'POST',
        body: JSON.stringify({
          credentials_json: secretValue.trim()
        })
      });
      
      if (res.ok) {
        const data = await res.json();
        setGa4OauthAccountsList(data.accounts || []);
        setGa4OauthPropertiesList(data.properties || []);
        
        if (data.accounts && data.accounts.length > 0) {
          setSelectedGa4OauthAccount(data.accounts[0].id);
        }
        if (data.properties && data.properties.length > 0) {
          setSelectedGa4OauthProperty(data.properties[0].id);
        }
        
        alert(`Credenciales de Google validadas con éxito. Se encontraron ${data.accounts?.length || 0} cuentas y ${data.properties?.length || 0} propiedades de GA4.`);
      } else {
        const err = await res.json();
        throw new Error(err.detail || "Fallo en la autenticación con Google Analytics API.");
      }
    } catch (err: any) {
      alert(err.message || 'Error al conectar con el servicio de validación de Google');
    } finally {
      setValidatingGa4Oauth(false);
    }
  };

  const handleGa4OauthAccountChange = async (accountId: string) => {
    setSelectedGa4OauthAccount(accountId);
    setSelectedGa4OauthProperty('');
    setGa4OauthPropertiesList([]);
    
    try {
      setValidatingGa4Oauth(true);
      const res = await secureFetch(`/api/v1/mcp-analytics/admin/tenants/validate-ga4-properties?credentials_json=${encodeURIComponent(secretValue.trim())}&account_id=${encodeURIComponent(accountId)}`);
      
      if (res.ok) {
        const data = await res.json();
        setGa4OauthPropertiesList(data.properties || []);
        if (data.properties && data.properties.length > 0) {
          setSelectedGa4OauthProperty(data.properties[0].id);
        }
      }
    } catch (err: any) {
      console.error("Error loading properties for GA4 account:", err);
    } finally {
      setValidatingGa4Oauth(false);
    }
  };

  const handleValidateAdobeCredentials = async () => {
    if (!adobeClientId || !adobeClientSecret || !adobeOrgId) {
      alert("Por favor completa los tres campos de Adobe para validar.");
      return;
    }
    
    try {
      setValidatingAdobe(true);
      const res = await secureFetch(`/api/v1/mcp-analytics/admin/tenants/validate-adobe-credentials`, {
        method: 'POST',
        body: JSON.stringify({
          client_id: adobeClientId.trim(),
          client_secret: adobeClientSecret.trim(),
          org_id: adobeOrgId.trim()
        })
      });
      
      if (res.ok) {
        const data = await res.json();
        setAdobeCompaniesList(data.companies || []);
        setAdobeSuitesList(data.suites || []);
        
        if (data.companies && data.companies.length > 0) {
          setSelectedAdobeCompany(data.companies[0].id);
        }
        if (data.suites && data.suites.length > 0) {
          setSelectedAdobeSuite(data.suites[0].id);
        }
        
        alert(`Credenciales de Adobe validadas con éxito. Se encontraron ${data.companies?.length || 0} compañías y ${data.suites?.length || 0} report suites.`);
      } else {
        const err = await res.json();
        throw new Error(err.detail || "Fallo en la autenticación con Adobe Discovery API.");
      }
    } catch (err: any) {
      alert(err.message || 'Error al conectar con el servicio de validación de Adobe');
    } finally {
      setValidatingAdobe(false);
    }
  };

  const handleAdobeCompanyChange = async (companyId: string) => {
    setSelectedAdobeCompany(companyId);
    setSelectedAdobeSuite('');
    setAdobeSuitesList([]);
    
    try {
      setValidatingAdobe(true);
      const res = await secureFetch(`/api/v1/mcp-analytics/admin/tenants/validate-adobe-properties?client_id=${encodeURIComponent(adobeClientId.trim())}&client_secret=${encodeURIComponent(adobeClientSecret.trim())}&org_id=${encodeURIComponent(adobeOrgId.trim())}&company_id=${encodeURIComponent(companyId)}`);
      
      if (res.ok) {
        const data = await res.json();
        const suites = data.suites || [];
        setAdobeSuitesList(suites);
        if (suites.length > 0) {
          const firstSuite = suites[0].id;
          setSelectedAdobeSuite(firstSuite);
        }
      }
    } catch (err: any) {
      console.error("Error loading properties for company:", err);
    } finally {
      setValidatingAdobe(false);
    }
  };

  const handleValidatePeecCredentials = async () => {
    if (!secretValue) {
      alert("Por favor ingresa el API Key de Peec.ai para validar.");
      return;
    }
    
    try {
      setValidatingPeec(true);
      const res = await secureFetch(`/api/v1/mcp-analytics/admin/tenants/validate-peec-projects?api_key=${encodeURIComponent(secretValue.trim())}`);
      
      if (res.ok) {
        const data = await res.json();
        setPeecProjectsList(data.projects || []);
        
        if (data.projects && data.projects.length > 0) {
          setSelectedPeecProject(data.projects[0].id);
        }
        
        alert(`API Key de Peec validadas con éxito. Se encontraron ${data.projects?.length || 0} proyectos.`);
      } else {
        const err = await res.json();
        throw new Error(err.detail || "Fallo en la autenticación con Peec API.");
      }
    } catch (err: any) {
      alert(err.message || 'Error al conectar con el servicio de validación de Peec.ai');
    } finally {
      setValidatingPeec(false);
    }
  };

  const handleEditConfig = async () => {
    if (!tenantId) return;
    try {
      setSaving(true);
      const res = await secureFetch(`/api/v1/mcp-analytics/admin/tenants/${tenantId}/secrets/${secretType}/options`);
      if (res.ok) {
        const data = await res.json();
        const opts = data.options;
        const cur = data.current_selection;

        if (secretType === 'peec-key') {
          setPeecProjectsList(opts.projects || []);
          if (cur.project_id) setSelectedPeecProject(cur.project_id);
        } else if (secretType === 'adobe-creds') {
          setAdobeCompaniesList(opts.companies || []);
          setAdobeSuitesList(opts.suites || []);
          if (cur.company_id) setSelectedAdobeCompany(cur.company_id);
          if (cur.property_id) setSelectedAdobeSuite(cur.property_id);
        } else if (secretType === 'ga4-creds' || secretType === 'ga4-oauth') {
          setGa4OauthAccountsList(opts.accounts || []);
          setGa4OauthPropertiesList(opts.properties || []);
          if (cur.account_id) setSelectedGa4OauthAccount(cur.account_id);
          if (cur.property_id) setSelectedGa4OauthProperty(cur.property_id);
        }
        
        setIsEditMode(true);
      } else {
        const err = await res.json();
        throw new Error(err.detail || "Error al cargar opciones de configuración.");
      }
    } catch (err: any) {
      alert(err.message || 'Error al conectar con el backend para editar configuración');
    } finally {
      setSaving(false);
    }
  };

  const handleRedeployEtl = async () => {
    try {
      setRedeploying(true);
      const res = await secureFetch(`/api/v1/mcp-analytics/admin/tenants/${tenantId}/redeploy-etl`, {
        method: 'POST'
      });
      
      if (res.ok) {
        const data = await res.json();
        alert(data.message || 'Infraestructura ETL re-desplegada con éxito. Se re-creó el Cloud Scheduler y se encoló el backfill histórico.');
      } else {
        throw new Error("Error al re-desplegar la infraestructura ETL");
      }
    } catch (err: any) {
      alert(err.message || 'Error al re-desplegar la ETL');
    } finally {
      setRedeploying(false);
    }
  };

  const handleDeleteSecret = async () => {
    if (!tenantId) return;
    if (!window.confirm(`¿Estás seguro de que quieres borrar la llave secreta para ${secretType}? Esto podría romper los flujos ETL que dependan de ella.`)) {
      return;
    }
    try {
      setSaving(true);
      const res = await secureFetch(`/api/v1/mcp-analytics/admin/tenants/${tenantId}/secrets/${secretType}`, {
        method: 'DELETE'
      });
      if (res.ok) {
        onSaveSuccess(`Secreto '${secretType}' eliminado con éxito.`);
        onClose();
      } else {
        const err = await res.json();
        throw new Error(err.detail || "Error al eliminar el secreto.");
      }
    } catch (err: any) {
      alert(err.message || 'Error al conectar con el backend para eliminar el secreto');
    } finally {
      setSaving(false);
    }
  };

  const handleSaveSecret = async (e: React.FormEvent) => {
    e.preventDefault();

    try {
      setSaving(true);
      
      if (isEditMode) {
        let updates: Record<string, any> = {};
        if (secretType === 'peec-key') {
          updates.project_id = selectedPeecProject;
        } else if (secretType === 'adobe-creds') {
          updates.company_id = selectedAdobeCompany;
          updates.property_id = selectedAdobeSuite;
        } else if (secretType === 'ga4-creds' || secretType === 'ga4-oauth') {
          updates.account_id = selectedGa4OauthAccount;
          updates.property_id = selectedGa4OauthProperty;
        }

        const res = await secureFetch(`/api/v1/mcp-analytics/admin/tenants/${tenantId}/secrets/${secretType}`, {
          method: 'PATCH',
          body: JSON.stringify(updates)
        });
        
        if (res.ok) {
          onSaveSuccess(`Configuración del secreto '${secretType}' actualizada con éxito.`);
          onClose();
        } else {
          const err = await res.json();
          throw new Error(err.detail || "Error al actualizar la configuración");
        }
        return;
      }
      
      if (secretType === 'ga4-creds') {
        if (!selectedGa4Connection || selectedGa4Properties.length === 0) {
          alert("Debes seleccionar una conexión global y al menos una propiedad de GA4.");
          return;
        }
        const res = await secureFetch(`/api/v1/mcp-analytics/admin/tenants/${tenantId}/ga4-config`, {
          method: 'POST',
          body: JSON.stringify({
            connection_id: selectedGa4Connection,
            properties: selectedGa4Properties
          })
        });
        if (res.ok) {
          onSaveSuccess(`Configuración multicuenta de GA4 guardada con éxito para '${tenantId}'.`);
          onClose();
        } else {
          throw new Error("Error al guardar la configuración de GA4");
        }
      } else {
        let finalSecretValue = secretValue;
        if (secretType === 'adobe-creds') {
          finalSecretValue = JSON.stringify({
            client_id: adobeClientId.trim(),
            client_secret: adobeClientSecret.trim(),
            org_id: adobeOrgId.trim(),
            company_id: selectedAdobeCompany || undefined,
            property_id: selectedAdobeSuite || undefined
          });
        } else if (secretType === 'peec-key') {
          finalSecretValue = JSON.stringify({
            api_key: secretValue.trim(),
            project_id: selectedPeecProject || undefined
          });
        } else if (secretType === 'ga4-oauth' && selectedGa4OauthProperty) {
          try {
            const parsed = JSON.parse(secretValue.trim());
            parsed.account_id = selectedGa4OauthAccount;
            parsed.property_id = selectedGa4OauthProperty;
            finalSecretValue = JSON.stringify(parsed);
          } catch (err) {
            console.warn("Pasted secret is not valid JSON, keeping as is:", err);
          }
        }
        if (!finalSecretValue) {
          alert("Por favor completa los campos de credenciales.");
          return;
        }
        const res = await secureFetch(`/api/v1/mcp-analytics/admin/tenants/${tenantId}/secrets`, {
          method: 'POST',
          body: JSON.stringify({ secret_type: secretType, secret_value: finalSecretValue })
        });
        if (res.ok) {
          onSaveSuccess(`Secreto '${secretType}' guardado y encriptado con éxito en GCP Secret Manager para el cliente '${tenantId}'.`);
          onClose();
        } else {
          throw new Error("Error al persistir el secreto en GCP Secret Manager");
        }
      }
    } catch (err: any) {
      onSaveError(err.message || 'Error de ciberseguridad al guardar el secreto');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-navy/80 backdrop-blur-sm flex items-center justify-center p-5 z-[1000]">
      <div className="bg-[#0b1b3d]/90 border border-white/10 rounded-2xl max-w-lg w-full shadow-2xl overflow-hidden max-h-[90vh] flex flex-col">
        <div className="p-6 border-b border-white/10 bg-white/[0.02] flex items-center gap-2">
          <Key className="w-5 h-5 text-amber-400" />
          <h3 className="font-black text-sm uppercase tracking-widest text-amber-400">
            Administrar Credenciales de Ciberseguridad (GCP)
          </h3>
        </div>
        
        <form onSubmit={handleSaveSecret} className="p-6 space-y-4 overflow-y-auto custom-scrollbar flex-1">
          <div className="bg-amber-500/5 border border-amber-500/10 rounded-xl p-4 text-[11px] text-amber-300/80 leading-relaxed">
            🛡️ **Seguridad Compliance**: Estas llaves serán guardadas y encriptadas de forma transparente y directa en **GCP Secret Manager** de producción. Nunca se almacenarán en bases de datos relacionales estándar en texto plano.
          </div>

          <div>
            <label className="block text-[10px] font-bold uppercase tracking-wider text-mid mb-1">Cliente Objetivo</label>
            <input 
              type="text" 
              value={tenantId.toUpperCase()} 
              disabled 
              className="w-full bg-white/5 border border-white/5 rounded-lg px-4 py-2.5 text-xs text-white/50 font-bold uppercase"
            />
          </div>

          <div className="space-y-1.5 flex justify-between items-end">
            <div className="w-full">
              <label className="text-xs font-bold uppercase tracking-widest text-mid block mb-1">
                ¿Qué llave quieres actualizar?
              </label>
              <select
                value={secretType}
                onChange={(e) => setSecretType(e.target.value)}
                className="w-full bg-[#0a1829] border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:border-amber-400 focus:ring-1 focus:ring-amber-400/50 outline-none"
              >
                {!secretType && <option value="">¡Todas las llaves disponibles ya están configuradas!</option>}
                {(forceEditMode ? configuredSecrets['brandlight-key'] : !configuredSecrets['brandlight-key']) && <option value="brandlight-key">Clave API de Brandlight (Menciones)</option>}
                {(forceEditMode ? configuredSecrets['peec-key'] : !configuredSecrets['peec-key']) && <option value="peec-key">Clave API de Peec.ai (Brand Intelligence)</option>}
                {(forceEditMode ? configuredSecrets['ga4-creds'] : !configuredSecrets['ga4-creds']) && <option value="ga4-creds">Conexión GA4 (Global Service Account)</option>}
                {(forceEditMode ? configuredSecrets['ga4-oauth'] : !configuredSecrets['ga4-oauth']) && <option value="ga4-oauth">Credenciales GA4 (JSON OAuth / Service Account)</option>}
                {(forceEditMode ? configuredSecrets['adobe-creds'] : !configuredSecrets['adobe-creds']) && <option value="adobe-creds">Credenciales de Adobe Analytics</option>}
              </select>
            </div>
          </div>

          {secretType && (
            secretType === 'adobe-creds' ? (
            <div className="space-y-4">
              {!isEditMode && (
                <div className="space-y-3">
                  <div className="space-y-1.5">
                    <label className="text-xs font-bold uppercase tracking-widest text-mid block">Client ID</label>
                    <input
                      type="password"
                      placeholder="e.g. 1a2b3c4d5e6f7g8h9i0j..."
                      value={adobeClientId}
                      onChange={(e) => setAdobeClientId(e.target.value)}
                      className="w-full bg-[#0a1829] border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-white/20 focus:border-amber-400 font-mono"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-bold uppercase tracking-widest text-mid block">Client Secret</label>
                    <input
                      type="password"
                      placeholder="e.g. p8e-xxxxxxxx..."
                      value={adobeClientSecret}
                      onChange={(e) => setAdobeClientSecret(e.target.value)}
                      className="w-full bg-[#0a1829] border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-white/20 focus:border-amber-400 font-mono"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-bold uppercase tracking-widest text-mid block">Organization ID</label>
                    <input
                      type="text"
                      placeholder="e.g. 1234567890ABCDEF@AdobeOrg"
                      value={adobeOrgId}
                      onChange={(e) => setAdobeOrgId(e.target.value)}
                      className="w-full bg-[#0a1829] border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-white/20 focus:border-amber-400 font-mono"
                    />
                  </div>

                  <button
                    type="button"
                    onClick={handleValidateAdobeCredentials}
                    disabled={validatingAdobe || !adobeClientId.trim() || !adobeClientSecret.trim() || !adobeOrgId.trim()}
                    className="w-full py-2 bg-rose-500/20 text-rose-300 rounded-lg text-xs font-bold uppercase hover:bg-rose-500/30 transition-colors border border-rose-500/30 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                  >
                    {validatingAdobe ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : '🔍 Validar Credenciales Adobe'}
                  </button>
                </div>
              )}

              {(isEditMode || adobeCompaniesList.length > 0) && (
                <div className="space-y-4 pt-3 border-t border-white/5">
                  <div>
                    <label className="block text-[10px] font-bold uppercase tracking-wider text-mid mb-1 text-teal">Compañía Seleccionada</label>
                    <select 
                      value={selectedAdobeCompany}
                      onChange={(e) => handleAdobeCompanyChange(e.target.value)}
                      className="w-full bg-[#0a1829] border border-white/10 rounded-lg px-4 py-2.5 text-xs text-white focus:outline-none focus:border-red font-bold"
                    >
                      {adobeCompaniesList.map(c => (
                        <option key={c.id} value={c.id}>{c.name}</option>
                      ))}
                    </select>
                  </div>
                  
                  {adobeSuitesList.length > 0 && (
                    <div>
                      <label className="block text-[10px] font-bold uppercase tracking-wider text-mid mb-1 text-red">Report Suite (Propiedad para ETL)</label>
                      <select 
                        value={selectedAdobeSuite}
                        onChange={(e) => setSelectedAdobeSuite(e.target.value)}
                        className="w-full bg-[#0a1829] border border-white/10 rounded-lg px-4 py-2.5 text-xs text-white focus:outline-none focus:border-red font-bold"
                      >
                        {adobeSuitesList.map(s => (
                          <option key={s.id} value={s.id}>{s.name}</option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>
              )}
            </div>
          ) : secretType === 'ga4-creds' ? (
            <div className="space-y-4 border-l-2 border-teal pl-4">
              <div>
                <label className="block text-[10px] font-bold uppercase tracking-wider text-mid mb-1 text-teal">Conexión Global de GA4 (Vault)</label>
                <select 
                  value={selectedGa4Connection}
                  onChange={(e) => setSelectedGa4Connection(e.target.value)}
                  className="w-full bg-[#0a1829] border border-white/10 rounded-lg px-4 py-2.5 text-xs text-white focus:outline-none focus:border-red font-bold"
                >
                  <option value="" disabled>Selecciona una conexión...</option>
                  {ga4Connections.map((conn: any) => (
                    <option key={conn.id} value={conn.id}>{conn.name} ({conn.client_email})</option>
                  ))}
                </select>
              </div>
              
              {loadingGa4Properties ? (
                <div className="flex items-center gap-2 text-mid text-xs">
                  <RefreshCw className="w-4 h-4 animate-spin" /> Cargando propiedades...
                </div>
              ) : ga4PropertiesList.length > 0 ? (
                <div>
                  <label className="block text-[10px] font-bold uppercase tracking-wider text-mid mb-2 text-red">Propiedades GA4 (Selección Múltiple)</label>
                  <div className="bg-[#0a1829] border border-white/10 rounded-lg max-h-60 overflow-y-auto custom-scrollbar">
                    {ga4PropertiesList.map(p => (
                      <div 
                        key={p.property_id} 
                        className={`flex items-center gap-3 p-3 border-b border-white/5 cursor-pointer hover:bg-white/5 transition-colors ${selectedGa4Properties.includes(p.property_id) ? 'bg-red/5' : ''}`}
                        onClick={() => handleToggleGa4Property(p.property_id)}
                      >
                        <div className={`w-4 h-4 rounded border flex items-center justify-center ${selectedGa4Properties.includes(p.property_id) ? 'bg-red border-red text-white' : 'border-white/20'}`}>
                          {selectedGa4Properties.includes(p.property_id) && <CheckSquare className="w-3 h-3" />}
                        </div>
                        <div>
                          <p className="text-xs font-bold text-white">{p.property_name}</p>
                          <p className="text-[10px] text-mid">{p.account_name} &bull; {p.property_id}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : selectedGa4Connection ? (
                <p className="text-xs text-red-400">No se encontraron propiedades accesibles para esta conexión.</p>
              ) : null}
            </div>
          ) : secretType === 'ga4-oauth' ? (
            <div className="space-y-4">
              {!isEditMode && (
                <div className="space-y-1.5">
                  <label className="text-xs font-bold uppercase tracking-widest text-mid block">
                    JSON de Credenciales de Google (OAuth)
                  </label>
                  <textarea
                    placeholder='Pega el contenido completo del archivo JSON descargado desde Google Cloud Platform...'
                    value={secretValue}
                    onChange={(e) => setSecretValue(e.target.value)}
                    rows={4}
                    className="w-full bg-[#0a1829] border border-white/10 rounded-lg px-3 py-2.5 text-xs text-white placeholder-white/20 focus:border-amber-400 focus:ring-1 focus:ring-amber-400/50 outline-none font-mono custom-scrollbar resize-none"
                  />
                  
                  <button
                    type="button"
                    onClick={handleValidateGa4OauthCredentials}
                    disabled={validatingGa4Oauth || !secretValue.trim()}
                    className="w-full mt-2 py-2 bg-emerald-500/20 text-emerald-300 rounded-lg text-xs font-bold uppercase hover:bg-emerald-500/30 transition-colors border border-emerald-500/30 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                  >
                    {validatingGa4Oauth ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : '🔍 Validar y Buscar Cuentas de GA4'}
                  </button>
                </div>
              )}
              
              {(isEditMode || ga4OauthAccountsList.length > 0) && (
                <div className="space-y-3 bg-emerald-500/10 p-4 rounded-xl border border-emerald-500/20">
                  <div className="space-y-4 pt-3 border-t border-white/5">
                    <div>
                      <label className="block text-[10px] font-bold uppercase tracking-wider text-mid mb-1 text-teal">Cuenta Google Seleccionada</label>
                      <select 
                        value={selectedGa4OauthAccount}
                        onChange={(e) => handleGa4OauthAccountChange(e.target.value)}
                        className="w-full bg-[#0a1829] border border-white/10 rounded-lg px-4 py-2.5 text-xs text-white focus:outline-none focus:border-red font-bold"
                      >
                        {ga4OauthAccountsList.map(a => (
                          <option key={a.id} value={a.id}>{a.name}</option>
                        ))}
                      </select>
                    </div>
                    
                    {ga4OauthPropertiesList.length > 0 && (
                      <div>
                        <label className="block text-[10px] font-bold uppercase tracking-wider text-mid mb-1 text-red">Propiedad GA4 (Para ETL)</label>
                        <select 
                          value={selectedGa4OauthProperty}
                          onChange={(e) => setSelectedGa4OauthProperty(e.target.value)}
                          className="w-full bg-[#0a1829] border border-white/10 rounded-lg px-4 py-2.5 text-xs text-white focus:outline-none focus:border-red font-bold text-red"
                        >
                          {ga4OauthPropertiesList.map(p => (
                            <option key={p.id} value={p.id}>{p.name}</option>
                          ))}
                        </select>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          ) : secretType === 'peec-key' ? (
            <div className="space-y-4">
              {!isEditMode && (
                <div className="space-y-1.5">
                  <label className="text-xs font-bold uppercase tracking-widest text-mid block">
                    LLAVE SECRETA (API Key de Peec)
                  </label>
                  <input
                    type="password"
                    placeholder="Pega la llave secreta provista por el proveedor aquí..."
                    value={secretValue}
                    onChange={(e) => setSecretValue(e.target.value)}
                    className="w-full bg-[#0a1829] border border-white/10 rounded-lg px-3 py-2.5 text-sm text-white placeholder-white/20 focus:border-amber-400 focus:ring-1 focus:ring-amber-400/50 outline-none font-mono"
                  />
                  
                  <button
                    type="button"
                    onClick={handleValidatePeecCredentials}
                    disabled={validatingPeec || !secretValue.trim()}
                    className="w-full mt-2 py-2 bg-indigo-500/20 text-indigo-300 rounded-lg text-xs font-bold uppercase hover:bg-indigo-500/30 transition-colors border border-indigo-500/30 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                  >
                    {validatingPeec ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : '🔍 Validar y Cargar Proyectos de Peec.ai'}
                  </button>
                </div>
              )}
              
              {(isEditMode || peecProjectsList.length > 0) && (
                <div className="space-y-1.5 bg-indigo-500/10 p-4 rounded-xl border border-indigo-500/20">
                  <div className="space-y-4 pt-3 border-t border-white/5">
                    <div>
                      <label className="block text-[10px] font-bold uppercase tracking-wider text-mid mb-1 text-indigo-400">Proyecto Peec.ai Seleccionado</label>
                      <select 
                        value={selectedPeecProject}
                        onChange={(e) => setSelectedPeecProject(e.target.value)}
                        className="w-full bg-[#0a1829] border border-white/10 rounded-lg px-4 py-2.5 text-xs text-white focus:outline-none focus:border-red font-bold text-indigo-400"
                      >
                        {peecProjectsList.map(p => (
                          <option key={p.id} value={p.id}>{p.name}</option>
                        ))}
                      </select>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ) : (
             <div>
              <label className="block text-[10px] font-bold uppercase tracking-wider text-mid mb-1">Valor de la Llave Secreta (API Key / Token)</label>
              <textarea 
                value={secretValue}
                onChange={(e) => setSecretValue(e.target.value)}
                placeholder="Pega aquí la clave secreta obtenida del proveedor analítico..."
                required={secretType !== 'ga4-creds'}
                rows={4}
                className="w-full bg-[#0a1829] border border-white/10 rounded-lg px-4 py-2.5 text-xs text-white font-mono focus:outline-none focus:border-red resize-none"
              />
            </div>
          ))}

          {/* Sección de Automatización ETL y Scheduler */}
          <div className="bg-white/5 border border-white/5 p-4 rounded-xl space-y-3 mt-4">
            <div className="flex items-start gap-2.5">
              <RefreshCw className={`w-4 h-4 text-amber-400 mt-0.5 ${redeploying ? 'animate-spin' : ''}`} />
              <div>
                <h4 className="text-[10px] font-bold uppercase tracking-widest text-white">Estado de Automatización (Daily ETL & Backfill)</h4>
                <p className="text-[9px] text-mid leading-relaxed mt-1">
                  Si el Cloud Scheduler diario o el backfill de 90 días no se configuraron debido a un fallo inicial, puedes forzar su re-despliegue manual e inmediato.
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={handleRedeployEtl}
              disabled={redeploying || saving}
              className="w-full py-2 bg-gradient-to-r from-amber-500/10 to-amber-600/10 hover:from-amber-500/20 hover:to-amber-600/20 text-amber-400 hover:text-white border border-amber-500/20 disabled:opacity-50 text-[10px] font-black uppercase tracking-wider rounded-lg transition-all flex items-center justify-center gap-1.5"
            >
              <RefreshCw className={`w-3 h-3 ${redeploying ? 'animate-spin' : ''}`} />
              {redeploying ? 'Re-desplegando...' : 'Forzar Re-despliegue de Scheduler & Backfill'}
            </button>
          </div>

          <div className="flex items-center justify-end gap-3 pt-4 border-t border-white/10">
            {forceEditMode && isEditMode && (
              <>
                <button 
                  type="button"
                  onClick={handleDeleteSecret}
                  disabled={saving}
                  className="px-4 py-2 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-400 rounded-lg text-xs font-bold uppercase tracking-wider transition-colors disabled:opacity-50"
                >
                  Borrar Llave
                </button>
                <button 
                  type="button"
                  onClick={() => setIsEditMode(false)}
                  disabled={saving}
                  className="px-4 py-2 bg-blue-500/10 hover:bg-blue-500/20 border border-blue-500/20 text-blue-400 rounded-lg text-xs font-bold uppercase tracking-wider transition-colors disabled:opacity-50"
                >
                  Renovar Llave
                </button>
              </>
            )}
            <button 
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-lg bg-white/5 hover:bg-white/10 text-xs font-bold transition-colors"
            >
              Cancelar
            </button>
            <button 
              type="submit"
              disabled={saving || !secretType}
              className="flex items-center gap-1.5 px-4 py-2 bg-amber-500 hover:bg-amber-600 text-navy rounded-lg text-xs font-black uppercase tracking-wider transition-colors disabled:opacity-50"
            >
              <Save className="w-4 h-4" /> {saving ? 'Cifrando...' : 'Encriptar y Guardar'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
