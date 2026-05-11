import React, { useRef, useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface Props {
  content: string;
  thinkingContent?: string;  // SSE 推送的思维链内容
  onChatSubmit: (message: string) => void;
}

/**
 * 将 notebook 的 Markdown 内容解析为消息气泡数组。
 * 约定分隔符：\n---\n
 * 用户消息以 **👤 您:** 开头
 */
interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

function parseMessages(raw: string): ChatMessage[] {
  // 用 --- 分割消息段
  const segments = raw.split(/\n---\n/).filter(s => s.trim());
  return segments.map(seg => {
    const trimmed = seg.trim();
    if (trimmed.startsWith('**👤')) {
      // 提取用户消息（移除 **👤 您:** 前缀 + 占位文字）
      let userText = trimmed.replace(/^\*\*👤\s*您:\*\*\s*/, '');
      // 清理尾部的占位符（思考中...）
      userText = userText.replace(/\n*\*…小冶思考中\.\.\.\*\s*$/, '').trim();
      return { role: 'user' as const, content: userText };
    }
    return { role: 'assistant' as const, content: trimmed };
  });
}

const Notebook: React.FC<Props> = ({ content, thinkingContent, onChatSubmit }) => {
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [showThinking, setShowThinking] = useState(false);

  // AI 新内容来时自动滚动到底部
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [content]);

  // 有新思维链内容时自动展开
  useEffect(() => {
    if (thinkingContent && thinkingContent.length > 0) {
      setShowThinking(true);
    }
  }, [thinkingContent]);

  const handleSend = () => {
    const el = textareaRef.current;
    if (el && el.value.trim()) {
      onChatSubmit(el.value.trim());
      el.value = '';
    }
  };

  const hasThinking = thinkingContent && thinkingContent.trim().length > 0;
  const messages = parseMessages(content);
  // 检测是否正在流式输出（最后一段不以分隔符结尾）
  const isStreaming = content.length > 0 && !content.trimEnd().endsWith('---');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: '12px' }}>

      {/* 思维链折叠面板 */}
      <div>
        <button
          onClick={() => setShowThinking(!showThinking)}
          style={{
            background: hasThinking ? 'var(--accent-light)' : 'rgba(0,0,0,0.2)',
            border: `1px solid ${hasThinking ? 'var(--accent)' : 'var(--glass-border)'}`,
            borderRadius: '4px',
            padding: '5px 12px',
            color: hasThinking ? 'var(--accent)' : 'var(--text-muted)',
            cursor: 'pointer',
            fontSize: '0.8rem',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            transition: 'all 0.2s',
          }}
        >
          {/* 有内容时显示脉冲指示点 */}
          {hasThinking && (
            <span style={{
              display: 'inline-block',
              width: '6px',
              height: '6px',
              borderRadius: '50%',
              background: 'var(--accent)',
              animation: 'pulse 1.5s ease-in-out infinite',
              flexShrink: 0,
            }} />
          )}
          {showThinking ? '🧠 收起推理过程' : `💭 ${hasThinking ? '查看推理过程' : '推理过程（空）'}`}
        </button>

        {showThinking && (
          <div style={{
            marginTop: '8px',
            padding: '12px',
            background: 'rgba(0, 0, 0, 0.35)',
            borderRadius: '6px',
            border: '1px solid var(--glass-border)',
            maxHeight: '180px',
            overflowY: 'auto',
            fontSize: '0.78rem',
            color: 'var(--text-muted)',
            fontFamily: 'monospace',
            lineHeight: 1.5,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}>
            <div style={{
              fontSize: '0.72rem',
              fontWeight: 700,
              marginBottom: '8px',
              color: 'var(--accent)',
              letterSpacing: '0.05em',
            }}>
              ── AI 推理链 (Thinking) ──
            </div>
            {hasThinking
              ? thinkingContent
              : <span style={{ opacity: 0.5 }}>暂无推理内容。触发 Fork Agent 后将在此显示思维链...</span>
            }
          </div>
        )}
      </div>

      {/* 消息气泡列表 */}
      <div
        ref={scrollRef}
        className="notebook-content"
        style={{
          flex: 1,
          overflowY: 'auto',
          backgroundColor: 'var(--panel-bg)',
          borderRadius: '8px',
          padding: '20px 16px',
          border: '1px solid var(--glass-border)',
          display: 'flex',
          flexDirection: 'column',
          gap: '18px',
        }}
      >
        {messages.map((msg, i) => (
          <div
            key={i}
            style={{
              display: 'flex',
              justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
              animation: 'fadeIn 0.25s ease',
            }}
          >
            <div style={{
              maxWidth: msg.role === 'user' ? '75%' : '82%',
              padding: msg.role === 'user' ? '10px 16px' : '16px 20px',
              borderRadius: msg.role === 'user'
                ? '16px 16px 4px 16px'
                : '16px 16px 16px 4px',
              background: msg.role === 'user'
                ? 'var(--accent)'
                : 'rgba(255, 255, 255, 0.04)',
              color: msg.role === 'user'
                ? 'white'
                : 'var(--text-primary)',
              border: msg.role === 'user'
                ? 'none'
                : '1px solid var(--glass-border)',
              fontSize: msg.role === 'user' ? '0.88rem' : '0.88rem',
              lineHeight: 1.7,
              boxShadow: msg.role === 'user'
                ? '0 2px 8px rgba(217, 119, 87, 0.25)'
                : '0 1px 3px rgba(0,0,0,0.1)',
            }}>
              {msg.role === 'user' ? (
                <span>{msg.content}</span>
              ) : (
                <div className="notebook-content">
                  {(() => {
                    // 分离工具状态日志与正文
                    const lines = msg.content.split('\n');
                    const statusLines: string[] = [];
                    const bodyLines: string[] = [];
                    let passedStatus = false;
                    for (const line of lines) {
                      const trimmed = line.trim();
                      if (!passedStatus && (
                        trimmed.startsWith('> 🔍') ||
                        trimmed.startsWith('> ⚙️') ||
                        trimmed.startsWith('> 🧪') ||
                        trimmed.startsWith('> 📊') ||
                        trimmed.startsWith('> 🔄') ||
                        trimmed.match(/^>\s*\*.*\*\s*$/) ||
                        trimmed.match(/^\*.*正在.*\*$/) ||
                        trimmed.match(/^test\s*>/) ||
                        trimmed.match(/^>\s*[a-z_]+\s*>/) ||
                        trimmed === ''
                      )) {
                        statusLines.push(line);
                      } else {
                        passedStatus = true;
                        bodyLines.push(line);
                      }
                    }
                    const statusText = statusLines.filter(l => l.trim()).join('\n');
                    const bodyText = bodyLines.join('\n').trim();

                    return (
                      <>
                        {statusText && (
                          <div style={{
                            fontSize: '0.76rem',
                            color: 'var(--text-muted)',
                            opacity: 0.7,
                            lineHeight: 1.5,
                            paddingBottom: '10px',
                            marginBottom: '10px',
                            borderBottom: '1px solid rgba(255,255,255,0.06)',
                            fontFamily: 'monospace',
                          }}>
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>
                              {statusText}
                            </ReactMarkdown>
                          </div>
                        )}
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {bodyText || msg.content}
                        </ReactMarkdown>
                      </>
                    );
                  })()}
                  {/* 流式打字光标：最后一条 AI 消息且正在流式输出 */}
                  {i === messages.length - 1 && msg.role === 'assistant' && isStreaming && (
                    <span className="typing-cursor" />
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* 输入区 */}
      <div style={{ position: 'relative' }}>
        <textarea
          ref={textareaRef}
          placeholder="✍️ 在此输入问题，与小冶助手对话...（Ctrl+Enter 发送）"
          id="chat-input"
          style={{
            width: '100%',
            height: '96px',
            backgroundColor: 'rgba(0,0,0,0.3)',
            border: '1px solid rgba(255,255,255,0.12)',
            borderRadius: '8px',
            color: 'var(--text-primary)',
            paddingTop: '12px',
            paddingBottom: '12px',
            paddingLeft: '14px',
            paddingRight: '90px',
            fontSize: '0.88rem',
            resize: 'vertical',
            minHeight: '72px',
            maxHeight: '200px',
            outline: 'none',
            boxShadow: 'inset 0 1px 3px rgba(0,0,0,0.3)',
            fontFamily: 'inherit',
            lineHeight: 1.5,
            transition: 'border-color 0.2s',
          }}
          onFocus={(e) => e.currentTarget.style.borderColor = 'var(--accent)'}
          onBlur={(e) => e.currentTarget.style.borderColor = 'rgba(255,255,255,0.12)'}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              handleSend();
            }
          }}
        />
        {/* 发送按钮 */}
        <button
          style={{
            position: 'absolute',
            bottom: '10px',
            right: '10px',
            background: 'var(--accent)',
            border: 'none',
            borderRadius: '6px',
            padding: '6px 14px',
            color: 'white',
            fontSize: '0.82rem',
            cursor: 'pointer',
            fontWeight: 600,
            transition: 'opacity 0.15s',
          }}
          onMouseEnter={e => (e.currentTarget.style.opacity = '0.8')}
          onMouseLeave={e => (e.currentTarget.style.opacity = '1')}
          onClick={handleSend}
        >
          发送 ↵
        </button>
      </div>

      {/* 打字光标动画 */}
      <style>{`
        .typing-cursor {
          display: inline-block;
          width: 2px;
          height: 1em;
          background: var(--accent);
          margin-left: 2px;
          vertical-align: text-bottom;
          animation: blink 1s step-end infinite;
        }
        @keyframes blink {
          0%, 50% { opacity: 1; }
          51%, 100% { opacity: 0; }
        }
      `}</style>

    </div>
  );
};

export default Notebook;
