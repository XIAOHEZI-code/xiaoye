import { useState, useEffect, useCallback, useRef } from 'react';
import ForkManager from './components/ForkManager';
import PdfViewer from './components/PdfViewer';
import Notebook from './components/Notebook';
import Sidebar from './components/Sidebar';
import Resizer from './components/Resizer';
import AskUserModal, { type AskUserEventData } from './components/AskUserModal';
import { useToast } from './components/Toast';
import { KnowledgeGraphViewer } from './components/KnowledgeGraphViewer';
import { Network } from 'lucide-react';

// localStorage 持久化键
const LAYOUT_KEY = 'xiaoye_layout_v2';  // v2: 调整右栏默认宽度
const NOTEBOOK_KEY = 'xiaoye_notebook_v1';
const THINKING_KEY = 'xiaoye_thinking_v1';
const SESSION_ID_KEY = 'xiaoye_session_id_v1';
const DEFAULT_LAYOUT = { leftWidth: 33, rightWidth: 24 };
const DEFAULT_NOTEBOOK = '# 工作台\n\n欢迎使用小冶冶金智慧文献服务平台。在左侧载入 PDF 文献，圈选区域并右键触发深入分析...';

function loadLayout() {
  try {
    const saved = localStorage.getItem(LAYOUT_KEY);
    if (saved) return JSON.parse(saved) as typeof DEFAULT_LAYOUT;
  } catch { }
  return DEFAULT_LAYOUT;
}

function loadNotebook(): string {
  try {
    const saved = localStorage.getItem(NOTEBOOK_KEY);
    if (saved) return saved;
  } catch { }
  return DEFAULT_NOTEBOOK;
}

function loadThinking(): string {
  try {
    return localStorage.getItem(THINKING_KEY) || '';
  } catch { }
  return '';
}

function loadSessionId(): string {
  try {
    return localStorage.getItem(SESSION_ID_KEY) || 'default_session';
  } catch { }
  return 'default_session';
}

export type ChatSession = {
  task_id: string;
  message_count: number;
  preview: string;
  last_user_msg: string;
};


export type BoundingBox = {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  pageNumber: number;
};

export type TaskEvent = {
  task_id: string;
  id?: string;        // 别名兼容旧代码
  patch?: string;
  thinking?: string;
  type?: "content" | "reasoning";
  bbox?: BoundingBox;
  timestamp?: number;
};

// 检索到的文献源信息（由 search_metallurgy_text tool 推送）
export type RetrievalSource = {
  doc_id: string;
  filename: string;
  pages: number[];
  score: number;
  chunk_type: string;
};

