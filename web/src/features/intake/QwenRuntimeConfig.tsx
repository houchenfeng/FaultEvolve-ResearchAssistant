import { useEffect, useState } from 'react';

type QwenStatus = { base_url: string; configured: boolean; reachable: boolean | null };
const DEFAULT_BASE = 'https://dashscope.aliyuncs.com/compatible-mode/v1';

export function QwenRuntimeConfig() {
  const [baseUrl, setBaseUrl] = useState(DEFAULT_BASE);
  const [status, setStatus] = useState<QwenStatus | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  const readStatus = async () => {
    try {
      const response = await fetch('/api/qwen/config');
      if (!response.ok) return;
      const data = await response.json() as QwenStatus;
      setStatus(data); setBaseUrl(data.base_url);
    } catch { /* 页面仍可编辑，保存时给出明确结果。 */ }
  };
  useEffect(() => { void readStatus(); }, []);

  const save = async () => {
    setSaving(true); setMessage('');
    try {
      const response = await fetch('/api/qwen/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ base_url: baseUrl }) });
      if (!response.ok) throw new Error('保存失败，请检查 Base URL 或服务状态。');
      const data = await response.json() as QwenStatus;
      setStatus(data); setMessage('Base URL 已保存并完成连通检查。');
    } catch (error) { setMessage(error instanceof Error ? error.message : '保存失败。'); }
    finally { setSaving(false); }
  };

  const tone = status?.reachable === true ? 'text-success-700 bg-success-50' : status?.configured ? 'text-warning-700 bg-warning-50' : 'text-fg-muted bg-surface-muted';
  return <section className="fe-card-panel overflow-hidden" data-qwen-runtime-config>
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border-subtle px-4 py-3"><div><h2 className="text-sm font-semibold text-fg">Qwen 模型服务</h2><p className="mt-1 text-[11px] text-fg-muted">用于候选生成、反思与知识辩论；密钥不会从服务端回传。</p></div><span className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${tone}`}>{status?.reachable === true ? '已连通' : status?.configured ? '已配置，待连通' : '未配置'}</span></div>
    <div className="grid gap-3 p-4 lg:grid-cols-[1.4fr_1fr_auto]">
      <label className="flex flex-col gap-1 text-[11px]"><span className="text-fg-subtle">Base URL</span><input className="fe-input fe-input-sm font-mono" value={baseUrl} onChange={(e)=>setBaseUrl(e.target.value)} placeholder={DEFAULT_BASE}/></label>
      <label className="flex flex-col gap-1 text-[11px]"><span className="text-fg-subtle">API Key</span><input readOnly type="password" className="fe-input fe-input-sm font-mono" value={status?.configured ? 'configured-secret' : ''} placeholder="由服务环境变量 DASHSCOPE_API_KEY 提供"/><span className="text-[10px] text-fg-subtle">密钥仅从服务端环境读取，不进入网页请求或响应。</span></label>
      <div className="flex items-end gap-2"><button type="button" className="fe-btn fe-btn-primary fe-btn-sm" disabled={saving} onClick={()=>void save()}>{saving ? '检查中…' : '保存并测试'}</button></div>
    </div>
    {message ? <p className="px-4 pb-3 text-[11px] text-fg-muted">{message}</p> : null}
  </section>;
}
