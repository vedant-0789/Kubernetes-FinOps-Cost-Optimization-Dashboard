import React from 'react';
import { AlertTriangle, X } from 'lucide-react';

export default function Modal({ isOpen, onClose, onConfirm, title, description, confirmText = 'Confirm Action', isDestructive = false, isLoading = false }) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in">
      <div className="w-full max-w-md glass-panel rounded-2xl p-6 border border-slate-700 shadow-2xl relative">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="flex items-start gap-4">
          <div className={`p-3 rounded-xl shrink-0 ${isDestructive ? 'bg-rose-500/20 text-rose-400 border border-rose-500/30' : 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'}`}>
            <AlertTriangle className="w-6 h-6" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-white tracking-tight">{title}</h3>
            <p className="mt-2 text-sm text-slate-300 leading-relaxed">{description}</p>
          </div>
        </div>

        <div className="mt-6 flex items-center justify-end gap-3 pt-4 border-t border-slate-800">
          <button
            onClick={onClose}
            disabled={isLoading}
            className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-300 hover:bg-slate-800 border border-slate-700 transition-all"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={isLoading}
            className={`px-4 py-2 rounded-xl text-xs font-semibold text-white shadow-lg transition-all flex items-center gap-2 ${
              isDestructive
                ? 'bg-rose-600 hover:bg-rose-500 shadow-rose-600/30'
                : 'bg-emerald-600 hover:bg-emerald-500 shadow-emerald-600/30'
            } disabled:opacity-50`}
          >
            {isLoading ? 'Processing...' : confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}
