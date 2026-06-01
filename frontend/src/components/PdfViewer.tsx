import React, { useState, useRef } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';
import type { BoundingBox } from '../App';
import { FileUp, ZoomIn, ZoomOut, Search, Sun } from 'lucide-react';
import { useToast } from './Toast';

// Use Vite's native URL resolution to ensure worker and its WASM dependencies are served correctly
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

// PDF.js document options — CJK 字体正确渲染及 WASM 图像解码
const PDF_OPTIONS = {
  cMapUrl: '/pdf-assets/cmaps/',
  standardFontDataUrl: '/pdf-assets/standard_fonts/',
  wasmUrl: '/pdf-assets/', // 必须提供，否则 JpxImage 和 qcms 会抛错导致图片无法渲染
  disableFontFace: true, // 阻止由于缺字体(如 STSong-Light)导致整个 Canvas 绘图上下文崩溃
  stopAtErrors: false,
};

type Point = { x: number; y: number };

interface Props {
  onForkTask: (id: string, documentId: string, type: string, bbox: BoundingBox) => void;
  onDocumentIdChange: (id: string | null) => void;
  pdfUrl?: string | null;                // 从服务端加载的 PDF URL
  sourceType?: 'uploaded' | 'retrieved'; // 来源类型：上传=蓝底纹，检索=无底纹
  targetPage?: number | null;            // 外部指令：跳转到指定页码（由引用角标触发）
}