function App() {
  const { showToast } = useToast();
  const [activeTasks, setActiveTasks] = useState<TaskEvent[]>([]);
  const [currentDocumentId, setCurrentDocumentId] = useState<string | null>(null);
  const [notebookContent, setNotebookContent] = useState<string>(loadNotebook);
  const [thinkingContent, setThinkingContent] = useState<string>(loadThinking);
  const [documents, setDocuments] = useState<{ id: string, filename: string, status: string, created_at: string | null }[]>([]);
  const [knowledgeDocId, setKnowledgeDocId] = useState<string | null>(null);
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const [askUserEvent, setAskUserEvent] = useState<AskUserEventData | null>(null);
  const [retrievalSources, setRetrievalSources] = useState<RetrievalSource[]>([]);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);       // 从服务端加载的 PDF URL
  const [pdfSourceType, setPdfSourceType] = useState<'uploaded' | 'retrieved'>('uploaded');
  const [showGraph, setShowGraph] = useState(false);
  const [deepMode, setDeepMode] = useState(false);
  const [chatSessions, setChatSessions] = useState<ChatSession[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string>(loadSessionId);
  // 引用跳转状态：{page, key} — key 用于重复点击同一页时也能重新触发
  const [citationTarget, setCitationTarget] = useState<{page: number, key: number} | null>(null);

  const toggleTheme = () => {
    const newTheme = theme === 'dark' ? 'light' : 'dark';
    setTheme(newTheme);
    document.documentElement.setAttribute('data-theme', newTheme);
  };

  // 布局状态（从 localStorage 恢复）
  const containerRef = useRef<HTMLDivElement>(null);
  const savedLayout = loadLayout();
  const [leftWidth, setLeftWidth] = useState(savedLayout.leftWidth);
  const [rightWidth, setRightWidth] = useState(savedLayout.rightWidth);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const prevLeftWidth = useRef(savedLayout.leftWidth);
  const prevRightWidth = useRef(savedLayout.rightWidth);
  // SSE 第一个 patch 到来时是否需要清除占位文字
  const pendingReplace = useRef(false);

  // 持久化布局到 localStorage
  useEffect(() => {
    if (!leftCollapsed && !rightCollapsed) {
      localStorage.setItem(LAYOUT_KEY, JSON.stringify({ leftWidth, rightWidth }));
    }
  }, [leftWidth, rightWidth, leftCollapsed, rightCollapsed]);

  // 持久化 notebook 内容到 localStorage
  useEffect(() => {
    localStorage.setItem(NOTEBOOK_KEY, notebookContent);
  }, [notebookContent]);

  useEffect(() => {
    localStorage.setItem(THINKING_KEY, thinkingContent);
  }, [thinkingContent]);

  useEffect(() => {
    localStorage.setItem(SESSION_ID_KEY, currentSessionId);
  }, [currentSessionId]);

  const handleLeftDrag = useCallback((dx: number) => {
    if (!containerRef.current) return;
    const deltaPerc = (dx / containerRef.current.clientWidth) * 100;
    setLeftWidth(prev => {
      const newLeft = Math.min(Math.max(prev + deltaPerc, 10), 75);
      const middle = 100 - newLeft - rightWidth;
      if (middle < 15) return prev;
      return newLeft;
    });
  }, [rightWidth]);

  const handleRightDrag = useCallback((dx: number) => {
    if (!containerRef.current) return;
    const deltaPerc = (dx / containerRef.current.clientWidth) * 100;
    setRightWidth(prev => {
      const newRight = Math.min(Math.max(prev - deltaPerc, 10), 75);
      const middle = 100 - leftWidth - newRight;
      if (middle < 15) return prev;
      return newRight;
    });
  }, [leftWidth]);

  // 左侧面板折叠/展开
  const handleCollapseLeft = useCallback(() => {
    if (leftCollapsed) {
      setLeftWidth(prevLeftWidth.current);
      setLeftCollapsed(false);
    } else {
      prevLeftWidth.current = leftWidth;
      setLeftWidth(0);
      setLeftCollapsed(true);
    }
  }, [leftCollapsed, leftWidth]);

  // 右侧面板折叠/展开
  const handleCollapseRight = useCallback(() => {
    if (rightCollapsed) {
      setRightWidth(prevRightWidth.current);
      setRightCollapsed(false);
    } else {
      prevRightWidth.current = rightWidth;
      setRightWidth(0);
      setRightCollapsed(true);
    }
  }, [rightCollapsed, rightWidth]);

  // 计算实际宽度（折叠时为 0）
  const effectiveLeft = leftCollapsed ? 0 : leftWidth;
  const effectiveRight = rightCollapsed ? 0 : rightWidth;
  // effectiveMiddle 不再需要 — 中栏使用 flex:1 自动填充

  // Setup Server-Sent Events (SSE) Listener
  useEffect(() => {
    const eventSource = new EventSource("/api/v1/notebook/stream");

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        // AskUser 事件处理
        if (data.type === 'ask_user' && data.ask_id) {
          setAskUserEvent(data as AskUserEventData);
          return;
        }

        // 检索源推送 — Tool 调用后自动推送命中的文献列表
        if (data.type === 'retrieval_sources' && data.sources) {
          setRetrievalSources(data.sources as RetrievalSource[]);
          return;
        }

        // Fork VLM: 选区截图推送
        if (data.type === 'fork_start' && data.image_url) {
          const imgUrl = data.image_url.startsWith('/')
            ? `http://localhost:8000${data.image_url}`
            : data.image_url;
          setNotebookContent(prev => prev + `\n\n![📷 选区截图](${imgUrl})\n`);
          return;
        }

        if (data.type === 'reasoning' && data.thinking) {
          setThinkingContent(prev => prev + data.thinking);
        } else if (data.patch) {
          // 第一个 patch 到来时：清除占位文字 + 插入分隔符，让 AI 回复独立成段
          if (pendingReplace.current) {
            pendingReplace.current = false;
            setNotebookContent(prev =>
              prev.replace('\n*\u2026小冶思考中...*\n', '\n\n---\n')
            );
          }
          setNotebookContent(prev => prev + data.patch);
          if (data.patch.includes('\n---\n') || data.patch.endsWith('```\n')) {
            setActiveTasks(prev => prev.filter(t => t.task_id !== data.task_id));
          }
        }
      } catch (err) {
        console.error("Failed to parse SSE event", err);
      }
    };

    eventSource.onerror = () => {
      // SSE 断运时不弹窗，静默处理（后端未启动时是正常状态）
    };

    return () => {
      eventSource.close();
    };
  }, []);

  // 加载已上传的PDF列表（可被主动调用刷新）
  const fetchDocuments = async () => {
    try {
      const res = await fetch("/api/v1/documents");
      const data = await res.json();
      if (data.documents) setDocuments(data.documents);
    } catch {
      // 后端未启动时静默失败
    }
  };

  // 加载对话会话列表
  const fetchChatSessions = async () => {
    try {
      const res = await fetch('/api/v1/chat/sessions');
      const data = await res.json();
      if (data.sessions) setChatSessions(data.sessions);
    } catch {
      // 静默失败
    }
  };

  useEffect(() => {
    fetchDocuments();
    fetchChatSessions();
  }, []);

  // 新建对话
  const handleNewSession = () => {
    const newId = `session_${Date.now()}`;
    // 保存当前对话到 localStorage（按 session_id 隔离）
    localStorage.setItem(`xiaoye_nb_${currentSessionId}`, notebookContent);
    localStorage.setItem(`xiaoye_tk_${currentSessionId}`, thinkingContent);
    // 切换到新会话
    setCurrentSessionId(newId);
    setNotebookContent(DEFAULT_NOTEBOOK);
    setThinkingContent('');
    showToast('已创建新对话', 'success', 2000);
  };

  // 切换对话
  const handleSwitchSession = (taskId: string) => {
    if (taskId === currentSessionId) return;
    // 保存当前对话
    localStorage.setItem(`xiaoye_nb_${currentSessionId}`, notebookContent);
    localStorage.setItem(`xiaoye_tk_${currentSessionId}`, thinkingContent);
    // 加载目标对话
    const savedNb = localStorage.getItem(`xiaoye_nb_${taskId}`);
    const savedTk = localStorage.getItem(`xiaoye_tk_${taskId}`);
    setCurrentSessionId(taskId);
    setNotebookContent(savedNb || DEFAULT_NOTEBOOK);
    setThinkingContent(savedTk || '');
  };

  // 删除对话
  const handleDeleteSession = async (taskId: string) => {
    try {
      await fetch(`/api/v1/chat/sessions/${taskId}`, { method: 'DELETE' });
      // 清理 localStorage
      localStorage.removeItem(`xiaoye_nb_${taskId}`);
      localStorage.removeItem(`xiaoye_tk_${taskId}`);
      // 如果删的是当前对话，切换到新对话
      if (taskId === currentSessionId) {
        setCurrentSessionId('default_session');
        setNotebookContent(DEFAULT_NOTEBOOK);
        setThinkingContent('');
      }
      showToast('对话已删除', 'info', 2000);
      fetchChatSessions();
    } catch {
      showToast('删除失败', 'error');
    }
  };

  const handleForkTask = async (taskId: string, documentId: string, type: string, bbox: BoundingBox) => {
    const newTask: TaskEvent = {
      task_id: taskId,
      id: taskId,
      type: type as any,
      bbox,
      timestamp: Date.now()
    };

    setActiveTasks(prev => [...prev, newTask]);

    try {
      await fetch("/api/v1/fork_agent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ taskId, documentId, type, bbox })
      });
    } catch (err) {
      console.error("[M3 Network Error] Failed to fork task:", err);
      showToast('后端未启动，Fork 任务失败。请先启动 FastAPI 后端服务（localhost:8000）', 'error', 6000);
      setActiveTasks(prev => prev.filter(t => t.task_id !== taskId));
    }
  };

  const handleDocumentIdChange = (id: string | null) => {
    setCurrentDocumentId(id);
  };

  const handleUserChat = async (message: string, deepMode: boolean) => {
    const docId = currentDocumentId || null;
    const taskId = currentSessionId;

    // 立即显示用户消息，加占位符
    setNotebookContent(prev => prev + `\n\n---\n**\ud83d\udc64 \u60a8:** ${message}\n\n*\u2026小冶思考中...*\n`);
    // 标记等待第一个 patch 替换占位文字
    pendingReplace.current = true;
    setThinkingContent('');

    try {
      const res = await fetch("/api/v1/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task_id: taskId,
          message: message,
          deep_mode: deepMode,
          // document_id 为 null 时不传该字段，避免 Pydantic v2 422
          ...(docId ? { document_id: docId } : {}),
        })
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showToast(err.detail || '对话请求失败', 'error');
      }
      // 对话发送后刷新会话列表
      setTimeout(fetchChatSessions, 3000);
    } catch (err) {
      showToast('后端未启动，无法发送消息。请先启动 FastAPI 服务', 'error');
    }
  };

  // AskUser 回复处理
  const handleAskUserReply = async (askId: string, taskId: string, reply: string) => {
    setAskUserEvent(null);
    try {
      await fetch('/api/v1/ask_user/reply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ask_id: askId, task_id: taskId, reply }),
      });
      showToast(`已回复小冶的询问: ${reply}`, 'success', 3000);
    } catch {
      showToast('回复提交失败，请检查后端服务', 'error');
    }
  };

  // 获取当前文档名称
  const currentDocName = currentDocumentId
    ? documents.find(d => d.id === currentDocumentId)?.filename
    : null;
  const currentKbName = knowledgeDocId
    ? documents.find(d => d.id === knowledgeDocId)?.filename
    : null;

  // 引用角标点击回调：Notebook → PdfViewer 页码跳转
  const handleCitationClick = useCallback((pageNumber: number, docId?: string) => {
    // 如果指定了 docId，先加载对应文档的 PDF
    if (docId && docId !== currentDocumentId) {
      setPdfUrl(`/api/v1/documents/${docId}/pdf`);
      setPdfSourceType('retrieved');
      setCurrentDocumentId(docId);
    }
    // 设置跳转目标（用 Date.now() 作 key，确保重复点击同一页也会触发）
    setCitationTarget({ page: pageNumber, key: Date.now() });
  }, [currentDocumentId]);

  return (
    <>
      {/* 主题切换按钮 */}
      <div style={{
        position: 'fixed',
        top: '12px',
        right: '12px',
        zIndex: 1000,
        padding: '8px 12px',
        background: 'var(--panel-bg)',
        border: '1px solid var(--glass-border)',
        borderRadius: '8px',
        cursor: 'pointer',
        fontSize: '0.85rem',
        display: 'flex',
        alignItems: 'center',
        gap: '6px',
        color: 'var(--text-secondary)',
        transition: 'border-color 0.2s',
      }} onClick={toggleTheme}>
        {theme === 'dark' ? '🌙 暗色' : '☀️ 亮色'}
      </div>

      {/* 知识图谱视图按钮 */}
      <div style={{
        position: 'fixed',
        top: '12px',
        right: '100px',
        zIndex: 1000,
        padding: '8px 12px',
        background: 'var(--panel-bg)',
        border: '1px solid var(--glass-border)',
        borderRadius: '8px',
        cursor: 'pointer',
        fontSize: '0.85rem',
        display: 'flex',
        alignItems: 'center',
        gap: '6px',
        color: 'var(--text-secondary)',
        transition: 'all 0.2s',
      }} onClick={() => setShowGraph(true)}>
        <Network size={16} style={{ color: '#3b82f6' }} />
        <span style={{ fontWeight: 500, color: 'rgba(59, 130, 246, 0.9)' }}>图谱全景</span>
      </div>

      {/* 主布局 */}
      <div ref={containerRef} className="app-container" style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>

        {/* 左栏：PDF 文献阅读（用宽度过渡折叠，不用条件渲染） */}
        <div
          className="glass-panel"
          style={{
            flex: leftCollapsed ? '0 0 0px' : `0 0 ${effectiveLeft}%`,
            minWidth: leftCollapsed ? 0 : '150px',
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
            transition: 'flex-basis 0.25s cubic-bezier(0.4, 0, 0.2, 1), min-width 0.25s',
            marginRight: '8px',
          }}
        >
          <div className="panel-header">
            <span>📄 阅读器</span>
            <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '160px' }}>
              {currentDocName || '右键选区可触发 Agent'}
            </span>
          </div>
          <div className="panel-content" style={{ flex: 1, padding: 0, overflow: 'hidden' }}>
            <PdfViewer
              onForkTask={handleForkTask}
              onDocumentIdChange={handleDocumentIdChange}
              pdfUrl={pdfUrl}
              sourceType={pdfSourceType}
              targetPage={citationTarget?.page ?? null}
              key={citationTarget?.key}
            />
          </div>
        </div>

        <Resizer
          onDrag={handleLeftDrag}
          onCollapse={handleCollapseLeft}
        />

        {/* 中栏：AI 助手 — flex:1 自动填充剩余空间 */}
        <div
          className="glass-panel"
          style={{
            flex: 1,
            minWidth: '200px',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            margin: '0 8px',
          }}
        >
          <div className="panel-header">
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span> 小冶助手</span>
              {currentKbName && (
                <span style={{
                  fontSize: '0.72rem',
                  background: 'var(--accent-light)',
                  color: 'var(--accent)',
                  padding: '2px 8px',
                  borderRadius: '4px',
                  border: '1px solid var(--accent)',
                  opacity: 0.85,
                  maxWidth: '150px',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}>
                  📚 {currentKbName}
                </span>
              )}
            </div>
            {activeTasks.length > 0 ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{
                  display: 'inline-block',
                  width: '8px',
                  height: '8px',
                  borderRadius: '50%',
                  background: 'var(--accent)',
                  animation: 'pulse 1.5s ease-in-out infinite',
                }} />
                <span style={{ fontSize: '0.8rem', color: 'var(--accent)' }}>
                  {activeTasks.length} 个 Agent 工作中
                </span>
              </div>
            ) : (
              <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>就绪</span>
            )}
          </div>
          <div className="panel-content" style={{ flex: 1 }}>
            <Notebook
              content={notebookContent}
              thinkingContent={thinkingContent}
              onChatSubmit={handleUserChat}
              deepMode={deepMode}
              onDeepModeToggle={setDeepMode}
              onCitationClick={handleCitationClick}
            />
          </div>
        </div>

        <Resizer
          onDrag={handleRightDrag}
          onCollapse={handleCollapseRight}
        />

        {/* 右栏：知识库 & Fork 管理（宽度过渡折叠） */}
        <div
          className="glass-panel"
          style={{
            flex: rightCollapsed ? '0 0 0px' : `0 0 ${effectiveRight}%`,
            minWidth: rightCollapsed ? 0 : '220px',
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
            transition: 'flex-basis 0.25s cubic-bezier(0.4, 0, 0.2, 1), min-width 0.25s',
            marginLeft: '8px',
          }}
        >
          <Sidebar
            documents={documents}
            selectedId={knowledgeDocId}
            onSelect={(id) => {
              setKnowledgeDocId(id);
              setCurrentDocumentId(id);
              // 用户点击自己上传的文档 → 从服务端加载 + 蓝色底纹
              setPdfUrl(`/api/v1/documents/${id}/pdf`);
              setPdfSourceType('uploaded');
            }}
            onRefresh={fetchDocuments}
            onDocumentUploaded={(docId) => {
              setKnowledgeDocId(docId);
              setCurrentDocumentId(docId);
            }}
            retrievalSources={retrievalSources}
            onRetrievedSelect={(docId) => {
              // 用户点击检索到的文献 → 从服务端加载 + 无底纹
              setPdfUrl(`/api/v1/documents/${docId}/pdf`);
              setPdfSourceType('retrieved');
              setCurrentDocumentId(docId);
            }}
            chatSessions={chatSessions}
            currentSessionId={currentSessionId}
            onNewSession={handleNewSession}
            onSwitchSession={handleSwitchSession}
            onDeleteSession={handleDeleteSession}
          />
          <ForkManager tasks={activeTasks} style={{ marginTop: '12px' }} />
        </div>

      </div>

      {/* AskUser 弹窗 */}
      <AskUserModal
        event={askUserEvent}
        onReply={handleAskUserReply}
        onDismiss={() => setAskUserEvent(null)}
      />

      {/* 知识图谱查看器弹窗 */}
      {showGraph && <KnowledgeGraphViewer onClose={() => setShowGraph(false)} />}
    </>
  );
}

export default App;
