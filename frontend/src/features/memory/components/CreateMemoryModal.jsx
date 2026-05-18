import React, { useState } from 'react';
import { Plus, Loader2 } from 'lucide-react';
import { createMemory } from '../../../lib/api';

export default function CreateMemoryModal({ isOpen, onClose, onCreated, parentPath, currentDomain }) {
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [priority, setPriority] = useState(0);
  const [disclosure, setDisclosure] = useState('');
  const [domain, setDomain] = useState(currentDomain);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const handleCreate = async () => {
    if (!content.trim() || !disclosure.trim()) return;
    setSaving(true);
    setError('');
    try {
      const result = await createMemory({
        parent_path: parentPath,
        content: content.trim(),
        priority,
        disclosure: disclosure.trim(),
        title: title.trim() || undefined,
        domain,
      });
      onCreated(result.uri);
      // Reset form
      setTitle('');
      setContent('');
      setPriority(0);
      setDisclosure('');
      setDomain(currentDomain);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleClose = () => {
    if (saving) return;
    setTitle('');
    setContent('');
    setPriority(0);
    setDisclosure('');
    setDomain(currentDomain);
    setError('');
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
      onClick={handleClose}
    >
      <div
        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-[#0C0C14] border border-slate-800 rounded-xl p-6 max-w-lg w-[calc(100%-2rem)] shadow-2xl max-h-[90vh] overflow-y-auto custom-scrollbar"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 mb-5">
          <div className="p-2.5 rounded-lg bg-emerald-950/40 text-emerald-400">
            <Plus size={20} />
          </div>
          <div>
            <h3 className="text-base font-bold text-slate-100">Create Memory</h3>
            <p className="text-xs text-slate-500 mt-0.5">Add a new node to the memory tree</p>
          </div>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-rose-950/20 border border-rose-900/30 rounded-lg text-rose-400 text-sm">
            {error}
          </div>
        )}

        <div className="space-y-4">
          {/* Title */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-400 flex items-center gap-1">
              Title <span className="text-slate-600 font-normal">(optional)</span>
            </label>
            <input
              type="text"
              value={title}
              onChange={e => setTitle(e.target.value)}
              placeholder="e.g. my_memory"
              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 font-mono focus:outline-none focus:border-indigo-500/50 transition-colors"
            />
            <p className="text-[10px] text-slate-600">alphanumeric, hyphens, underscores only</p>
          </div>

          {/* Domain */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-400">Domain</label>
            <input
              type="text"
              value={domain}
              onChange={e => setDomain(e.target.value)}
              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 font-mono focus:outline-none focus:border-indigo-500/50 transition-colors"
            />
          </div>

          {/* Parent path (readonly) */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-400">Parent path</label>
            <div className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-indigo-300/70 font-mono select-all">
              {domain}://{parentPath || 'root'}
            </div>
          </div>

          {/* Priority */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-400">
              Priority
              <span className="text-slate-600 font-normal ml-1">(lower = higher priority)</span>
            </label>
            <input
              type="number"
              min="0"
              value={priority}
              onChange={e => setPriority(parseInt(e.target.value) || 0)}
              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 font-mono focus:outline-none focus:border-indigo-500/50 transition-colors"
            />
          </div>

          {/* Disclosure */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-400">
              Disclosure <span className="text-rose-400">*</span>
            </label>
            <input
              type="text"
              value={disclosure}
              onChange={e => setDisclosure(e.target.value)}
              placeholder="When to recall this memory..."
              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/50 transition-colors"
            />
          </div>

          {/* Content */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-400">
              Content <span className="text-rose-400">*</span>
            </label>
            <textarea
              value={content}
              onChange={e => setContent(e.target.value)}
              placeholder="Memory content..."
              className="w-full h-64 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 font-mono focus:outline-none focus:border-indigo-500/50 transition-colors resize-y"
              spellCheck={false}
            />
          </div>
        </div>

        <div className="flex gap-3 justify-end mt-6 pt-4 border-t border-slate-800/50">
          <button
            onClick={handleClose}
            disabled={saving}
            className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 bg-slate-800 hover:bg-slate-700 rounded-lg border border-slate-700 transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={handleCreate}
            disabled={saving || !content.trim() || !disclosure.trim()}
            className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-emerald-600 hover:bg-emerald-500 rounded-lg transition-colors shadow-lg shadow-emerald-900/20 disabled:opacity-50"
          >
            {saving ? (
              <>
                <Loader2 size={16} className="animate-spin" />
                Creating...
              </>
            ) : (
              <>
                <Plus size={16} />
                Create Memory
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
