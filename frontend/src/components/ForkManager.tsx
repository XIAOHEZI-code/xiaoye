import React from 'react';
import type { TaskEvent } from '../App';

interface Props {
  tasks: TaskEvent[];
  style?: React.CSSProperties;
}

const STATUS_COLOR: Record<string, string> = {
  running:   'var(--accent)',
  queued:    'var(--status-pending)',
  completed: 'var(--success)',
  failed:    'var(--status-error)',
};

const STATUS_LABEL: Record<string, string> = {
  running:   '执行中',
  queued:    '排队中',
  completed: '已完成',
  failed:    '失败',
};

/**
 * ForkManager — 显示真实的 activeTasks 列表（接入 App.tsx 的 SSE 数据流）
 */
export default function ForkManager({ tasks, style }: Props) {
  const activeTasks = tasks.filter(t => !t.patch?.endsWith('---\n'));

  return (
    <div
      className="glass-panel"
      style={{
        display: 'flex',
        flexDirection: 'column',
        padding: '0',
        overflow: 'hidden',
        ...style,
      }}
    >
      <div className="panel-header" style={{ fontSize: '0.85rem', padding: '10px 14px' }}>
        <span>⚡ Fork 任务</span>
        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          {activeTasks.length > 0 ? `${activeTasks.length} 个运行中` : '空闲'}
        </span>
      </div>

      <div className="panel-content" style={{ padding: '8px 12px', flex: 1, overflowY: 'auto' }}>
        {activeTasks.length === 0 ? (
          <div style={{
            textAlign: 'center',
            padding: '16px 0',
            color: 'var(--text-muted)',
            fontSize: '0.8rem',
          }}>
            <div style={{ marginBottom: '6px', opacity: 0.5 }}>⚙️</div>
            暂无活跃任务
            <div style={{ fontSize: '0.72rem', marginTop: '4px', opacity: 0.7 }}>
              圈选 PDF 区域后右键触发
            </div>
          </div>
        ) : (
          <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {activeTasks.map(task => {
              const status = task.type === 'reasoning' ? 'running' : 'queued';
              return (
                <li
                  key={task.task_id}
                  style={{
                    marginBottom: '6px',
                    padding: '8px 10px',
                    background: 'rgba(0,0,0,0.2)',
                    borderRadius: '6px',
                    border: `1px solid ${STATUS_COLOR[status] || 'var(--glass-border)'}22`,
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    fontSize: '0.8rem',
                  }}
                >
                  <span style={{
                    color: 'var(--text-secondary)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    maxWidth: '100px',
                  }}>
                    {task.task_id}
                  </span>
                  <span style={{
                    color: STATUS_COLOR[status] || 'var(--text-muted)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '5px',
                    flexShrink: 0,
                  }}>
                    {status === 'running' && (
                      <span style={{
                        display: 'inline-block',
                        width: '6px',
                        height: '6px',
                        borderRadius: '50%',
                        background: 'var(--accent)',
                        animation: 'pulse 1.5s ease-in-out infinite',
                      }} />
                    )}
                    {STATUS_LABEL[status] || status}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
