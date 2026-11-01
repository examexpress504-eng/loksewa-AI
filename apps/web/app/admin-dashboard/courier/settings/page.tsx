"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { 
  marketplaceApi, 
  NCMConfiguration, 
  NCMBranch, 
  NCMWebhookEvent 
} from "@/lib/api/marketplace";
import { 
  Settings, 
  ShieldAlert, 
  CheckCircle2, 
  XCircle, 
  RefreshCw, 
  Activity, 
  Key, 
  Server, 
  Globe, 
  Copy, 
  AlertTriangle, 
  Info, 
  Clock, 
  Save, 
  Lock, 
  Check,
  Send,
  Eye,
  Sliders,
  MapPin,
  Compass,
  Edit2,
  Search,
  Navigation,
} from "lucide-react";
import toast from "react-hot-toast";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

export default function CourierSettingsPage() {
  const [config, setConfig] = useState<NCMConfiguration | null>(null);
  const [branches, setBranches] = useState<NCMBranch[]>([]);
  const [branchesCount, setBranchesCount] = useState<number>(0);
  const [branchSource, setBranchSource] = useState<string>("DATABASE_CACHE");
  const [branchLastSyncedAt, setBranchLastSyncedAt] = useState<string | null>(null);
  const [recentWebhooks, setRecentWebhooks] = useState<NCMWebhookEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [refreshingBranches, setRefreshingBranches] = useState(false);
  const [copiedUrl, setCopiedUrl] = useState(false);

  // Branch coordinate editing state
  const [editingBranch, setEditingBranch] = useState<NCMBranch | null>(null);
  const [editLat, setEditLat] = useState<string>("");
  const [editLon, setEditLon] = useState<string>("");
  const [editSource, setEditSource] = useState<string>("ADMIN_VERIFIED");
  const [editVerified, setEditVerified] = useState<boolean>(true);
  const [editServiceable, setEditServiceable] = useState<boolean>(true);
  const [editNotes, setEditNotes] = useState<string>("");
  const [editReason, setEditReason] = useState<string>("");
  const [savingBranch, setSavingBranch] = useState<boolean>(false);
  const [branchSearch, setBranchSearch] = useState<string>("");
  const [branchFilter, setBranchFilter] = useState<string>("all");

  // Form State
  const [isEnabled, setIsEnabled] = useState(true);
  const [environment, setEnvironment] = useState<"demo" | "production">("demo");
  const [customBaseUrl, setCustomBaseUrl] = useState("");
  const [newToken, setNewToken] = useState("");
  const [originBranch, setOriginBranch] = useState("Kathmandu");
  const [liveRatesEnabled, setLiveRatesEnabled] = useState(true);
  const [fallbackRulesEnabled, setFallbackRulesEnabled] = useState(false);
  const [autoSyncEnabled, setAutoSyncEnabled] = useState(true);
  const [webhookEnabled, setWebhookEnabled] = useState(true);

  // Production confirmation modal
  const [showProductionModal, setShowProductionModal] = useState(false);
  const [confirmProductionText, setConfirmProductionText] = useState("");

  const loadData = async () => {
    try {
      setLoading(true);
      const [configData, branchesData, webhookData] = await Promise.all([
        marketplaceApi.adminGetCourierSettings(),
        marketplaceApi.adminGetCourierBranches().catch(() => ({ branches: [], count: 0 })),
        marketplaceApi.adminGetNCMWebhookManagement().catch(() => ({ recent_events: [] })),
      ]);

      setConfig(configData);
      setIsEnabled(configData.is_enabled);
      setEnvironment(configData.environment);
      setCustomBaseUrl(configData.custom_base_url || "");
      setOriginBranch(configData.default_origin_branch || "Kathmandu");
      setLiveRatesEnabled(configData.live_rates_enabled);
      setFallbackRulesEnabled(configData.fallback_rules_enabled);
      setAutoSyncEnabled(configData.auto_sync_enabled);
      setWebhookEnabled(configData.webhook_enabled);

      if (branchesData?.branches) {
        setBranches(branchesData.branches);
        setBranchesCount(branchesData.count || branchesData.branches.length);
        setBranchSource((branchesData as any).source || (configData as any).branch_sync_source || "DATABASE_CACHE");
        setBranchLastSyncedAt((branchesData as any).last_synced_at || (configData as any).last_branch_sync_at || null);
      }
      if (webhookData?.recent_events) {
        setRecentWebhooks(webhookData.recent_events);
      }
    } catch (err: any) {
      toast.error(err.message || "Failed to load courier configuration");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleTestConnection = async () => {
    try {
      setTesting(true);
      const res = await marketplaceApi.adminTestNCMConnection();
      if (res.success) {
        toast.success(`Connection verified! Response time: ${res.latency_ms}ms (${res.branch_count} branches reachable)`);
      } else {
        toast.error(`Connection diagnostic failed: ${res.error || "Unknown error"}`);
      }
      // Reload updated telemetry
      const updated = await marketplaceApi.adminGetCourierSettings();
      setConfig(updated);
    } catch (err: any) {
      const msg = err?.data?.error || err?.data?.detail || err?.message || "Failed to test connection";
      toast.error(msg);
      marketplaceApi.adminGetCourierSettings().then(setConfig).catch(() => {});
    } finally {
      setTesting(false);
    }
  };

  const handleRefreshBranches = async () => {
    try {
      setRefreshingBranches(true);
      const res = await marketplaceApi.adminRefreshCourierBranches();
      setBranches(res.branches);
      setBranchesCount(res.count);
      setBranchSource((res as any).source || "LIVE_API");
      setBranchLastSyncedAt((res as any).last_synced_at || new Date().toISOString());
      toast.success(`Refreshed ${res.count} active NCM branches from provider.`);
    } catch (err: any) {
      toast.error(err.message || "Failed to refresh branches");
    } finally {
      setRefreshingBranches(false);
    }
  };

  const handleOpenEditBranch = (b: NCMBranch) => {
    setEditingBranch(b);
    setEditLat(b.latitude !== undefined && b.latitude !== null ? String(b.latitude) : "");
    setEditLon(b.longitude !== undefined && b.longitude !== null ? String(b.longitude) : "");
    setEditSource(b.coordinate_source || "ADMIN_VERIFIED");
    setEditVerified(Boolean(b.is_coordinate_verified));
    setEditServiceable(b.is_serviceable !== false);
    setEditNotes(b.serviceability_notes || "");
    setEditReason("");
  };

  const handleSaveBranchCoordinates = async () => {
    if (!editingBranch) return;
    try {
      setSavingBranch(true);
      await marketplaceApi.adminUpdateCourierBranchCoordinates({
        id: editingBranch.id,
        code: editingBranch.code,
        latitude: editLat.trim() ? parseFloat(editLat.trim()) : null,
        longitude: editLon.trim() ? parseFloat(editLon.trim()) : null,
        coordinate_source: editSource,
        is_coordinate_verified: editVerified,
        is_serviceable: editServiceable,
        serviceability_notes: editNotes,
        reason: editReason || "Admin coordinate review",
      });
      toast.success(`Updated coordinates and serviceability for ${editingBranch.name}`);
      setEditingBranch(null);
      loadData();
    } catch (err: any) {
      toast.error(err.message || "Failed to update branch coordinates");
    } finally {
      setSavingBranch(false);
    }
  };

  const handleCopyWebhookUrl = () => {
    const url = config?.webhook_endpoint_url || `${window.location.origin}/api/marketplace/webhooks/ncm/`;
    navigator.clipboard.writeText(url);
    setCopiedUrl(true);
    toast.success("Webhook endpoint URL copied to clipboard");
    setTimeout(() => setCopiedUrl(false), 2500);
  };

  const handleSaveSettings = async (skipProductionCheck = false) => {
    // If switching to production, require explicit confirmation
    if (environment === "production" && config?.environment !== "production" && !skipProductionCheck) {
      setShowProductionModal(true);
      return;
    }

    try {
      setSaving(true);
      const payload: any = {
        is_enabled: isEnabled,
        environment,
        custom_base_url: customBaseUrl,
        default_origin_branch: originBranch,
        live_rates_enabled: liveRatesEnabled,
        fallback_rules_enabled: fallbackRulesEnabled,
        auto_sync_enabled: autoSyncEnabled,
        webhook_enabled: webhookEnabled,
      };

      if (environment === "production") {
        payload.confirm_production = true;
      }

      if (newToken.trim()) {
        payload.new_api_token = newToken.trim();
      }

      const updated = await marketplaceApi.adminUpdateCourierSettings(payload);
      setConfig(updated);
      setNewToken("");
      setShowProductionModal(false);
      setConfirmProductionText("");
      toast.success("Courier settings saved successfully.");
    } catch (err: any) {
      toast.error(err.message || "Failed to update courier settings");
    } finally {
      setSaving(false);
    }
  };

  const handleClearDatabaseToken = async () => {
    try {
      setSaving(true);
      const updated = await marketplaceApi.adminUpdateCourierSettings({
        clear_database_token: true,
        new_api_token: "",
      });
      setConfig(updated);
      setNewToken("");
      toast.success("Database token override cleared. Active token now falls back to Render environment variable.");
    } catch (err: any) {
      toast.error(err.message || "Failed to clear database token override");
    } finally {
      setSaving(false);
    }
  };

  const handleToggleWebhook = async () => {
    try {
      const res = await marketplaceApi.adminActionNCMWebhook("toggle_enabled");
      setWebhookEnabled(res.webhook_enabled);
      toast.success(res.detail || "Webhook status updated");
    } catch (err: any) {
      toast.error(err.message || "Failed to toggle webhook");
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[400px] gap-3">
        <RefreshCw className="w-8 h-8 text-[#D4A72C] animate-spin" />
        <p className="text-slate-500 text-sm font-medium">Loading NCM configuration...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-6xl pb-12">
      {/* Page Title & Diagnostic Bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-900 tracking-tight flex items-center gap-2">
            <Settings className="w-5 h-5 text-[#D4A72C]" />
            Nepal Can Move (NCM) Settings
          </h2>
          <p className="text-slate-500 text-xs mt-0.5">
            Configure provider API authentication, origin shipping hubs, fallback policies, and webhook callbacks.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleTestConnection}
            disabled={testing}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 transition-colors shadow-xs disabled:opacity-60"
          >
            <Activity className={`w-3.5 h-3.5 ${testing ? "animate-spin" : ""}`} />
            {testing ? "Testing Connection..." : "Test Connection"}
          </button>
          <button
            onClick={() => handleSaveSettings(false)}
            disabled={saving}
            className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-lg bg-[#0B2545] text-white hover:bg-[#133966] transition-colors shadow-xs disabled:opacity-60"
          >
            <Save className={`w-3.5 h-3.5 ${saving ? "animate-spin" : ""}`} />
            {saving ? "Saving Changes..." : "Save Settings"}
          </button>
        </div>
      </div>

      {/* Connection Diagnostic Banner */}
      <div className={`p-4 rounded-xl border flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 ${
        config?.connection_status === 'connected'
          ? 'bg-emerald-50/70 border-emerald-200 text-emerald-900'
          : config?.connection_status === 'error'
          ? 'bg-rose-50/70 border-rose-200 text-rose-900'
          : 'bg-amber-50/70 border-amber-200 text-amber-900'
      }`}>
        <div className="flex items-center gap-3">
          {config?.connection_status === 'connected' ? (
            <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0" />
          ) : config?.connection_status === 'error' ? (
            <XCircle className="w-5 h-5 text-rose-600 shrink-0" />
          ) : (
            <AlertTriangle className="w-5 h-5 text-amber-600 shrink-0" />
          )}
          <div>
            <span className="font-bold text-xs uppercase tracking-wider block">
              {config?.connection_status === 'connected' ? "Connection Healthy" : config?.connection_status === 'error' ? "Connection Error" : "Untested Connection"}
            </span>
            <p className="text-xs opacity-90 mt-0.5">
              {config?.connection_status === 'connected' && `Last tested successfully (${config.last_connection_latency_ms || 120}ms) at ${new Date(config.last_connection_tested_at || Date.now()).toLocaleTimeString()}`}
              {config?.connection_status === 'error' && (config.last_connection_error || "Failed to reach NCM endpoints. Check API token and network.")}
              {config?.connection_status === 'untested' && "Run a connection test to verify API token authentication against active NCM servers."}
            </p>
          </div>
        </div>

        <div className="text-xs font-medium text-right shrink-0">
          Environment: <span className="font-bold uppercase">{config?.environment}</span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column (2 Cols): API Configuration & Branch Selection */}
        <div className="lg:col-span-2 space-y-6">
          {/* Card A: API Configuration */}
          <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs space-y-5">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <div className="flex items-center gap-2">
                <Key className="w-4 h-4 text-[#D4A72C]" />
                <h3 className="font-bold text-slate-900 text-sm">A. API & Authentication</h3>
              </div>
              <label className="flex items-center gap-2 text-xs font-semibold cursor-pointer">
                <input
                  type="checkbox"
                  checked={isEnabled}
                  onChange={(e) => setIsEnabled(e.target.checked)}
                  className="rounded text-[#0B2545] focus:ring-[#D4A72C] w-4 h-4"
                />
                <span className={isEnabled ? "text-emerald-700" : "text-slate-400"}>
                  {isEnabled ? "NCM Enabled" : "NCM Disabled"}
                </span>
              </label>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {/* Environment Selector */}
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">
                  Active Environment
                </label>
                <select
                  value={environment}
                  onChange={(e) => setEnvironment(e.target.value as any)}
                  className="w-full text-xs rounded-lg border border-slate-300 bg-white px-3 py-2 font-medium text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#D4A72C]/50"
                >
                  <option value="demo">Demo / Sandbox (https://demo.nepalcanmove.com)</option>
                  <option value="production">Production / Live (https://portal.nepalcanmove.com)</option>
                </select>
                <p className="text-[11px] text-slate-400 mt-1">
                  Production requires verified merchant credentials and dispatches actual shipments.
                </p>
              </div>

              {/* Token Status & Masked Display */}
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">
                  Active API Token Status
                </label>
                <div className="flex items-center gap-2">
                  <div className="flex-1 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-xs font-mono text-slate-700">
                    {config?.masked_token || "No Token Configured"}
                  </div>
                  <span className="text-[11px] font-medium px-2 py-1 rounded bg-slate-100 text-slate-600 capitalize">
                    {config?.token_source || "None"}
                  </span>
                </div>
                <p className="text-[11px] text-slate-400 mt-1">
                  Stored securely. Plaintext secrets are never returned in browser network calls.
                </p>
              </div>
            </div>

            {/* Render Environment Notice & Token Override */}
            <div className="bg-slate-50 border border-slate-200 rounded-lg p-3.5 space-y-2">
              <div className="flex items-start gap-2">
                <Info className="w-4 h-4 text-blue-600 shrink-0 mt-0.5" />
                <div className="text-xs text-slate-700 space-y-1">
                  <span className="font-semibold text-slate-900 block">Render Environment Best Practice:</span>
                  <p>
                    For production deployments on Render, configure <code className="bg-white px-1 py-0.5 rounded border border-slate-200 font-mono text-slate-900">NCM_API_TOKEN</code> in your Render Dashboard environment variables.
                  </p>
                  <p className="text-[11px] text-slate-500">
                    To override dynamically in the database without redeploying, enter a new token below:
                  </p>
                </div>
              </div>

              <div className="pt-2">
                <input
                  type="password"
                  value={newToken}
                  onChange={(e) => setNewToken(e.target.value)}
                  placeholder="Paste new API Token to override (e.g. ncm_live_...)"
                  className="w-full text-xs rounded-lg border border-slate-300 bg-white px-3 py-2 font-mono text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-[#D4A72C]/50"
                />
              </div>

              {config?.token_source === "DATABASE" && (
                <div className="flex items-center justify-between pt-1">
                  <span className="text-[11px] text-amber-700 font-medium">
                    Token is currently overridden in the database.
                  </span>
                  <button
                    type="button"
                    onClick={handleClearDatabaseToken}
                    disabled={saving}
                    className="text-[11px] text-rose-600 hover:text-rose-700 font-semibold underline disabled:opacity-50 cursor-pointer"
                  >
                    Reset to Render Environment Variable
                  </button>
                </div>
              )}
            </div>

            {/* Base URL override */}
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                Custom API Base URL (Optional)
              </label>
              <input
                type="text"
                value={customBaseUrl}
                onChange={(e) => setCustomBaseUrl(e.target.value)}
                placeholder={environment === 'production' ? "https://portal.nepalcanmove.com/api/" : "https://demo.nepalcanmove.com/api/"}
                className="w-full text-xs rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-800 font-mono placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-[#D4A72C]/50"
              />
              <p className="text-[11px] text-slate-400 mt-1">
                Leave blank to automatically use official NCM endpoints for the selected environment.
              </p>
            </div>
          </div>

          {/* Card B: Branch Configuration & Geographic Directory */}
          <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between pb-3 border-b border-slate-100 gap-2">
              <div className="flex items-center gap-2">
                <Server className="w-4 h-4 text-[#D4A72C]" />
                <h3 className="font-bold text-slate-900 text-sm">B. Default Origin Branch & Geographic Directory</h3>
                {/* Branch Provenance Badge */}
                <span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${
                  branchSource === 'LIVE_API'
                    ? 'bg-emerald-50 text-emerald-800 border-emerald-300'
                    : branchSource === 'DATABASE_CACHE'
                    ? 'bg-blue-50 text-blue-800 border-blue-300'
                    : 'bg-amber-50 text-amber-800 border-amber-300'
                }`}>
                  SOURCE: {branchSource}
                </span>
              </div>
              <div className="flex items-center gap-2">
                {branchLastSyncedAt && (
                  <span className="text-[11px] text-slate-400">
                    Synced: {new Date(branchLastSyncedAt).toLocaleTimeString()}
                  </span>
                )}
                <button
                  onClick={handleRefreshBranches}
                  disabled={refreshingBranches}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md bg-slate-100 text-slate-700 hover:bg-slate-200 transition-colors disabled:opacity-60"
                >
                  <RefreshCw className={`w-3 h-3 ${refreshingBranches ? "animate-spin text-[#D4A72C]" : ""}`} />
                  {refreshingBranches ? "Refreshing..." : `Refresh Live API (${branchesCount})`}
                </button>
              </div>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">
                  Default Origin Hub
                </label>
                {branches.length > 0 ? (
                  <select
                    value={originBranch}
                    onChange={(e) => setOriginBranch(e.target.value)}
                    className="w-full text-xs rounded-lg border border-slate-300 bg-white px-3 py-2 font-medium text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#D4A72C]/50"
                  >
                    {branches.map((b) => (
                      <option key={b.code || b.name} value={b.name}>
                        {b.name} {b.code ? `(${b.code})` : ""}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={originBranch}
                    onChange={(e) => setOriginBranch(e.target.value)}
                    placeholder="Kathmandu"
                    className="w-full text-xs rounded-lg border border-slate-300 bg-white px-3 py-2 font-medium text-slate-800"
                  />
                )}
                <p className="text-[11px] text-slate-400 mt-1">
                  Packages dispatched from LoksewaAI will be handed to this courier hub branch.
                </p>
              </div>

              {/* Geographic Nearest Branch Directory & Coordinate Review */}
              <div className="pt-3 border-t border-slate-100 space-y-3">
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                  <div className="flex items-center gap-1.5">
                    <Compass className="w-3.5 h-3.5 text-[#0B2545]" />
                    <span className="text-xs font-bold text-slate-800">Branch Coordinates & Serviceability Review</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="relative">
                      <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-2.5" />
                      <input
                        type="text"
                        value={branchSearch}
                        onChange={(e) => setBranchSearch(e.target.value)}
                        placeholder="Search branches..."
                        className="pl-8 pr-2.5 py-1 text-xs rounded-md border border-slate-200 w-36 sm:w-44 focus:outline-none focus:ring-1 focus:ring-[#D4A72C]"
                      />
                    </div>
                    <select
                      value={branchFilter}
                      onChange={(e) => setBranchFilter(e.target.value)}
                      className="text-xs rounded-md border border-slate-200 px-2 py-1 bg-white focus:outline-none"
                    >
                      <option value="all">All ({branches.length})</option>
                      <option value="verified">Verified Coordinates</option>
                      <option value="missing">Missing Coordinates</option>
                      <option value="suspended">Suspended Only</option>
                    </select>
                  </div>
                </div>

                {/* Branches Preview Table */}
                <div className="border border-slate-200 rounded-lg overflow-hidden max-h-64 overflow-y-auto">
                  <table className="w-full text-[11px] text-left">
                    <thead className="bg-slate-50 text-slate-600 font-semibold border-b border-slate-200 sticky top-0 z-10">
                      <tr>
                        <th className="px-3 py-2">Branch / Code</th>
                        <th className="px-3 py-2">District / Province</th>
                        <th className="px-3 py-2">Coordinates</th>
                        <th className="px-3 py-2">Status</th>
                        <th className="px-3 py-2 text-right">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {branches
                        .filter((b) => {
                          const matchSearch =
                            !branchSearch.trim() ||
                            b.name.toLowerCase().includes(branchSearch.toLowerCase()) ||
                            b.code.toLowerCase().includes(branchSearch.toLowerCase()) ||
                            b.district_name.toLowerCase().includes(branchSearch.toLowerCase());
                          if (!matchSearch) return false;
                          if (branchFilter === "verified") return Boolean(b.is_coordinate_verified);
                          if (branchFilter === "missing") return b.latitude == null || b.longitude == null;
                          if (branchFilter === "suspended") return b.is_serviceable === false;
                          return true;
                        })
                        .slice(0, 50)
                        .map((b) => (
                          <tr key={b.code} className="hover:bg-slate-50/70 transition-colors">
                            <td className="px-3 py-2 font-medium text-slate-800">
                              <div>{b.name}</div>
                              <span className="text-[10px] font-mono text-slate-400">{b.code}</span>
                            </td>
                            <td className="px-3 py-2 text-slate-600">
                              <div>{b.district_name}</div>
                              <span className="text-[10px] text-slate-400">{b.province_name}</span>
                            </td>
                            <td className="px-3 py-2">
                              {b.latitude != null && b.longitude != null ? (
                                <div className="space-y-0.5">
                                  <span className="font-mono text-[10px] text-slate-700">
                                    {Number(b.latitude).toFixed(4)}, {Number(b.longitude).toFixed(4)}
                                  </span>
                                  <div>
                                    <span className={`text-[9px] px-1.5 py-0.2 rounded font-semibold ${
                                      b.is_coordinate_verified
                                        ? "bg-emerald-100 text-emerald-800"
                                        : "bg-slate-100 text-slate-600"
                                    }`}>
                                      {b.coordinate_source || "UNVERIFIED"}
                                    </span>
                                  </div>
                                </div>
                              ) : (
                                <span className="text-rose-600 font-semibold text-[10px]">No Coordinates</span>
                              )}
                            </td>
                            <td className="px-3 py-2">
                              {b.is_serviceable === false ? (
                                <span className="text-[9px] px-1.5 py-0.5 rounded font-semibold bg-rose-100 text-rose-700">
                                  Suspended
                                </span>
                              ) : (
                                <span className="text-[9px] px-1.5 py-0.5 rounded font-semibold bg-emerald-100 text-emerald-700">
                                  Active
                                </span>
                              )}
                            </td>
                            <td className="px-3 py-2 text-right">
                              <button
                                type="button"
                                onClick={() => handleOpenEditBranch(b)}
                                className="inline-flex items-center gap-1 px-2 py-1 text-[10px] font-semibold rounded bg-[#0B2545]/10 text-[#0B2545] hover:bg-[#0B2545]/20 transition-colors"
                              >
                                <Edit2 className="w-2.5 h-2.5" />
                                Review
                              </button>
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>

          {/* Card C: Delivery Rates & Fallback Policy */}
          <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs space-y-4">
            <div className="flex items-center gap-2 pb-3 border-b border-slate-100">
              <Sliders className="w-4 h-4 text-[#D4A72C]" />
              <h3 className="font-bold text-slate-900 text-sm">C. Delivery Pricing & Rate Calculations</h3>
            </div>

            <div className="space-y-3 text-xs">
              <label className="flex items-start gap-3 p-3 bg-slate-50 rounded-lg border border-slate-100 cursor-pointer">
                <input
                  type="checkbox"
                  checked={liveRatesEnabled}
                  onChange={(e) => setLiveRatesEnabled(e.target.checked)}
                  className="rounded text-[#0B2545] focus:ring-[#D4A72C] w-4 h-4 mt-0.5"
                />
                <div>
                  <span className="font-semibold text-slate-900 block">Enable Live NCM Delivery Rates</span>
                  <p className="text-slate-500 text-[11px] mt-0.5">
                    Queries <code className="font-mono bg-white px-1 py-0.5 rounded border border-slate-200">/v1/shipping-rate</code> dynamically during student checkout based on destination branch and origin hub.
                  </p>
                </div>
              </label>

              <label className="flex items-start gap-3 p-3 bg-slate-50 rounded-lg border border-slate-100 cursor-pointer">
                <input
                  type="checkbox"
                  checked={fallbackRulesEnabled}
                  onChange={(e) => setFallbackRulesEnabled(e.target.checked)}
                  className="rounded text-[#0B2545] focus:ring-[#D4A72C] w-4 h-4 mt-0.5"
                />
                <div>
                  <span className="font-semibold text-slate-900 block">Enable Fallback to Local Rules</span>
                  <p className="text-slate-500 text-[11px] mt-0.5">
                    If NCM API encounters a network timeout or connection error, safely calculate delivery fee using the platform's Admin Delivery Fee Rules instead of blocking the checkout.
                  </p>
                </div>
              </label>

              <div className="p-3 bg-blue-50/70 border border-blue-200 rounded-lg text-blue-900 flex items-center justify-between">
                <div>
                  <span className="font-semibold block">Fallback Pricing Source:</span>
                  <span className="text-[11px] text-blue-800">Admin Delivery Fee Rules (Kathmandu Valley / Outside Valley)</span>
                </div>
                <Link
                  href="/admin-dashboard/marketplace/delivery-fees"
                  className="text-xs font-semibold text-blue-700 hover:text-blue-900 underline"
                >
                  Configure Rules
                </Link>
              </div>
            </div>
          </div>
        </div>

        {/* Right Column (1 Col): Webhooks & Synchronization */}
        <div className="space-y-6">
          {/* Webhook Management Card */}
          <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <div className="flex items-center gap-2">
                <Globe className="w-4 h-4 text-[#D4A72C]" />
                <h3 className="font-bold text-slate-900 text-sm">D. Webhook Management</h3>
              </div>
              <button
                onClick={handleToggleWebhook}
                className={`text-xs font-semibold px-2 py-1 rounded ${webhookEnabled ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' : 'bg-slate-100 text-slate-600'}`}
              >
                {webhookEnabled ? "Receiver Active" : "Receiver Off"}
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <div>
                <span className="text-slate-500 block mb-1">Generated Webhook URL:</span>
                <div className="flex items-center gap-1.5">
                  <input
                    type="text"
                    readOnly
                    value={config?.webhook_endpoint_url || ""}
                    className="flex-1 bg-slate-50 border border-slate-200 rounded px-2.5 py-1.5 text-[11px] font-mono text-slate-700"
                  />
                  <button
                    onClick={handleCopyWebhookUrl}
                    className="p-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded transition-colors"
                    title="Copy URL"
                  >
                    {copiedUrl ? <Check className="w-4 h-4 text-emerald-600" /> : <Copy className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              <div className="pt-2 border-t border-slate-100 space-y-2">
                <div className="flex justify-between">
                  <span className="text-slate-500">HMAC Secret Status:</span>
                  <span className={`font-semibold ${config?.render_env_status?.webhook_secret_in_env ? 'text-emerald-700' : 'text-slate-400'}`}>
                    {config?.render_env_status?.webhook_secret_status || "Not Configured"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Last Received Event:</span>
                  <span className="font-mono text-slate-800">
                    {config?.last_webhook_event || "None"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Last Event Time:</span>
                  <span className="text-slate-700">
                    {config?.last_webhook_received_at ? new Date(config.last_webhook_received_at).toLocaleTimeString() : "Never"}
                  </span>
                </div>
              </div>

              {/* Recent Webhook Events */}
              <div className="pt-3 border-t border-slate-100">
                <span className="font-semibold text-slate-800 block mb-2">Recent Event History:</span>
                {recentWebhooks.length === 0 ? (
                  <p className="text-[11px] text-slate-400 italic">No webhook payloads logged yet.</p>
                ) : (
                  <div className="max-h-40 overflow-y-auto space-y-1.5 font-mono text-[10px]">
                    {recentWebhooks.map((ev) => (
                      <div key={ev.id} className="p-2 bg-slate-50 rounded border border-slate-100 flex justify-between items-center">
                        <div>
                          <span className={`font-bold ${ev.is_success ? 'text-emerald-600' : 'text-rose-600'}`}>
                            {ev.event_type}
                          </span>
                          <span className="text-slate-500 block">NCM #{ev.ncm_order_id}</span>
                        </div>
                        <span className="text-slate-400">
                          {new Date(ev.received_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Automatic Synchronization Card */}
          <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <div className="flex items-center gap-2">
                <RefreshCw className="w-4 h-4 text-[#D4A72C]" />
                <h3 className="font-bold text-slate-900 text-sm">E. Synchronization Scheduler</h3>
              </div>
              <label className="flex items-center gap-1.5 text-xs font-semibold cursor-pointer">
                <input
                  type="checkbox"
                  checked={autoSyncEnabled}
                  onChange={(e) => setAutoSyncEnabled(e.target.checked)}
                  className="rounded text-[#0B2545] focus:ring-[#D4A72C] w-4 h-4"
                />
                <span className={autoSyncEnabled ? "text-emerald-700" : "text-slate-400"}>
                  {autoSyncEnabled ? "Active" : "Paused"}
                </span>
              </label>
            </div>

            <div className="space-y-3 text-xs">
              <div className="p-3 bg-amber-50/70 border border-amber-200 rounded-lg text-amber-900">
                <span className="font-semibold block mb-0.5">Render Cron Job Scheduling:</span>
                <p className="text-[11px] text-amber-800 leading-relaxed">
                  Shipment polling runs automatically via Render Scheduled Job. The execution interval is configured in the Render Dashboard under Cron Jobs.
                </p>
                <div className="mt-2 font-mono text-[10px] bg-white/80 p-1.5 rounded border border-amber-200">
                  python manage.py sync_ncm_shipments --limit 50
                </div>
              </div>

              <div className="space-y-1.5 pt-1">
                <div className="flex justify-between">
                  <span className="text-slate-500">Last Batch Sync:</span>
                  <span className="font-semibold text-slate-800">
                    {config?.last_sync_at ? new Date(config.last_sync_at).toLocaleString() : "Never"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Last Batch Result:</span>
                  <span className="font-semibold text-slate-800 uppercase">
                    {config?.last_sync_status || "N/A"}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Production Switch Confirmation Modal */}
      {showProductionModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl max-w-md w-full p-6 shadow-2xl border border-rose-200 animate-in fade-in zoom-in-95">
            <div className="flex items-center gap-3 text-rose-600 mb-3">
              <AlertTriangle className="w-6 h-6 shrink-0" />
              <h3 className="text-base font-bold text-slate-900">Confirm Switch to Live Production</h3>
            </div>

            <div className="text-xs text-slate-600 space-y-2 mb-4">
              <p className="font-medium text-slate-800">
                You are about to switch the Nepal Can Move integration to the <strong>LIVE PRODUCTION</strong> environment.
              </p>
              <ul className="list-disc pl-5 space-y-1 text-slate-500">
                <li>All subsequent order dispatches will create actual courier shipments.</li>
                <li>Actual shipping charges will be invoiced to your NCM merchant account.</li>
                <li>Ensure you have configured your official Live NCM API token in Render.</li>
              </ul>
            </div>

            <div className="mb-4">
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                Type <span className="font-mono text-rose-600 font-bold">PRODUCTION</span> to confirm:
              </label>
              <input
                type="text"
                value={confirmProductionText}
                onChange={(e) => setConfirmProductionText(e.target.value)}
                placeholder="PRODUCTION"
                className="w-full text-xs rounded-lg border border-slate-300 px-3 py-2 font-mono uppercase focus:outline-none focus:ring-2 focus:ring-rose-500/50"
              />
            </div>

            <div className="flex justify-end gap-2.5">
              <button
                onClick={() => {
                  setShowProductionModal(false);
                  setEnvironment("demo");
                }}
                className="px-4 py-2 rounded-lg text-xs font-semibold bg-slate-100 text-slate-700 hover:bg-slate-200 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => handleSaveSettings(true)}
                disabled={confirmProductionText.trim() !== "PRODUCTION"}
                className="px-4 py-2 rounded-lg text-xs font-semibold bg-rose-600 text-white hover:bg-rose-700 transition-colors disabled:opacity-50"
              >
                Confirm & Switch
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Branch Coordinates & Status Edit Dialog */}
      {editingBranch && (
        <Dialog open={Boolean(editingBranch)} onOpenChange={(open) => !open && setEditingBranch(null)}>
          <DialogContent className="max-w-md">
            <DialogHeader>
              <DialogTitle className="text-base font-bold text-slate-900 flex items-center gap-2">
                <MapPin className="w-4 h-4 text-[#D4A72C]" />
                Review Coordinates: {editingBranch.name}
              </DialogTitle>
            </DialogHeader>

            <div className="space-y-4 pt-2 text-xs">
              <div className="p-3 bg-slate-50 rounded-lg space-y-1">
                <div className="font-semibold text-slate-800">
                  {editingBranch.name} ({editingBranch.code})
                </div>
                <div className="text-slate-500">
                  {editingBranch.district_name}, {editingBranch.province_name}
                </div>
                {editingBranch.address && (
                  <div className="text-slate-400 text-[11px]">{editingBranch.address}</div>
                )}
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Latitude</label>
                  <input
                    type="number"
                    step="0.000001"
                    value={editLat}
                    onChange={(e) => setEditLat(e.target.value)}
                    placeholder="e.g. 27.7172"
                    className="w-full text-xs font-mono rounded-lg border border-slate-300 px-3 py-2 bg-white"
                  />
                </div>
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Longitude</label>
                  <input
                    type="number"
                    step="0.000001"
                    value={editLon}
                    onChange={(e) => setEditLon(e.target.value)}
                    placeholder="e.g. 85.3240"
                    className="w-full text-xs font-mono rounded-lg border border-slate-300 px-3 py-2 bg-white"
                  />
                </div>
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">Coordinate Source</label>
                <select
                  value={editSource}
                  onChange={(e) => setEditSource(e.target.value)}
                  className="w-full text-xs rounded-lg border border-slate-300 px-3 py-2 bg-white"
                >
                  <option value="ADMIN_VERIFIED">Admin Verified (GPS / Physical Visit)</option>
                  <option value="GEOCODED">Geocoded Address / Place</option>
                  <option value="API">NCM API Direct</option>
                  <option value="MUNICIPALITY_CENTROID">Municipality Centroid Fallback</option>
                  <option value="DISTRICT_CENTROID">District Centroid Fallback</option>
                  <option value="UNVERIFIED">Unverified / Approximate</option>
                </select>
              </div>

              <div className="space-y-2 pt-1 border-t border-slate-100">
                <label className="flex items-center gap-2 cursor-pointer font-medium text-slate-800">
                  <input
                    type="checkbox"
                    checked={editVerified}
                    onChange={(e) => setEditVerified(e.target.checked)}
                    className="rounded text-[#0B2545] focus:ring-[#D4A72C] w-4 h-4"
                  />
                  Mark coordinates as verified
                </label>

                <label className="flex items-center gap-2 cursor-pointer font-medium text-slate-800">
                  <input
                    type="checkbox"
                    checked={editServiceable}
                    onChange={(e) => setEditServiceable(e.target.checked)}
                    className="rounded text-[#0B2545] focus:ring-[#D4A72C] w-4 h-4"
                  />
                  Active & Serviceable for dispatch
                </label>
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">Serviceability Notes</label>
                <input
                  type="text"
                  value={editNotes}
                  onChange={(e) => setEditNotes(e.target.value)}
                  placeholder="e.g. Road open, regular daily dispatches"
                  className="w-full text-xs rounded-lg border border-slate-300 px-3 py-2 bg-white"
                />
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">Audit Reason</label>
                <input
                  type="text"
                  value={editReason}
                  onChange={(e) => setEditReason(e.target.value)}
                  placeholder="e.g. Verified coordinates during hub inspection"
                  className="w-full text-xs rounded-lg border border-slate-300 px-3 py-2 bg-white"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setEditingBranch(null)}
                  className="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-slate-100 text-slate-700 hover:bg-slate-200"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleSaveBranchCoordinates}
                  disabled={savingBranch}
                  className="px-4 py-1.5 rounded-lg text-xs font-semibold bg-[#0B2545] text-white hover:bg-[#133966] disabled:opacity-50"
                >
                  {savingBranch ? "Saving..." : "Save Coordinates"}
                </button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
