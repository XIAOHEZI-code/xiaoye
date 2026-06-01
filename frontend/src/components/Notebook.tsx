import React, { useRef, useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';

interface Props {
  content: string;
  thinkingContent?: string;  // SSE 推送的思维链内容
  onChatSubmit: (message: string, deepMode: boolean) => void;
  deepMode: boolean;
  onDeepModeToggle: (deepMode: boolean) => void;
  onCitationClick?: (pageNumber: number, docId?: string, highlightText?: string) => void;  // 引用角标点击回调
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

/**
 * 预处理 LaTeX 文本：将常见的非标准 LaTeX 分隔符转换为标准格式
 * - \[...\] → $$...$$  (块级公式)
 * - \(...\) → $...$    (行内公式)
 * - [ ... ] 独立行的也尝试转换（常见于 AI 输出）
 */
function preprocessLatex(text: string): string {
  // \[...\] → $$...$$ (块级)
  let result = text.replace(/\\\[([\s\S]*?)\\\]/g, (_match, p1) => `$$${p1}$$`);
  // \(...\) → $...$ (行内)
  result = result.replace(/\\\(([\s\S]*?)\\\)/g, (_match, p1) => `$${p1}$`);
  return result;
}

/**
 * 分离 AI 回复中的工具调用状态日志与正文
 */
function separateStatusAndBody(content: string): { statusText: string; bodyText: string } {
  const lines = content.split('\n');
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
      trimmed.startsWith('> 🛠️') ||
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
  return {
    statusText: statusLines.filter(l => l.trim()).join('\n'),
    bodyText: bodyLines.join('\n').trim(),
  };
}

/**
 * 解析文本中的 [来源: xxx.pdf, p.N] 标注，渲染为可点击的蓝色角标按钮
 */
const CITATION_REGEX = /\[来源:\s*([^,\]]+?)(?:,\s*p\.?(\d+))?\]/g;

const CitationText: React.FC<{
  text: string;
  onCitationClick?: (pageNumber: number, docId?: string, highlightText?: string) => void;
}> = ({ text, onCitationClick }) => {
  if (!onCitationClick) return <>{text}</>;

  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  const regex = new RegExp(CITATION_REGEX.source, 'g');

  while ((match = regex.exec(text)) !== null) {
    // 前缀纯文本
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    const filename = match[1].trim();
    const page = match[2] ? parseInt(match[2], 10) : null;
    const label = page ? `📎 ${filename} p.${page}` : `📎 ${filename}`;

    // 提取引用标注前方 30~60 个字符作为高亮匹配关键词
    const contextStart = Math.max(0, match.index - 60);
    const rawContext = text.slice(contextStart, match.index).trim();
    // 取最后一个完整句子片段（从最近的句号/逗号/换行处截断）
    const sentenceBreak = rawContext.search(/[。，,.\n]/);
    const highlightText = sentenceBreak >= 0 ? rawContext.slice(sentenceBreak + 1).trim() : rawContext;

    parts.push(
      <button
        key={`cite-${match.index}`}
        onClick={(e) => {
          e.stopPropagation();
          if (page) onCitationClick(page, filename, highlightText || undefined);
        }}
        title={page ? `点击跳转到 ${filename} 第 ${page} 页` : filename}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '3px',
          padding: '1px 8px',
          margin: '0 2px',
          background: 'rgba(59, 130, 246, 0.12)',
          border: '1px solid rgba(59, 130, 246, 0.3)',
          borderRadius: '4px',
          color: '#60a5fa',
          fontSize: '0.75rem',
          fontWeight: 500,
          cursor: page ? 'pointer' : 'default',
          verticalAlign: 'middle',
          lineHeight: 1.4,
          transition: 'all 0.15s ease',
          textDecoration: 'none',
        }}
        onMouseEnter={e => {
          e.currentTarget.style.background = 'rgba(59, 130, 246, 0.25)';
          e.currentTarget.style.borderColor = 'rgba(59, 130, 246, 0.6)';
        }}
        onMouseLeave={e => {
          e.currentTarget.style.background = 'rgba(59, 130, 246, 0.12)';
          e.currentTarget.style.borderColor = 'rgba(59, 130, 246, 0.3)';
        }}
      >
        {label}
      </button>
    );
    lastIndex = regex.lastIndex;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts.length > 0 ? <>{parts}</> : <>{text}</>;
};

/**
 * 可复用的 Markdown 渲染组件（含 LaTeX 支持 + 引用角标点击跳转）
 */
