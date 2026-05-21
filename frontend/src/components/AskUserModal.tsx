import React, { useState, useEffect, useRef } from 'react';

/**
 * AskUser 求问事件的数据结构（与后端 SSE 推送一致）
 */
export interface AskUserEventData {
  ask_id: string;
  task_id: string;
  question: string;
  ask_type: 'confirm' | 'choice' | 'text';
  options: { label: string; value: string }[];
  default_value?: string;
  timeout_seconds: number;
}

interface Props {
  event: AskUserEventData | null;
  onReply: (askId: string, taskId: string, reply: string) => void;
  onDismiss: () => void;
}

/**
 * AskUserModal — AI 主动求问弹窗
 *
 * 三种模式：
 *   - confirm: 是/否 确认
 *   - choice:  单选列表
 *   - text:    自由输入
 *
 * 带超时倒计时，超时后自动关闭。
 */
const AskUserModal: React.FC<Props> = ({ event, onReply, onDismiss }) => {
  const [textValue, setTextValue] = useState('');
  const [selectedChoice, setSelectedChoice] = useState<string | null>(null);
  const [countdown, setCountdown] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (event) {
      setTextValue(event.default_value || '');
      setSelectedChoice(event.options?.[0]?.value || null);
      setCountdown(event.timeout_seconds);

      // 自动聚焦
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [event]);

  // 倒计时
  useEffect(() => {
    if (!event || countdown <= 0) return;
    const timer = setInterval(() => {
      setCountdown(prev => {
        if (prev <= 1) {
          onDismiss();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [event, countdown, onDismiss]);

  if (!event) return null;

  const handleSubmit = (reply: string) => {
    onReply(event.ask_id, event.task_id, reply);
  };

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  return (
    <>
      {/* 遮罩层 */}
      <div
        style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(0, 0, 0, 0.6)',
          backdropFilter: 'blur(4px)',
          zIndex: 9998,
          animation: 'fadeIn 0.2s ease',
        }}
        onClick={onDismiss}
      />

      {/* 弹窗主体 */}
      <div
        style={{
          position: 'fixed',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          zIndex: 9999,
          background: 'var(--panel-bg)',
          border: '1px solid var(--accent)',
          borderRadius: '16px',
          padding: '28px 32px',
          minWidth: '380px',
          maxWidth: '520px',
          boxShadow: '0 24px 80px rgba(0, 0, 0, 0.5), 0 0 0 1px var(--glass-border)',
          animation: 'slideUp 0.3s cubic-bezier(0.34, 1.56, 0.64, 1)',
        }}
      >
        {/* 标题栏 */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '16px',
        }}>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            fontSize: '0.95rem',
            fontWeight: 700,
            color: 'var(--accent)',
          }}>
            <span style={{
              display: 'inline-block',
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              background: 'var(--accent)',
              animation: 'pulse 1.5s ease-in-out infinite',
            }} />
            小冶需要您的确认
          </div>
          <span style={{
            fontSize: '0.72rem',
            color: countdown < 30 ? 'var(--status-error)' : 'var(--text-muted)',
            fontFamily: 'monospace',
          }}>
            ⏱ {formatTime(countdown)}
          </span>
        </div>

        {/* 问题文本 */}
        <div style={{
          fontSize: '0.92rem',
          color: 'var(--text-primary)',
          lineHeight: 1.6,
          marginBottom: '20px',
          padding: '12px 16px',
          background: 'rgba(0, 0, 0, 0.2)',
          borderRadius: '8px',
          border: '1px solid var(--glass-border)',
        }}>
          {event.question}
        </div>

        {/* 操作区 — 根据 ask_type 渲染不同 UI */}
        {event.ask_type === 'confirm' && (
          <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
            <button
              onClick={() => handleSubmit('no')}
              style={{
                padding: '8px 20px',
                borderRadius: '8px',
                border: '1px solid var(--glass-border)',
                background: 'rgba(0,0,0,0.3)',
                color: 'var(--text-secondary)',
                cursor: 'pointer',
                fontSize: '0.85rem',
                transition: 'all 0.15s',
              }}
            >
              ✕ 取消
            </button>
            <button
              onClick={() => handleSubmit('yes')}
              style={{
                padding: '8px 20px',
                borderRadius: '8px',
                border: 'none',
                background: 'var(--accent)',
                color: 'white',
                cursor: 'pointer',
                fontSize: '0.85rem',
                fontWeight: 600,
                transition: 'all 0.15s',
              }}
            >
              ✓ 确认
            </button>
          </div>
        )}

        {event.ask_type === 'choice' && (
          <div>
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '8px',
              marginBottom: '16px',
            }}>
              {event.options.map(opt => (
                <label
                  key={opt.value}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',
                    padding: '10px 14px',
                    borderRadius: '8px',
                    border: selectedChoice === opt.value
                      ? '1px solid var(--accent)'
                      : '1px solid var(--glass-border)',
                    background: selectedChoice === opt.value
                      ? 'var(--accent-light)'
                      : 'rgba(0,0,0,0.15)',
                    cursor: 'pointer',
                    transition: 'all 0.15s',
                    fontSize: '0.88rem',
                    color: 'var(--text-primary)',
                  }}
                  onClick={() => setSelectedChoice(opt.value)}
                >
                  <span style={{
                    width: '16px',
                    height: '16px',
                    borderRadius: '50%',
                    border: `2px solid ${selectedChoice === opt.value ? 'var(--accent)' : 'var(--text-muted)'}`,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexShrink: 0,
                  }}>
                    {selectedChoice === opt.value && (
                      <span style={{
                        width: '8px',
                        height: '8px',
                        borderRadius: '50%',
                        background: 'var(--accent)',
                      }} />
                    )}
                  </span>
                  {opt.label}
                </label>
              ))}
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button
                onClick={() => selectedChoice && handleSubmit(selectedChoice)}
                disabled={!selectedChoice}
                style={{
                  padding: '8px 20px',
                  borderRadius: '8px',
                  border: 'none',
                  background: selectedChoice ? 'var(--accent)' : 'var(--text-muted)',
                  color: 'white',
                  cursor: selectedChoice ? 'pointer' : 'default',
                  fontSize: '0.85rem',
                  fontWeight: 600,
                  opacity: selectedChoice ? 1 : 0.5,
                }}
              >
                提交选择
              </button>
            </div>
          </div>
        )}

        {event.ask_type === 'text' && (
          <div>
            <input
              ref={inputRef}
              type="text"
              value={textValue}
              onChange={e => setTextValue(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && textValue.trim()) {
                  handleSubmit(textValue.trim());
                }
              }}
              placeholder="请输入您的回复..."
              style={{
                width: '100%',
                padding: '10px 14px',
                borderRadius: '8px',
                border: '1px solid var(--glass-border)',
                background: 'rgba(0,0,0,0.3)',
                color: 'var(--text-primary)',
                fontSize: '0.88rem',
                outline: 'none',
                marginBottom: '14px',
                boxSizing: 'border-box',
              }}
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button
                onClick={() => textValue.trim() && handleSubmit(textValue.trim())}
                disabled={!textValue.trim()}
                style={{
                  padding: '8px 20px',
                  borderRadius: '8px',
                  border: 'none',
                  background: textValue.trim() ? 'var(--accent)' : 'var(--text-muted)',
                  color: 'white',
                  cursor: textValue.trim() ? 'pointer' : 'default',
                  fontSize: '0.85rem',
                  fontWeight: 600,
                  opacity: textValue.trim() ? 1 : 0.5,
                }}
              >
                发送回复
              </button>
            </div>
          </div>
        )}
      </div>

      {/* 动画 keyframes 注入 */}
      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        @keyframes slideUp {
          from { opacity: 0; transform: translate(-50%, -45%); }
          to { opacity: 1; transform: translate(-50%, -50%); }
        }
      `}</style>
    </>
  );
};

export default AskUserModal;
