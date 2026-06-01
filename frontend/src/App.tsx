import { useState, useEffect, useCallback, useRef } from 'react';
import ForkManager from './components/ForkManager';
import PdfViewer from './components/PdfViewer';
import Notebook from './components/Notebook';
import Sidebar from './components/Sidebar';
import Resizer from './components/Resizer';
import AskUserModal, { type AskUserEventData } from './components/AskUserModal';
import { useToast } from './components/Toast';
import { KnowledgeGraphViewer } from './components/KnowledgeGraphViewer';
import { TitleBar } from './components/TitleBar';
import { Network } from 'lucide-react';

// localStorage 持久化键
const LAYOUT_KEY = 'xiaoye_layout_v2';  // v2: 调整右栏默认宽度
const NOTEBOOK_KEY = 'xiaoye_notebook_v1';
const THINKING_KEY = 'xiaoye_thinking_v1';
const SESSION_ID_KEY = 'xiaoye_session_id_v1';
const DEFAULT_LAYOUT = { leftWidth: 33, rightWidth: 24 };
const DEFAULT_NOTEBOOK = '# 工作台\n\n欢迎使用小冶冶金智慧文献服务平台。在左侧载入 PDF 文献，圈选区域并右键触发深入分析...';

// Electron 环境下直接请求后端，跳过 Vite 代理
const BASE_URL = typeof navigator !== 'undefined' && navigator.userAgent.toLowerCase().includes('electron') 
  ? 'http://localhost:8000' 
  : '';

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
  const [currentSessionId, setCurrentSessionId] = useState<string>(
    () => localStorage.getItem('xiaoye_last_session') || `session_${Date.now()}`
  );
  
  // Initialize from last session on mount
  useEffect(() => {
    localStorage.setItem('xiaoye_last_session', currentSessionId);
    // Fetch history from backend
    fetch(`${BASE_URL}/api/v1/chat/sessions/${currentSessionId}`)
      .then(res => res.json())
      .then(data => {
        if (data.history && data.history.length > 0) {
          let md = '';
          data.history.forEach((h: any) => {
             md += `\n\n---\n**👤 您:** ${h.user}\n\n---\n${h.assistant}`;
          });
          setNotebookContent(md);
        }
      })
      .catch(e => console.error("Failed to load session history", e));
  }, [currentSessionId]);

  const [currentDocumentId, setCurrentDocumentId] = useState<string | null>(null);
  const [notebookContent, setNotebookContent] = useState<string>(
    localStorage.getItem(`xiaoye_nb_${currentSessionId}`) || DEFAULT_NOTEBOOK
  );
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
  // 引用跳转状态：{page, key, highlightText} — key 用于重复点击同一页时也能重新触发
  const [citationTarget, setCitationTarget] = useState<{page: number, key: number, highlightText?: string} | null>(null);

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
    const eventSource = new EventSource(`${BASE_URL}/api/v1/notebook/stream`);

    eventSource.onopen = () => {
      console.log("[SSE] Connected to backend stream");
    };

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
            ? `${BASE_URL}${data.image_url}`
            : data.image_url;
          setNotebookContent(prev => prev + `\n\n---\n![📷 选区截图](${imgUrl})\n`);
          return;
        }

        // 入库进度推送 — 实时刷新文档列表以显示细粒度状态
        if (data.type === 'ingestion_progress') {
          fetchDocuments();
          return;
        }

        if (data.type === 'reasoning' && data.thinking) {
          setThinkingContent(prev => prev + data.thinking);
        } else if (data.patch) {
          // 第一个 patch 到来时：清除占位文字，不需要再插入分隔符，因为 handleUserChat 已经插入过了
          if (pendingReplace.current) {
            pendingReplace.current = false;
            setNotebookContent(prev =>
              prev.replace(/\n*\*…小冶思考中\.\.\.\*\n*/g, '\n\n')
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

  // 僵尸任务自动清理：超过 90 秒未完成的 activeTasks 自动移除
  useEffect(() => {
    const interval = setInterval(() => {
      const now = Date.now();
      setActiveTasks(prev => {
        const cleaned = prev.filter(t => now - (t.timestamp ?? now) < 90_000);
        if (cleaned.length < prev.length) {
          console.warn(`[ActiveTasks] Auto-cleaned ${prev.length - cleaned.length} zombie task(s)`);
        }
        return cleaned.length < prev.length ? cleaned : prev;
      });
    }, 10_000); // 每 10 秒检查一次
    return () => clearInterval(interval);
  }, []);

  // 加载已上传的PDF列表（可被主动调用刷新）
  const fetchDocuments = async () => {
    try {
      const res = await fetch(`${BASE_URL}/api/v1/documents`);
      const data = await res.json();
      if (data.documents) setDocuments(data.documents);
    } catch {
      // 后端未启动时静默失败
    }
  };

  // 加载对话会话列表
  const fetchChatSessions = async () => {
    try {
      const res = await fetch(`${BASE_URL}/api/v1/chat/sessions`);
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

  // 恢复会话上下文
  const handleSwitchSession = async (taskId: string) => {
    // 保存当前内容到 localStorage 避免丢失
    localStorage.setItem(`xiaoye_nb_${currentSessionId}`, notebookContent);
    localStorage.setItem(`xiaoye_tk_${currentSessionId}`, thinkingContent);

    setCurrentSessionId(taskId);
    setThinkingContent(localStorage.getItem(`xiaoye_tk_${taskId}`) || '');
    
    try {
      const res = await fetch(`${BASE_URL}/api/v1/chat/sessions/${taskId}`);
      if (res.ok) {
        const data = await res.json();
        if (data.history && data.history.length > 0) {
          let md = '';
          data.history.forEach((h: any) => {
             md += `\n\n---\n**👤 您:** ${h.user}\n\n---\n${h.assistant}`;
          });
          setNotebookContent(md);
          return;
        }
      }
    } catch (e) {
      console.error(e);
    }
    setNotebookContent(localStorage.getItem(`xiaoye_nb_${taskId}`) || DEFAULT_NOTEBOOK);
  };

  // 删除对话
  const handleDeleteSession = async (taskId: string) => {
    try {
      await fetch(`${BASE_URL}/api/v1/chat/sessions/${taskId}`, { method: 'DELETE' });
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
      await fetch(`${BASE_URL}/api/v1/fork_agent`, {
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

    // 立即显示用户消息，并在后方加上分隔符，确保 AI 的回复一定在一个新的 segment 里！
    setNotebookContent(prev => prev + `\n\n---\n**👤 您:** ${message}\n\n---\n*…小冶思考中...*\n`);
    // 标记等待第一个 patch 替换占位文字
    pendingReplace.current = true;
    setThinkingContent('');

    try {
      const res = await fetch(`${BASE_URL}/api/v1/chat`, {
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
      await fetch(`${BASE_URL}/api/v1/ask_user/reply`, {
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

  // 引用角标点击回调：Notebook → PdfViewer 页码跳转 + 段落高亮
  const handleCitationClick = useCallback((pageNumber: number, docIdOrFilename?: string, highlightText?: string) => {
    let targetDocId = docIdOrFilename;

    // 如果传入的不是 UUID 格式，尝试通过 filename 查找文档
    if (docIdOrFilename && !docIdOrFilename.match(/^[0-9a-f]{8}-/)) {
      const matchedDoc = documents.find(d =>
        d.filename === docIdOrFilename ||
        d.filename.includes(docIdOrFilename.replace('.pdf', '')) ||
        docIdOrFilename.includes(d.filename.replace('.pdf', ''))
      );
      if (matchedDoc) {
        targetDocId = matchedDoc.id;
      }
    }

    // 加载对应文档的 PDF（如果尚未加载或需要切换）
    if (targetDocId && targetDocId !== currentDocumentId) {
      setPdfUrl(`${BASE_URL}/api/v1/documents/${targetDocId}/pdf`);
      setPdfSourceType('retrieved');
      setCurrentDocumentId(targetDocId);
    }

    // 设置跳转目标（用 Date.now() 作 key，确保重复点击同一页也会触发）
    setCitationTarget({ page: pageNumber, key: Date.now(), highlightText });
  }, [currentDocumentId, documents]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden' }}>
      {/* 自定义窗口拖拽栏与控制按钮（仅在 Electron 环境渲染） */}
      <TitleBar />
      
      {/* 下方主要工作区 */}
      <div style={{ position: 'relative', flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* 主题切换按钮 */}
        <div style={{
          position: 'absolute',
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
          position: 'absolute',
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
        <div ref={containerRef} className="app-container" style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

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
              setPdfUrl(`${BASE_URL}/api/v1/documents/${id}/pdf`);
              setPdfSourceType('uploaded');
            }}
            onRefresh={fetchDocuments}
            onDocumentUploaded={(docId) => {
              setKnowledgeDocId(docId);
              setCurrentDocumentId(docId);
            }}
            onDeleteDocument={(docId) => {
              // 删除后清理选中状态
              if (knowledgeDocId === docId) setKnowledgeDocId(null);
              if (currentDocumentId === docId) {
                setCurrentDocumentId(null);
                setPdfUrl(null);
              }
            }}
            retrievalSources={retrievalSources}
            onRetrievedSelect={(docId) => {
              // 用户点击检索到的文献 → 从服务端加载 + 无底纹
              setPdfUrl(`${BASE_URL}/api/v1/documents/${docId}/pdf`);
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
      </div>
    </div>
  );
}

export default App;
