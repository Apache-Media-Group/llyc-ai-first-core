// frontend/src/components/admin/TenantModal.tsx
import React, { useState, useEffect } from 'react';
import { Save } from 'lucide-react';
import type { TenantConfig } from './types';
import { secureFetch } from '../../services/apiClient';

interface TenantModalProps {
  isOpen: boolean;
  onClose: () => void;
  tenant: TenantConfig;
  onSaveSuccess: () => void;
}

export const TenantModal: React.FC<TenantModalProps> = ({
  isOpen,
  onClose,
  tenant,
  onSaveSuccess,
}) => {
  const [editingTenant, setEditingTenant] = useState<TenantConfig>(tenant);
  const [saving, setSaving] = useState(false);
  const [uploadingLogo, setUploadingLogo] = useState(false);
  const [emailsInput, setEmailsInput] = useState('');
  const [domainsInput, setDomainsInput] = useState('');

  useEffect(() => {
    setEditingTenant(tenant);
    setEmailsInput(tenant.authorized_emails ? tenant.authorized_emails.join(', ') : '');
    setDomainsInput(tenant.authorized_domains ? tenant.authorized_domains.join(', ') : '');
  }, [tenant]);

  const handleEmailsChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setEmailsInput(value);
    const list = value.split(',').map(item => item.trim()).filter(Boolean);
    setEditingTenant(prev => ({ ...prev, authorized_emails: list }));
  };

  const handleDomainsChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setDomainsInput(value);
    const list = value.split(',').map(item => item.trim()).filter(Boolean);
    setEditingTenant(prev => ({ ...prev, authorized_domains: list }));
  };

  if (!isOpen) return null;

  const handleLogoUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || !e.target.files[0] || !editingTenant) return;
    const file = e.target.files[0];
    
    if (!editingTenant.tenant_id) {
      alert("Por favor, escribe primero el ID del Cliente (Tenant ID) para poder asociarle el archivo de logotipo.");
      return;
    }
    
    const formData = new FormData();
    formData.append('file', file);
    
    try {
      setUploadingLogo(true);
      const res = await secureFetch(`/api/v1/mcp-analytics/admin/tenants/${editingTenant.tenant_id}/logo`, {
        method: 'POST',
        body: formData
      });
      const result = await res.json();
      if (res.ok && result.logo_url) {
        setEditingTenant({ ...editingTenant, logo_url: result.logo_url });
        alert("¡Logotipo subido y guardado con éxito en Google Cloud Storage!");
      } else {
        throw new Error(result.detail || "Error al subir el logotipo");
      }
    } catch (err: any) {
      alert("Fallo al subir el logo: " + err.message);
    } finally {
      setUploadingLogo(false);
    }
  };

  const handleSaveTenant = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingTenant) return;

    try {
      setSaving(true);
      const res = await secureFetch(`/api/v1/mcp-analytics/admin/tenants`, {
        method: 'POST',
        body: JSON.stringify(editingTenant)
      });

      if (res.ok) {
        onSaveSuccess();
      } else {
        throw new Error("Error del servidor al guardar el tenant");
      }
    } catch (err: any) {
      alert(err.message || 'Error al guardar el tenant');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-navy/80 backdrop-blur-sm flex items-center justify-center p-5 z-[1000]">
      <div className="bg-[#0c1829] border border-white/10 rounded-2xl max-w-lg w-full shadow-2xl overflow-hidden">
        <div className="p-6 border-b border-white/10 bg-white/[0.02]">
          <h3 className="font-black text-sm uppercase tracking-widest text-red">
            {editingTenant.updated_at ? 'Editar Configuración de Marca' : 'Crear Nuevo Cliente'}
          </h3>
        </div>
        
        <form onSubmit={handleSaveTenant} className="p-6 space-y-4 max-h-[75vh] overflow-y-auto">
          <div>
            <label className="block text-[10px] font-bold uppercase tracking-wider text-mid mb-1">ID del Cliente (Tenant ID)</label>
            <input 
              type="text" 
              value={editingTenant.tenant_id}
              onChange={(e) => setEditingTenant({ ...editingTenant, tenant_id: e.target.value.toLowerCase().replace(/\s+/g, '-') })}
              disabled={!!editingTenant.updated_at} // Bloquear ID si ya existe
              placeholder="ej: mi-organizacion"
              required
              className="w-full bg-[#0a1829] border border-white/10 rounded-lg px-4 py-2.5 text-xs text-white focus:outline-none focus:border-red transition-colors disabled:opacity-50"
            />
          </div>

          <div>
            <label className="block text-[10px] font-bold uppercase tracking-wider text-mid mb-1">Nombre Comercial</label>
            <input 
              type="text" 
              value={editingTenant.tenant_name}
              onChange={(e) => setEditingTenant({ ...editingTenant, tenant_name: e.target.value })}
              placeholder="ej: Mi Empresa S.A."
              required
              className="w-full bg-[#0a1829] border border-white/10 rounded-lg px-4 py-2.5 text-xs text-white focus:outline-none focus:border-red transition-colors"
            />
          </div>

          <div>
            <label className="block text-[10px] font-bold uppercase tracking-wider text-mid mb-1">Logotipo del Cliente (SVG o PNG)</label>
            <div className="space-y-2">
              <div className="flex gap-2">
                <input 
                  type="text" 
                  value={editingTenant.logo_url}
                  onChange={(e) => setEditingTenant({ ...editingTenant, logo_url: e.target.value })}
                  placeholder="Escribe la URL del logo o sube un archivo..."
                  required
                  className="flex-1 bg-[#0a1829] border border-white/10 rounded-lg px-4 py-2.5 text-xs text-white focus:outline-none focus:border-red transition-colors"
                />
                <label className="px-4 py-2.5 bg-white/5 border border-white/10 hover:bg-white/10 text-xs font-bold rounded-lg cursor-pointer flex items-center justify-center min-w-[120px] transition-colors">
                  {uploadingLogo ? 'Subiendo...' : 'Subir Archivo'}
                  <input 
                    type="file" 
                    accept=".svg,.png" 
                    onChange={handleLogoUpload} 
                    className="hidden" 
                    disabled={uploadingLogo} 
                  />
                </label>
              </div>
              {editingTenant.logo_url && (
                <div className="p-3 bg-white/5 rounded-lg border border-white/5 flex items-center justify-between gap-4">
                  <span className="text-[10px] text-mid truncate max-w-[250px] font-mono">{editingTenant.logo_url}</span>
                  <img src={editingTenant.logo_url} alt="Vista previa" className="h-6 max-w-[60px] object-contain bg-white/5 p-0.5 rounded" />
                </div>
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-[10px] font-bold uppercase tracking-wider text-mid mb-1">Color Primario (Hex)</label>
              <div className="flex gap-2">
                <input 
                  type="color" 
                  value={editingTenant.primary_color}
                  onChange={(e) => setEditingTenant({ ...editingTenant, primary_color: e.target.value })}
                  className="w-8 h-8 rounded border border-white/10 cursor-pointer bg-transparent"
                />
                <input 
                  type="text" 
                  value={editingTenant.primary_color}
                  onChange={(e) => setEditingTenant({ ...editingTenant, primary_color: e.target.value })}
                  maxLength={7}
                  required
                  className="flex-1 bg-[#0a1829] border border-white/10 rounded-lg px-3 py-1.5 text-xs text-white uppercase font-mono focus:outline-none focus:border-red"
                />
              </div>
            </div>

            <div>
              <label className="block text-[10px] font-bold uppercase tracking-wider text-mid mb-1">Color Secundario (Hex)</label>
              <div className="flex gap-2">
                <input 
                  type="color" 
                  value={editingTenant.secondary_color}
                  onChange={(e) => setEditingTenant({ ...editingTenant, secondary_color: e.target.value })}
                  className="w-8 h-8 rounded border border-white/10 cursor-pointer bg-transparent"
                />
                <input 
                  type="text" 
                  value={editingTenant.secondary_color}
                  onChange={(e) => setEditingTenant({ ...editingTenant, secondary_color: e.target.value })}
                  maxLength={7}
                  required
                  className="flex-1 bg-[#0a1829] border border-white/10 rounded-lg px-3 py-1.5 text-xs text-white uppercase font-mono focus:outline-none focus:border-red"
                />
              </div>
            </div>
          </div>

          <div>
            <label className="block text-[10px] font-bold uppercase tracking-wider text-mid mb-1">Email de Soporte</label>
            <input 
              type="email" 
              value={editingTenant.support_email}
              onChange={(e) => setEditingTenant({ ...editingTenant, support_email: e.target.value })}
              placeholder="soporte@mi-organizacion.com"
              required
              className="w-full bg-[#0a1829] border border-white/10 rounded-lg px-4 py-2.5 text-xs text-white focus:outline-none focus:border-red transition-colors"
            />
          </div>

          <div>
            <label className="block text-[10px] font-bold uppercase tracking-wider text-mid mb-1">Correos Autorizados (Separados por comas)</label>
            <input 
              type="text" 
              value={emailsInput}
              onChange={handleEmailsChange}
              placeholder="ej: cliente@empresa.com, gerente@empresa.com"
              className="w-full bg-[#0a1829] border border-white/10 rounded-lg px-4 py-2.5 text-xs text-white focus:outline-none focus:border-red transition-colors"
            />
            {editingTenant.authorized_emails && editingTenant.authorized_emails.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-1.5 max-h-[60px] overflow-y-auto">
                {editingTenant.authorized_emails.map((email, idx) => (
                  <span key={idx} className="px-2 py-0.5 bg-red/10 border border-red/20 rounded text-[10px] text-red font-semibold">
                    {email}
                  </span>
                ))}
              </div>
            )}
          </div>

          <div>
            <label className="block text-[10px] font-bold uppercase tracking-wider text-mid mb-1">Dominios Corporativos Autorizados (Separados por comas)</label>
            <input 
              type="text" 
              value={domainsInput}
              onChange={handleDomainsChange}
              placeholder="ej: empresa.com, filial.es"
              className="w-full bg-[#0a1829] border border-white/10 rounded-lg px-4 py-2.5 text-xs text-white focus:outline-none focus:border-red transition-colors"
            />
            {editingTenant.authorized_domains && editingTenant.authorized_domains.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-1.5 max-h-[60px] overflow-y-auto">
                {editingTenant.authorized_domains.map((domain, idx) => (
                  <span key={idx} className="px-2 py-0.5 bg-blue-500/10 border border-blue-500/20 rounded text-[10px] text-blue-400 font-semibold">
                    {domain}
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="flex items-center justify-end gap-3 pt-4 border-t border-white/10">
            <button 
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-lg bg-white/5 hover:bg-white/10 text-xs font-bold transition-colors"
            >
              Cancelar
            </button>
            <button 
              type="submit"
              disabled={saving}
              className="flex items-center gap-1.5 px-4 py-2 bg-red hover:bg-red/90 text-white rounded-lg text-xs font-bold transition-colors disabled:opacity-50"
            >
              <Save className="w-4 h-4" /> {saving ? 'Guardando...' : 'Guardar Marca'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
