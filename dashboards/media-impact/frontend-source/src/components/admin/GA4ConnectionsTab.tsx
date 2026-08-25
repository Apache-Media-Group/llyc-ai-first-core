import React, { useState } from 'react';
import { KeyRound, Plus, Upload, CheckCircle2, AlertCircle, FileJson } from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { secureFetch } from '../../services/apiClient';

interface GA4Connection {
  id: string;
  name: string;
  client_email: string;
  created_at: string;
}

export const GA4ConnectionsTab: React.FC = () => {
  const [showAddModal, setShowAddModal] = useState(false);
  const [connectionName, setConnectionName] = useState('');
  const [connectionType, setConnectionType] = useState<'service_account' | 'oauth_json' | 'admin_oauth'>('service_account');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  
  const queryClient = useQueryClient();

  const { data: connections = [], isLoading } = useQuery<GA4Connection[]>({
    queryKey: ['ga4Connections'],
    queryFn: async () => {
      const res = await secureFetch('/api/v1/mcp-analytics/connections/ga4');
      if (!res.ok) throw new Error('Error al cargar las conexiones');
      return res.json();
    }
  });

  const uploadMutation = useMutation({
    mutationFn: async (formData: FormData) => {
      const res = await secureFetch('/api/v1/mcp-analytics/connections/ga4', {
        method: 'POST',
        body: formData,
        // No headers needed, fetch will automatically set multipart/form-data
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || 'Error al subir el archivo');
      }
      return res.json();
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['ga4Connections'] });
      
      // Si el backend devuelve un auth_url, redirigimos (flujo OAuth)
      if (data.authorization_url) {
        window.location.href = data.authorization_url;
        return;
      }
      
      setShowAddModal(false);
      setConnectionName('');
      setConnectionType('service_account');
      setSelectedFile(null);
      setUploadError(null);
    },
    onError: (error: any) => {
      setUploadError(error.message);
    }
  });

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setSelectedFile(e.target.files[0]);
      setUploadError(null);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!connectionName) {
      setUploadError('Debes proporcionar un nombre descriptivo.');
      return;
    }
    
    if (connectionType !== 'admin_oauth' && !selectedFile) {
      setUploadError('Debes proporcionar un archivo JSON para este método de conexión.');
      return;
    }

    const formData = new FormData();
    formData.append('name', connectionName);
    formData.append('type', connectionType);
    if (selectedFile) {
      formData.append('file', selectedFile);
    }
    
    uploadMutation.mutate(formData);
  };

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center bg-white/5 border border-white/10 rounded-2xl p-6">
        <div>
          <h2 className="text-lg font-black tracking-tight flex items-center gap-2">
            <KeyRound className="w-5 h-5 text-red" />
            Conexiones Globales de Google Analytics 4
          </h2>
          <p className="text-xs text-mid mt-1">
            Administra los Service Accounts maestros (vaults) que tienen acceso de lectura a las propiedades de GA4 de los clientes.
          </p>
        </div>
        <button
          onClick={() => setShowAddModal(true)}
          className="flex items-center gap-2 px-4 py-2.5 bg-red text-white rounded-lg text-[11px] font-black uppercase tracking-widest hover:bg-red/90 transition-colors shadow-lg shadow-red/20"
        >
          <Plus className="w-4 h-4" /> Añadir Conexión
        </button>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-10">
          <div className="animate-spin w-6 h-6 border-2 border-red border-t-transparent rounded-full"></div>
        </div>
      ) : connections.length === 0 ? (
        <div className="bg-[#0c1e30] border border-white/10 rounded-2xl p-8 text-center space-y-4">
          <FileJson className="w-12 h-12 text-mid mx-auto opacity-50" />
          <h3 className="text-sm font-bold text-white/80">No hay conexiones GA4 configuradas</h3>
          <p className="text-xs text-mid max-w-md mx-auto">
            Sube un archivo JSON de Service Account de Google Cloud para añadir la primera conexión global. Esto permitirá listar y asignar propiedades a los clientes.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {connections.map((conn) => (
            <div key={conn.id} className="bg-white/5 border border-white/10 hover:border-white/20 transition-colors rounded-xl p-5 space-y-4">
              <div className="flex items-start justify-between">
                <div>
                  <h3 className="text-sm font-bold truncate pr-2" title={conn.name}>{conn.name}</h3>
                  <p className="text-[10px] text-emerald-400 font-mono mt-1 flex items-center gap-1">
                    <CheckCircle2 className="w-3 h-3" /> Activa
                  </p>
                </div>
                <div className="bg-white/10 p-2 rounded-lg">
                  <KeyRound className="w-4 h-4 text-white/60" />
                </div>
              </div>
              
              <div className="space-y-2 pt-2 border-t border-white/5">
                <div>
                  <p className="text-[10px] text-mid uppercase font-bold tracking-wider">Service Account</p>
                  <p className="text-xs font-mono text-white/80 truncate mt-0.5" title={conn.client_email}>{conn.client_email}</p>
                </div>
                <div>
                  <p className="text-[10px] text-mid uppercase font-bold tracking-wider">Fecha Creación</p>
                  <p className="text-xs text-white/80 mt-0.5">{new Date(conn.created_at).toLocaleDateString('es-ES', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute:'2-digit' })}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* MODAL PARA AÑADIR CONEXIÓN */}
      {showAddModal && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-[#0a1829]/80 backdrop-blur-sm p-4">
          <div className="bg-[#0f2339] border border-white/10 rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
            <div className="flex justify-between items-center p-6 border-b border-white/5">
              <h2 className="text-base font-black tracking-tight uppercase flex items-center gap-2">
                <Upload className="w-5 h-5 text-red" />
                Subir Service Account
              </h2>
              <button 
                onClick={() => setShowAddModal(false)}
                className="text-mid hover:text-white transition-colors"
              >
                ✕
              </button>
            </div>
            
            <form onSubmit={handleSubmit} className="p-6 space-y-5 overflow-y-auto">
              {uploadError && (
                <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg flex items-start gap-2">
                  <AlertCircle className="w-4 h-4 text-red shrink-0 mt-0.5" />
                  <p className="text-xs text-red-400">{uploadError}</p>
                </div>
              )}
              
              <div className="space-y-1.5">
                <label className="text-[10px] font-bold uppercase tracking-widest text-mid">Tipo de Conexión</label>
                <select 
                  value={connectionType}
                  onChange={(e) => setConnectionType(e.target.value as any)}
                  className="w-full bg-[#0a1829] border border-white/10 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:border-red transition-colors text-white"
                >
                  <option value="service_account">GA4 Service Account JSON (Opción Recomendada)</option>
                  <option value="oauth_json">GA4 OAuth 2.0 Client Secret (Flujo de Consentimiento)</option>
                  <option value="admin_oauth">Login con Google (Usar cuenta del Admin actual)</option>
                </select>
                <p className="text-[10px] text-mid/80 mt-1">
                  {connectionType === 'service_account' && 'Permite usar un Service Account (vault) sin requerir consentimientos manuales futuros.'}
                  {connectionType === 'oauth_json' && 'Sube un client_secret de GCP para iniciar el flujo de autenticación 3-Legged.'}
                  {connectionType === 'admin_oauth' && 'Se abrirá un popup para autenticarte usando la App Web preconfigurada.'}
                </p>
              </div>
              
              <div className="space-y-1.5">
                <label className="text-[10px] font-bold uppercase tracking-widest text-mid">Nombre Descriptivo</label>
                <input 
                  type="text" 
                  value={connectionName}
                  onChange={(e) => setConnectionName(e.target.value)}
                  placeholder="Ej: Agencia Madrid Principal" 
                  className="w-full bg-[#0a1829] border border-white/10 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:border-red transition-colors"
                  required
                />
              </div>

              {connectionType !== 'admin_oauth' && (
                <div className="space-y-1.5">
                  <label className="text-[10px] font-bold uppercase tracking-widest text-mid">Archivo JSON</label>
                  <div className="relative">
                    <input 
                      type="file" 
                      accept=".json"
                      onChange={handleFileChange}
                      className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                      required
                    />
                    <div className={`w-full border-2 border-dashed rounded-xl p-8 text-center transition-colors ${selectedFile ? 'border-emerald-500/50 bg-emerald-500/5' : 'border-white/10 bg-white/5 hover:border-white/20 hover:bg-white/10'}`}>
                      <FileJson className={`w-8 h-8 mx-auto mb-2 ${selectedFile ? 'text-emerald-400' : 'text-mid'}`} />
                      <p className="text-xs font-semibold text-white/80">
                        {selectedFile ? selectedFile.name : 'Haz clic o arrastra el archivo JSON aquí'}
                      </p>
                      <p className="text-[10px] text-mid mt-1">
                        {connectionType === 'service_account' ? 'Sólo se permiten archivos de Service Account de Google Cloud' : 'Sube tu archivo client_secret_*.json de GCP'}
                      </p>
                    </div>
                  </div>
                </div>
              )}

              <div className="pt-4 flex justify-end gap-3 border-t border-white/5">
                <button 
                  type="button" 
                  onClick={() => setShowAddModal(false)}
                  className="px-4 py-2 bg-white/5 hover:bg-white/10 text-white text-xs font-bold uppercase tracking-widest rounded-lg transition-colors"
                >
                  Cancelar
                </button>
                <button 
                  type="submit" 
                  disabled={uploadMutation.isPending || !connectionName || (connectionType !== 'admin_oauth' && !selectedFile)}
                  className="flex items-center gap-2 px-6 py-2 bg-red hover:bg-red/90 text-white text-xs font-black uppercase tracking-widest rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {uploadMutation.isPending ? 'Procesando...' : (connectionType === 'service_account' ? 'Guardar Conexión' : 'Conectar con Google')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