const PdfViewer: React.FC<Props> = ({ onForkTask, onDocumentIdChange, pdfUrl, sourceType = 'uploaded', targetPage }) => {
  const { showToast } = useToast();
  const [file, setFile] = useState<File | string | null>(null); // File 或 URL string
  const [numPages, setNumPages] = useState<number>(0);
  const [pageNumber, setPageNumber] = useState<number>(1);
  const [scale, setScale] = useState<number>(1.2);
  const [documentId, setDocumentId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [brightness, setBrightness] = useState(85);
  // const [contrast, setContrast] = useState(95);
  const [currentSourceType, setCurrentSourceType] = useState<'uploaded' | 'retrieved'>('uploaded');
  
  
  // Selection Box State
  const [isDrawing, setIsDrawing] = useState(false);
  const [startPoint, setStartPoint] = useState<Point | null>(null);
  const [currentPoint, setCurrentPoint] = useState<Point | null>(null);
  const [finalBox, setFinalBox] = useState<{ x: number, y: number, w: number, h: number } | null>(null);
  
  // Context Menu State
  const [contextMenu, setContextMenu] = useState<{ x: number, y: number } | null>(null);

  const containerRef = useRef<HTMLDivElement>(null);

  // 当父组件传入 pdfUrl 变化时，从服务端加载 PDF
  React.useEffect(() => {
    if (pdfUrl) {
      setFile(pdfUrl);
      setCurrentSourceType(sourceType || 'uploaded');
      setPageNumber(1);
      // 从 URL 提取 doc_id
      const match = pdfUrl.match(/documents\/([^/]+)\/pdf/);
      if (match) {
        setDocumentId(match[1]);
        onDocumentIdChange(match[1]);
      }
    }
  }, [pdfUrl, sourceType]);

  // 外部跳转指令：当 targetPage 变化时自动翻页 + 闪烁动画
  const [jumpFlash, setJumpFlash] = React.useState(false);
  React.useEffect(() => {
    if (targetPage && targetPage > 0) {
      // 如果 PDF 还没加载完成（numPages=0），等 numPages 更新后会自动重试
      if (numPages > 0 && targetPage <= numPages) {
        setPageNumber(targetPage);
        // 触发页面闪烁高亮效果（3次脉冲渐隐）
        setJumpFlash(true);
        const timer = setTimeout(() => setJumpFlash(false), 2500);
        return () => clearTimeout(timer);
      } else if (numPages === 0) {
        console.log(`[PdfViewer] Waiting for PDF to load... targetPage=${targetPage}`);
      }
    }
  }, [targetPage, numPages]);

  async function onFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const { files } = event.target;
    if (files && files[0]) {
      const selectedFile = files[0];
      setFile(selectedFile);
      setCurrentSourceType('uploaded'); // 手动上传始终是 uploaded
      setUploading(true);

      const formData = new FormData();
      formData.append('file', selectedFile);

      try {
        const response = await fetch('/api/v1/upload_pdf', {
          method: 'POST',
          body: formData,
        });
        const data = await response.json();
        
        if (data.documentId) {
          setDocumentId(data.documentId);
          onDocumentIdChange(data.documentId);
          showToast(`文档已就绪：${selectedFile.name}`, 'success');
        } else if (data.message === 'File already exists') {
          setDocumentId(data.documentId);
          onDocumentIdChange(data.documentId);
          showToast(`文档已在知识库中：${selectedFile.name}`, 'info');
        }
      } catch (err) {
        console.error("Upload failed", err);
        showToast('PDF 上传失败，请检查后端服务是否运行', 'error');
      } finally {
        setUploading(false);
      }
    }
  }

  function onDocumentLoadSuccess({ numPages }: { numPages: number }) {
    setNumPages(numPages);
    setPageNumber(1);
  }

  // Clear drawing box if zoom changes
  React.useEffect(() => {
    setFinalBox(null);
    setContextMenu(null);
  }, [scale]);

  // --- Bounding Box Drawing Logic ---
  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return; // Only left click
    if (contextMenu) setContextMenu(null); // Close menu
    
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    
    setIsDrawing(true);
    setStartPoint({ x, y });
    setCurrentPoint({ x, y });
    setFinalBox(null);
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDrawing || !startPoint) return;
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    
    // Bind within container
    let x = Math.max(0, Math.min(e.clientX - rect.left, rect.width));
    let y = Math.max(0, Math.min(e.clientY - rect.top, rect.height));

    setCurrentPoint({ x, y });
  };

  const handleMouseUp = () => {
    if (!isDrawing || !startPoint || !currentPoint) return;
    setIsDrawing(false);
    
    const width = Math.abs(currentPoint.x - startPoint.x);
    const height = Math.abs(currentPoint.y - startPoint.y);
    
    // Ignore tiny accidental clicks
    if (width > 10 && height > 10) {
      setFinalBox({
        x: Math.min(startPoint.x, currentPoint.x),
        y: Math.min(startPoint.y, currentPoint.y),
        w: width,
        h: height
      });
    } else {
      setFinalBox(null);
    }
  };

  const handleRightClick = (e: React.MouseEvent) => {
    e.preventDefault();
    if (finalBox) {
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) return;
      setContextMenu({
        x: e.clientX - rect.left,
        y: e.clientY - rect.top
      });
    }
  };

  const dispatchFork = (type: string) => {
    if (!documentId) {
      showToast('请等待文档上传完成后再操作', 'warning');
      return;
    }
    if (finalBox && containerRef.current) {
      const rect = containerRef.current.getBoundingClientRect();
      const normalizeX = (v: number) => v / rect.width;
      const normalizeY = (v: number) => v / rect.height;

      const bbox: BoundingBox = {
        x0: normalizeX(finalBox.x),
        y0: normalizeY(finalBox.y),
        x1: normalizeX(finalBox.x + finalBox.w),
        y1: normalizeY(finalBox.y + finalBox.h),
        pageNumber: pageNumber
      };

      const taskId = "task_" + Math.random().toString(36).substr(2, 9);
      console.log(`[Frontend] Dispatching Event -> ${type}`, bbox);
      onForkTask(taskId, documentId, type, bbox);
      
      setContextMenu(null);
      setFinalBox(null);
    }
  };

  // Compute live drawing box style
  const getDrawingStyle = () => {
    if (!startPoint || !currentPoint) return {};
    return {
      left: Math.min(startPoint.x, currentPoint.x),
      top: Math.min(startPoint.y, currentPoint.y),
      width: Math.abs(currentPoint.x - startPoint.x),
      height: Math.abs(currentPoint.y - startPoint.y),
    };
  };

  return (
    <div className="pdf-container" style={{ height: '100%', flexDirection: 'column' }}>
      
      {/* Toolbar */}
      <div style={{ display: 'flex', gap: '8px', padding: '8px 10px', background: 'rgba(0,0,0,0.25)', alignItems: 'center', flexWrap: 'wrap' }}>
        <input type="file" onChange={onFileChange} accept="application/pdf" id="pdf-upload" style={{ display: 'none' }} />
        <label htmlFor="pdf-upload" style={{
          cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '5px',
          padding: '5px 10px', background: 'var(--accent-light)',
          border: '1px solid var(--accent)', borderRadius: '5px',
          color: 'var(--accent)', fontSize: '0.82rem', whiteSpace: 'nowrap',
        }}>
          <FileUp size={14} /> {uploading ? '上传中...' : '载入 PDF'}
        </label>
        {documentId && <span style={{ fontSize: '12px', color: 'var(--success)' }}>✓ 已就绪</span>}
        
        {file && (
          <>
            <span style={{ marginLeft: 'auto', fontSize: '13px', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
              {numPages > 0 ? `第 ${pageNumber} / ${numPages} 页` : '解析中...'}
            </span>
            <button
              onClick={() => setPageNumber(p => Math.max(1, p - 1))}
              disabled={pageNumber <= 1 || numPages === 0}
              style={{ background: 'none', border: '1px solid var(--glass-border)', borderRadius: '4px', color: 'var(--text-secondary)', padding: '3px 8px', cursor: 'pointer' }}
            >&lt;</button>
            <button
              onClick={() => setPageNumber(p => Math.min(numPages, p + 1))}
              disabled={pageNumber >= numPages || numPages === 0}
              style={{ background: 'none', border: '1px solid var(--glass-border)', borderRadius: '4px', color: 'var(--text-secondary)', padding: '3px 8px', cursor: 'pointer' }}
            >&gt;</button>
            <button onClick={() => setScale(s => Math.max(0.5, s - 0.2))} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: '3px' }} title="缩小">
              <ZoomOut size={15}/>
            </button>
            <button onClick={() => setScale(s => Math.min(3, s + 0.2))} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: '3px' }} title="放大">
              <ZoomIn size={15}/>
            </button>
            {/* 亮度滑块 — 解决白色PDF在暗色界面刺眼的问题 */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '5px', marginLeft: '4px' }} title="PDF 亮度（护眼调节）">
              <Sun size={13} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
              <input
                type="range"
                min={40}
                max={100}
                value={brightness}
                onChange={e => setBrightness(Number(e.target.value))}
                style={{ width: '64px', accentColor: 'var(--accent)', cursor: 'pointer' }}
              />
            </div>
          </>
        )}
      </div>

      {/* Document Area */}
      <div 
        style={{ flex: 1, overflow: 'auto', textAlign: 'center', backgroundColor: '#0f111a', padding: '20px' }}
      >
        {!file ? (
          <div style={{ margin: 'auto', color: 'var(--text-muted)', textAlign: 'center' }}>
            <FileUp size={48} style={{ opacity: 0.5, marginBottom: '16px' }} />
            <p style={{ fontSize: '0.9rem' }}>选择 PDF 文献开始阅读与分析</p>
            <p style={{ fontSize: '0.78rem', opacity: 0.6 }}>支持左键圈选区域，右键触发 Agent 解析</p>
          </div>
        ) : (
          <div 
            className="pdf-page-wrapper"
            ref={containerRef}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
            onContextMenu={handleRightClick}
            style={{
              position: 'relative',
              filter: `brightness(${brightness}%)`,
              transition: 'filter 0.2s ease',
            }}
          >
            {/* 引用跳转闪烁高亮覆盖层 — 3次脉冲金色光晕 */}
            {jumpFlash && (
              <div style={{
                position: 'absolute',
                inset: 0,
                background: 'linear-gradient(135deg, rgba(250, 204, 21, 0.18), rgba(251, 191, 36, 0.12))',
                pointerEvents: 'none',
                zIndex: 2,
                borderRadius: '4px',
                border: '2px solid rgba(250, 204, 21, 0.4)',
                boxShadow: '0 0 20px rgba(250, 204, 21, 0.15), inset 0 0 30px rgba(250, 204, 21, 0.08)',
                animation: 'citationPulse 2.5s ease-out forwards',
              }} />
            )}
            {/* 蓝色底纹覆盖层：仅用户上传的文档显示 */}
            {currentSourceType === 'uploaded' && (
              <div style={{
                position: 'absolute',
                inset: 0,
                background: 'rgba(99, 102, 241, 0.06)',
                pointerEvents: 'none',
                zIndex: 1,
                borderRadius: '4px',
              }} />
            )}
            <Document 
              file={file} 
              onLoadSuccess={onDocumentLoadSuccess} 
              options={PDF_OPTIONS}
              loading={<div style={{ padding: '20px', color: 'var(--text-muted)' }}>文献解析中...</div>}
            >
              <Page 
                pageNumber={pageNumber} 
                scale={scale} 
                devicePixelRatio={Math.max(window.devicePixelRatio || 1, 2)}
                renderTextLayer={true} 
                renderAnnotationLayer={true}
                loading={<div style={{ padding: '20px', color: 'var(--text-muted)' }}>页面渲染中...</div>}
              />
            </Document>

            {/* Live Drawing Box */}
            {isDrawing && <div className="drawing-box" style={getDrawingStyle()} />}
            
            {/* Final Rendered Box */}
            {finalBox && !isDrawing && (
              <div className="rendered-box" style={{ left: finalBox.x, top: finalBox.y, width: finalBox.w, height: finalBox.h }} />
            )}

            {/* Context Menu Hook */}
            {contextMenu && (
              <div 
                className="context-menu" 
                style={{ left: contextMenu.x, top: contextMenu.y }}
                onMouseDown={(e) => e.stopPropagation()}
              >
                <div className="menu-item" onMouseDown={(e) => { e.stopPropagation(); dispatchFork('analyze_region'); }}>
                  <Search size={14} /> 🔬 直接解析
                </div>
                <div className="menu-item" onMouseDown={(e) => { e.stopPropagation(); dispatchFork('deep_research'); }}>
                   🧠 深度科研
                </div>
                <hr style={{ borderColor: 'rgba(255,255,255,0.1)', margin: '4px 0' }}/>
                <div className="menu-item danger" onMouseDown={(e) => { e.stopPropagation(); setContextMenu(null); }}>取消</div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 引用跳转脉冲动画 — 3次金色光晕后渐隐 */}
      <style>{`
        @keyframes citationPulse {
          0% { opacity: 0; }
          8% { opacity: 1; }
          20% { opacity: 0.3; }
          35% { opacity: 0.9; }
          50% { opacity: 0.2; }
          65% { opacity: 0.7; }
          80% { opacity: 0.15; }
          100% { opacity: 0; border-color: transparent; box-shadow: none; }
        }
      `}</style>
    </div>
  );
};

export default PdfViewer;