const MarkdownRenderer: React.FC<{
  content: string;
  className?: string;
  onCitationClick?: (pageNumber: number, docId?: string, highlightText?: string) => void;
}> = ({ content, className, onCitationClick }) => {
  const processed = preprocessLatex(content);
  return (
    <div className={className}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          // 拦截所有文本节点，将其中的 [来源: ...] 标注替换为可点击组件
          p: ({ children, ...props }) => (
            <p {...props}>
              {React.Children.map(children, child =>
                typeof child === 'string'
                  ? <CitationText text={child} onCitationClick={onCitationClick} />
                  : child
              )}
            </p>
          ),
          li: ({ children, ...props }) => (
            <li {...props}>
              {React.Children.map(children, child =>
                typeof child === 'string'
                  ? <CitationText text={child} onCitationClick={onCitationClick} />
                  : child
              )}
            </li>
          ),
        }}
      >
        {processed}
      </ReactMarkdown>
    </div>
  );
};

const Notebook: React.FC<Props> = ({ content, thinkingContent, onChatSubmit, deepMode, onDeepModeToggle, onCitationClick }) => {
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
    if (!el || !el.value.trim()) return;
    onChatSubmit(el.value.trim(), deepMode);
    el.value = '';
  };

  const hasThinking = thinkingContent && thinkingContent.trim().length > 0;
  const messages = parseMessages(content);
  // 检测是否正在流式输出（最后一段不以分隔符结尾）
  const isStreaming = content.length > 0 && !content.trimEnd().endsWith('---');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: '12px' }}>

      {/* 思维链折叠面板 */}
      <div className="thinking-panel-wrapper">
        <button
          onClick={() => setShowThinking(!showThinking)}
          className={`thinking-toggle-btn ${hasThinking ? 'has-content' : ''} ${showThinking ? 'expanded' : ''}`}
        >
          {/* 有内容时显示脉冲指示点 */}
          {hasThinking && (
            <span className="thinking-pulse-dot" />
          )}
          <span className="thinking-toggle-icon">
            {showThinking ? '▾' : '▸'}
          </span>
          {showThinking ? '🧠 收起推理过程' : `💭 ${hasThinking ? '查看推理过程' : '推理过程（空）'}`}
        </button>

        <div className={`thinking-content-panel ${showThinking ? 'open' : ''}`}>
          <div className="thinking-content-inner">
            <div className="thinking-header-label">
              ── AI 推理链 (Thinking) ──
            </div>
            {hasThinking ? (
              <div className="thinking-text">
                <MarkdownRenderer content={thinkingContent!} />
              </div>
            ) : (
              <span style={{ opacity: 0.5 }}>暂无推理内容。触发深度模式或 Fork Agent 后将在此显示思维链...</span>
            )}
          </div>
        </div>
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
            <div className={msg.role === 'user' ? 'chat-bubble-user' : 'chat-bubble-assistant'}>
              {msg.role === 'user' ? (
                <span>{msg.content}</span>
              ) : (
                <div className="notebook-content assistant-reply">
                  {(() => {
                    const { statusText, bodyText } = separateStatusAndBody(msg.content);
                    return (
                      <>
                        {statusText && (
                          <div className="tool-status-log">
                            <MarkdownRenderer content={statusText} />
                          </div>
                        )}
                        <MarkdownRenderer content={bodyText || msg.content} onCitationClick={onCitationClick} />
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
        {/* 深度模式切换 */}
        <button
          onClick={() => onDeepModeToggle(!deepMode)}
          title={deepMode ? "深度模式已启用：知识图谱增强检索 + 详尽分析" : "点击启用深度模式：启用知识图谱增强检索(HyDE)"}
          style={{
            position: 'absolute',
            bottom: '10px',
            right: '90px',
            background: deepMode ? 'rgba(59, 130, 246, 0.15)' : 'rgba(255,255,255,0.05)',
            border: deepMode ? '1px solid rgba(59, 130, 246, 0.4)' : '1px solid var(--glass-border)',
            borderRadius: '6px',
            padding: '6px 10px',
            color: deepMode ? 'rgba(59, 130, 246, 0.9)' : 'var(--text-muted)',
            fontSize: '0.75rem',
            cursor: 'pointer',
            fontWeight: deepMode ? 600 : 400,
            transition: 'all 0.2s',
            display: 'flex',
            alignItems: 'center',
            gap: '4px',
            boxShadow: deepMode ? '0 0 8px rgba(59, 130, 246, 0.15)' : 'none',
          }}
        >
          {deepMode ? (
            <>
              <span style={{
                display: 'inline-block', width: '5px', height: '5px',
                borderRadius: '50%', background: '#3b82f6',
                animation: 'pulse 1.5s ease-in-out infinite'
              }} />
              🧠 深度
            </>
          ) : (
            <>🧠 深度</>
          )}
        </button>
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
      `}
      </style>

    </div>
  );
};

export default Notebook;
