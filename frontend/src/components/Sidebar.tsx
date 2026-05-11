import React, { useState, useEffect } from 'react';
import { FileText, RefreshCw, Upload, Loader } from 'lucide-react';
import { useToast } from './Toast';
import type { RetrievalSource } from '../App';

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
  retrievalSources?: RetrievalSource[];           // AI 检索命中的文献
  onRetrievedSelect?: (docId: string) => void;    // 点击检索文献的回调
}

const STATUS_MAP: Record<string, { color: string; label: string }> = {
  ready:   { color: 'var(--success)',        label: '就绪' },
  pending: { color: 'var(--status-pending)', label: '处理中' },
  failed:  { color: 'var(--status-error)',   label: '失败' },
};

const Sidebar: React.FC<Props> = ({ documents, selectedId, onSelect, onRefresh, onDocumentUploaded, retrievalSources, onRetrievedSelect }) => {
  const { showToast } = useToast();
  const [uploading, setUploading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  // 自动轮询：当有 pending 状态的文档时，每 8 秒刷新一次
  const hasPending = documents.some(d => d.status === 'pending');
  useEffect(() => {
    if (!hasPending) return;
    const interval = setInterval(() => {
      onRefresh();
    }, 8000);
    return () => clearInterval(interval);
  }, [hasPending, onRefresh]);

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
    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch('http://localhost:8000/api/v1/upload_pdf', {
        method: 'POST',
        body: formData,
      });
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
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px' }}>
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
                }}
              >
                {/* 文件名 + 状态行 — Flex 对齐 */}
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
                </div>
                {/* 次要信息行 — 左状态 右日期，严格对齐 */}
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
    </div>
  );
};

export default Sidebar;