import React, { useState, useEffect } from 'react';
import { FileText, RefreshCw, Upload, Loader, MessageSquare, Plus, Trash2 } from 'lucide-react';
import { useToast } from './Toast';
import type { RetrievalSource, ChatSession } from '../App';

interface Document {
  id: string;
  filename: string;
  status: string;
  created_at: string | null;
}

interface Props {
  documents: Document[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onRefresh: () => void;
  onDocumentUploaded?: (docId: string) => void;
  onDeleteDocument?: (docId: string) => void;      // 删除文档回调
  retrievalSources?: RetrievalSource[];           // AI 检索命中的文献
  onRetrievedSelect?: (docId: string) => void;    // 点击检索文献的回调
  chatSessions?: ChatSession[];
  currentSessionId?: string;
  onNewSession?: () => void;
  onSwitchSession?: (taskId: string) => void;
  onDeleteSession?: (taskId: string) => void;
}

const STATUS_MAP: Record<string, { color: string; label: string; pulsing?: boolean }> = {
  ready:    { color: 'var(--success)',        label: '就绪' },
  pending:  { color: 'var(--status-pending)', label: '等待处理', pulsing: true },
  parsing:  { color: '#f59e0b',               label: '解析PDF中', pulsing: true },
  chunking: { color: '#f59e0b',               label: '文本分块中', pulsing: true },
  figures:  { color: '#f59e0b',               label: '图片处理中', pulsing: true },
  indexing: { color: '#8b5cf6',               label: '向量索引中', pulsing: true },
  graphing: { color: '#8b5cf6',               label: '图谱抽取中', pulsing: true },
  failed:   { color: 'var(--status-error)',   label: '失败' },
};

const Sidebar: React.FC<Props> = ({
  documents, selectedId, onSelect, onRefresh, onDocumentUploaded, onDeleteDocument,
  retrievalSources, onRetrievedSelect,
  chatSessions, currentSessionId, onNewSession, onSwitchSession, onDeleteSession,
}) => {
  const { showToast } = useToast();
  const [uploading, setUploading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // 删除文档（带确认弹窗）
  const handleDeleteDocument = async (docId: string, filename: string) => {
    if (!confirm(`确定删除「${filename}」？\n将同时清理 ES 索引、Neo4j 图谱和磁盘文件。`)) return;
    setDeletingId(docId);
    try {
      const res = await fetch(`/api/v1/documents/${docId}`, { method: 'DELETE' });
      const data = await res.json();
      if (res.ok) {
        showToast(`✅ 已删除：${filename}（${data.cleaned?.join(', ')}）`, 'success', 4000);
        onDeleteDocument?.(docId);
        await onRefresh();
      } else {
        showToast(`删除失败：${data.detail || '未知错误'}`, 'error');
      }
    } catch {
      showToast('删除失败，请检查后端服务', 'error');
    } finally {
      setDeletingId(null);
    }
  };

  // 自动轮询：当有处理中状态的文档时，每 8 秒刷新一次
  const TERMINAL_STATES = ['ready', 'failed'];
  const hasInProgress = documents.some(d => !TERMINAL_STATES.includes(d.status));
  useEffect(() => {
    if (!hasInProgress) return;
    const interval = setInterval(() => {
      onRefresh();
    }, 8000);
    return () => clearInterval(interval);
  }, [hasInProgress, onRefresh]);

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '';
    return new Date(dateStr).toLocaleDateString('zh-CN', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await onRefresh();
    } finally {
      setTimeout(() => setRefreshing(false), 400);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.endsWith('.pdf')) {
      showToast('仅支持 PDF 文件', 'warning');
      return;
    }

    setUploading(true);

    try {
      // 检查是否在 Electron 环境中，且能获取到绝对路径
      const isElectron = typeof navigator !== 'undefined' && navigator.userAgent.toLowerCase().includes('electron');
      const filepath = (file as any).path;
      
      let res;
      if (isElectron && filepath) {
        // Electron 极速上传模式：直接发送绝对路径给后端
        res = await fetch('/api/v1/upload_local_pdf', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filepath }),
        });
      } else {
        // 传统 Web 上传模式：通过 FormData 传输二进制流
        const formData = new FormData();
        formData.append('file', file);
        res = await fetch('/api/v1/upload_pdf', {
          method: 'POST',
          body: formData,
        });
      }
      
