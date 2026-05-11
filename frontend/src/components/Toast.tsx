import React, { useState, useCallback, useRef, useEffect } from 'react';

export type ToastType = 'info' | 'success' | 'warning' | 'error';

interface Toast {
  id: number;
  message: string;
  type: ToastType;
}

interface ToastContextValue {
  showToast: (message: string, type?: ToastType, duration?: number) => void;
}

export const ToastContext = React.createContext<ToastContextValue>({
  showToast: () => {},
});

const ICONS: Record<ToastType, string> = {
  info: 'ℹ️',
  success: '✅',
  warning: '⚠️',
  error: '❌',
};

const COLORS: Record<ToastType, string> = {
  info:    'rgba(74, 144, 217, 0.15)',
  success: 'rgba(90, 154, 106, 0.15)',
  warning: 'rgba(212, 168, 67, 0.15)',
  error:   'rgba(196, 75, 75, 0.15)',
};

const BORDER_COLORS: Record<ToastType, string> = {
  info:    'rgba(74, 144, 217, 0.5)',
  success: 'rgba(90, 154, 106, 0.5)',
  warning: 'rgba(212, 168, 67, 0.5)',
  error:   'rgba(196, 75, 75, 0.5)',
};

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: (id: number) => void }) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    // 进场动画
    requestAnimationFrame(() => setVisible(true));
  }, []);

  const dismiss = () => {
    setVisible(false);
    setTimeout(() => onDismiss(toast.id), 300);
  };

  return (
    <div
      onClick={dismiss}
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: '10px',
        padding: '12px 16px',
        background: COLORS[toast.type],
        border: `1px solid ${BORDER_COLORS[toast.type]}`,
        borderRadius: '8px',
        backdropFilter: 'blur(12px)',
        boxShadow: '0 4px 16px rgba(0,0,0,0.4)',
        cursor: 'pointer',
        maxWidth: '360px',
        fontSize: '0.875rem',
        color: 'var(--text-primary)',
        lineHeight: '1.4',
        opacity: visible ? 1 : 0,
        transform: visible ? 'translateX(0)' : 'translateX(40px)',
        transition: 'opacity 0.3s ease, transform 0.3s ease',
        pointerEvents: 'all',
        userSelect: 'none',
      }}
    >
      <span style={{ fontSize: '1rem', flexShrink: 0, marginTop: '1px' }}>
        {ICONS[toast.type]}
      </span>
      <span style={{ flex: 1 }}>{toast.message}</span>
    </div>
  );
}

let _toastCounter = 0;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const timers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());

  const dismiss = useCallback((id: number) => {
    setToasts(prev => prev.filter(t => t.id !== id));
    const timer = timers.current.get(id);
    if (timer) { clearTimeout(timer); timers.current.delete(id); }
  }, []);

  const showToast = useCallback((message: string, type: ToastType = 'info', duration = 4000) => {
    const id = ++_toastCounter;
    setToasts(prev => [...prev, { id, message, type }]);
    const timer = setTimeout(() => dismiss(id), duration);
    timers.current.set(id, timer);
  }, [dismiss]);

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      {/* Toast 容器 — 右下角显示 */}
      <div style={{
        position: 'fixed',
        bottom: '24px',
        right: '24px',
        zIndex: 9999,
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
        pointerEvents: 'none',
        alignItems: 'flex-end',
      }}>
        {toasts.map(t => (
          <ToastItem key={t.id} toast={t} onDismiss={dismiss} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

/** 便捷 hook */
export function useToast() {
  return React.useContext(ToastContext);
}
