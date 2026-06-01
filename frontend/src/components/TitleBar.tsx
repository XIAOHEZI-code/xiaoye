import React from 'react';
import { Minus, Square, X, RefreshCw } from 'lucide-react';
import { ipcRenderer } from 'electron';

export const TitleBar: React.FC = () => {
  return (
    <div style={{
      height: '32px',
      width: '100%',
      background: 'var(--bg-color)', // 动态跟随主题
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      WebkitAppRegion: 'drag', // 允许拖拽窗口
      userSelect: 'none',
      borderBottom: '1px solid var(--glass-border)',
      position: 'relative',
      zIndex: 9999,
      flexShrink: 0,
    } as React.CSSProperties}>
      
      {/* 标题 */}
      <div style={{ paddingLeft: '80px', fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={{ display: 'inline-block', width: '12px', height: '12px', borderRadius: '50%', background: 'var(--accent)' }}></span>
        小冶 - 冶金智慧文献平台
      </div>
      
      {/* 右侧控制按钮（仅 Windows/Linux 显示比较合适，如果你想全平台一致的话也可以加上） */}
      <div style={{ display: 'flex', height: '100%', WebkitAppRegion: 'no-drag' } as React.CSSProperties}>
        <button 
          onClick={() => window.location.reload()}
          className="window-control-btn"
          title="重新加载页面"
        >
          <RefreshCw size={14} />
        </button>
        <button 
          onClick={() => ipcRenderer.send('window-min')}
          className="window-control-btn"
        >
          <Minus size={16} />
        </button>
        <button 
          onClick={() => ipcRenderer.send('window-max')}
          className="window-control-btn"
        >
          <Square size={13} />
        </button>
        <button 
          onClick={() => ipcRenderer.send('window-close')}
          className="window-control-btn close-btn"
        >
          <X size={16} />
        </button>
      </div>
    </div>
  );
};