      const data = await res.json();

      if (data.documentId) {
        const isNew = data.status === 'success';
        showToast(
          isNew ? `✅ 上传成功：${file.name}` : `ℹ️ 已存在，秒传：${file.name}`,
          isNew ? 'success' : 'info'
        );
        onDocumentUploaded?.(data.documentId);
        // 上传后刷新列表
        await onRefresh();
      }
    } catch {
      showToast('上传失败，请检查后端服务是否运行（localhost:8000）', 'error');
    } finally {
      setUploading(false);
      // 清空 input，允许重复上传同一文件
      e.target.value = '';
    }
  };

  const formatSessionId = (taskId: string) => {
    if (taskId === 'default_session') return '默认会话';
    if (taskId.startsWith('session_')) {
      const ts = parseInt(taskId.replace('session_', ''));
      if (!isNaN(ts)) {
        return new Date(ts).toLocaleString('zh-CN', {
          month: 'short', day: 'numeric',
          hour: '2-digit', minute: '2-digit',
        });
      }
    }
    // 截断显示
    return taskId.length > 12 ? taskId.slice(0, 12) + '…' : taskId;
  };

  return (
    <div style={{
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      background: 'var(--panel-bg)',
      borderRadius: '8px',
      border: '1px solid var(--glass-border)',
      overflow: 'hidden',
    }}>
      {/* ================================================================
          知识库区域
          ================================================================ */}
      {/* 头部 — 统一 48px 高度 */}
      <div style={{
        height: '48px',
        minHeight: '48px',
        padding: '0 14px',
        borderBottom: '1px solid var(--glass-border)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '8px',
        flexShrink: 0,
      }}>
        <span style={{
          fontWeight: 600,
          color: 'var(--text-primary)',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          fontSize: '0.88rem',
        }}>
          <FileText size={16} />
          知识库 ({documents.length})
        </span>

        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
          {/* 刷新按钮 — 调用 API 而非 reload() */}
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-muted)',
              cursor: refreshing ? 'default' : 'pointer',
              padding: '4px',
              display: 'flex',
              alignItems: 'center',
            }}
            title="刷新文档列表"
          >
            <RefreshCw
              size={13}
              style={{
                animation: refreshing ? 'spin 0.8s linear infinite' : 'none',
              }}
            />
          </button>

          {/* 上传 PDF 按钮 */}
          <label
            title="上传 PDF 到知识库"
            style={{
              cursor: uploading ? 'default' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              padding: '4px',
              color: uploading ? 'var(--text-muted)' : 'var(--accent)',
            }}
          >
            {uploading
              ? <Loader size={13} style={{ animation: 'spin 1s linear infinite' }} />
              : <Upload size={13} />
            }
            <input
              type="file"
              accept="application/pdf"
              onChange={handleFileUpload}
              disabled={uploading}
              style={{ display: 'none' }}
            />
          </label>
        </div>
      </div>

      {/* 文档列表 */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px', minHeight: 0 }}>
        {documents.length === 0 ? (
          <div style={{
            padding: '24px 12px',
            textAlign: 'center',
            color: 'var(--text-muted)',
            fontSize: '0.82rem',
          }}>
            <FileText size={28} style={{ opacity: 0.35, marginBottom: '8px' }} />
            <div style={{ marginBottom: '4px' }}>知识库为空</div>
            <div style={{ fontSize: '0.72rem', opacity: 0.7 }}>
              点击右上角 ↑ 上传 PDF
            </div>
          </div>
        ) : (
          documents.map((doc) => {
            const statusInfo = STATUS_MAP[doc.status] ?? { color: '#94a3b8', label: doc.status };
            const isDeleting = deletingId === doc.id;
            return (
              <div
                key={doc.id}
                onClick={() => onSelect(doc.id)}
                title={doc.filename}
                style={{
                  padding: '10px 11px',
                  marginBottom: '4px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  background: selectedId === doc.id ? 'var(--accent-light)' : 'transparent',
                  border: selectedId === doc.id
                    ? '1px solid var(--accent)'
                    : '1px solid transparent',
                  transition: 'all 0.15s ease',
                  opacity: isDeleting ? 0.4 : 1,
                }}
              >
                {/* 文件名 + 删除按钮 */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '7px', marginBottom: '5px' }}>
                  <FileText size={13} style={{ color: 'var(--text-secondary)', flexShrink: 0 }} />
                  <span style={{
                    flex: 1,
                    fontSize: '0.82rem',
                    color: 'var(--text-primary)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    fontWeight: 500,
                  }}>
                    {doc.filename}
                  </span>
                  {/* 删除按钮 */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDeleteDocument(doc.id, doc.filename);
                    }}
                    disabled={isDeleting}
                    title={`删除 ${doc.filename}（级联清理 ES + Neo4j + 磁盘）`}
                    style={{
                      background: 'none',
                      border: 'none',
                      color: 'var(--text-muted)',
                      cursor: isDeleting ? 'default' : 'pointer',
                      padding: '2px',
                      display: 'flex',
                      alignItems: 'center',
                      opacity: 0.3,
                      transition: 'opacity 0.15s, color 0.15s',
                      flexShrink: 0,
                    }}
                    onMouseEnter={e => {
                      e.currentTarget.style.opacity = '1';
                      e.currentTarget.style.color = 'var(--status-error)';
                    }}
                    onMouseLeave={e => {
                      e.currentTarget.style.opacity = '0.3';
                      e.currentTarget.style.color = 'var(--text-muted)';
                    }}
                  >
                    {isDeleting ? <Loader size={11} style={{ animation: 'spin 1s linear infinite' }} /> : <Trash2 size={11} />}
                  </button>
                </div>
                {/* 次要信息行 — 左状态 右日期 */}
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  fontSize: '0.7rem',
                  paddingLeft: '20px',
                }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <span style={{
                      width: '5px',
                      height: '5px',
                      borderRadius: '50%',
                      background: statusInfo.color,
                      flexShrink: 0,
                      animation: statusInfo.pulsing ? 'pulse 1.5s ease-in-out infinite' : 'none',
                    }} />
                    <span style={{ color: 'var(--text-muted)', opacity: 0.8 }}>{statusInfo.label}</span>
                  </span>
                  <span style={{ color: 'var(--text-muted)', opacity: 0.6, flexShrink: 0 }}>{formatDate(doc.created_at)}</span>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* 底部提示 */}
      <div style={{
        padding: '8px 12px',
        borderTop: '1px solid var(--glass-border)',
        fontSize: '0.72rem',
        color: 'var(--text-muted)',
        textAlign: 'center',
      }}>
        点击文档选为问答上下文
      </div>

      {/* 检索到的文献区域（无蓝色底纹） */}
      {retrievalSources && retrievalSources.length > 0 && (
        <div style={{
          borderTop: '1px solid var(--glass-border)',
          padding: '8px',
        }}>
          <div style={{
            fontSize: '0.78rem',
            fontWeight: 600,
            color: 'var(--text-secondary)',
            padding: '4px 6px 8px',
            display: 'flex',
            alignItems: 'center',
            gap: '5px',
          }}>
            🔍 检索到的文献 ({retrievalSources.length})
          </div>
          {retrievalSources.map((src) => (
            <div
              key={src.doc_id}
              onClick={() => onRetrievedSelect?.(src.doc_id)}
              style={{
                padding: '8px 10px',
                marginBottom: '3px',
                borderRadius: '6px',
                cursor: 'pointer',
                background: 'transparent',
                border: '1px solid var(--glass-border)',
                transition: 'all 0.15s ease',
              }}
              onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.04)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '3px' }}>
                <FileText size={12} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
                <span style={{
                  flex: 1,
                  fontSize: '0.8rem',
                  color: 'var(--text-primary)',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}>
                  {src.filename}
                </span>
              </div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', display: 'flex', gap: '8px' }}>
                {src.pages.length > 0 && <span>p.{src.pages.join(',')}</span>}
                <span>得分: {(src.score * 100).toFixed(0)}%</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ================================================================
          对话记录区域
          ================================================================ */}
      <div style={{
        borderTop: '1px solid var(--glass-border)',
        display: 'flex',
        flexDirection: 'column',
        minHeight: '120px',
        maxHeight: '260px',
      }}>
        {/* 对话记录头部 */}
        <div style={{
          height: '40px',
          minHeight: '40px',
          padding: '0 14px',
          borderBottom: '1px solid var(--glass-border)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexShrink: 0,
        }}>
          <span style={{
            fontWeight: 600,
            color: 'var(--text-primary)',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            fontSize: '0.82rem',
          }}>
            <MessageSquare size={14} />
            对话记录 ({chatSessions?.length || 0})
          </span>
          <button
            onClick={onNewSession}
            title="新建对话"
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--accent)',
              cursor: 'pointer',
              padding: '4px',
              display: 'flex',
              alignItems: 'center',
              transition: 'opacity 0.15s',
            }}
            onMouseEnter={e => (e.currentTarget.style.opacity = '0.7')}
            onMouseLeave={e => (e.currentTarget.style.opacity = '1')}
          >
            <Plus size={14} />
          </button>
        </div>

        {/* 会话列表 */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '6px 8px', minHeight: 0 }}>
          {(!chatSessions || chatSessions.length === 0) ? (
            <div style={{
              padding: '16px 8px',
              textAlign: 'center',
              color: 'var(--text-muted)',
              fontSize: '0.75rem',
            }}>
              <MessageSquare size={20} style={{ opacity: 0.3, marginBottom: '6px' }} />
              <div>暂无对话记录</div>
              <div style={{ fontSize: '0.68rem', opacity: 0.6, marginTop: '2px' }}>
                发送消息后自动保存
              </div>
            </div>
          ) : (
            chatSessions.map((session) => {
              const isActive = session.task_id === currentSessionId;
              return (
                <div
                  key={session.task_id}
                  onClick={() => onSwitchSession?.(session.task_id)}
                  style={{
                    padding: '8px 10px',
                    marginBottom: '3px',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    background: isActive ? 'var(--accent-light)' : 'transparent',
                    border: isActive
                      ? '1px solid var(--accent)'
                      : '1px solid transparent',
                    transition: 'all 0.15s ease',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                  }}
                  onMouseEnter={e => {
                    if (!isActive) e.currentTarget.style.background = 'rgba(255,255,255,0.03)';
                  }}
                  onMouseLeave={e => {
                    if (!isActive) e.currentTarget.style.background = 'transparent';
                  }}
                >
                  <div style={{ flex: 1, overflow: 'hidden', minWidth: 0 }}>
                    <div style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '5px',
                      marginBottom: '3px',
                    }}>
                      <MessageSquare size={11} style={{
                        color: isActive ? 'var(--accent)' : 'var(--text-muted)',
                        flexShrink: 0,
                      }} />
                      <span style={{
                        fontSize: '0.78rem',
                        color: isActive ? 'var(--accent)' : 'var(--text-primary)',
                        fontWeight: isActive ? 600 : 400,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}>
                        {formatSessionId(session.task_id)}
                      </span>
                    </div>
                    <div style={{
                      fontSize: '0.68rem',
                      color: 'var(--text-muted)',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                      paddingLeft: '16px',
                    }}>
                      {session.preview || '空对话'} · {session.message_count} 条
                    </div>
                  </div>
                  {/* 删除按钮 */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteSession?.(session.task_id);
                    }}
                    title="删除此对话"
                    style={{
                      background: 'none',
                      border: 'none',
                      color: 'var(--text-muted)',
                      cursor: 'pointer',
                      padding: '3px',
                      display: 'flex',
                      alignItems: 'center',
                      opacity: 0.4,
                      transition: 'opacity 0.15s, color 0.15s',
                      flexShrink: 0,
                    }}
                    onMouseEnter={e => {
                      e.currentTarget.style.opacity = '1';
                      e.currentTarget.style.color = 'var(--status-error)';
                    }}
                    onMouseLeave={e => {
                      e.currentTarget.style.opacity = '0.4';
                      e.currentTarget.style.color = 'var(--text-muted)';
                    }}
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};

export default Sidebar;