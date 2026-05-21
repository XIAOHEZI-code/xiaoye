import { useEffect, useRef, useState } from 'react';

/**
 * Resizer – 可拖拽的面板分割条（重构版）
 * 改进点：
 * 1. 触控区域扩大到 16px（视觉 2px + 透明缓冲区）
 * 2. Hover 高亮动画
 * 3. 中央拖拽图标
 * 4. 双击可折叠/展开（onCollapse 回调）
 */
interface ResizerProps {
  onDrag: (dx: number) => void;
  onCollapse?: () => void; // 双击折叠回调
  style?: React.CSSProperties;
}

export default function Resizer({ onDrag, onCollapse, style }: ResizerProps) {
  const elRef = useRef<HTMLDivElement>(null);
  const [isHovered, setIsHovered] = useState(false);
  const [isDragging, setIsDragging] = useState(false);

  // 用 useCallback 稳定 onDrag 引用，避免 useEffect 频繁重建
  const onDragRef = useRef(onDrag);
  useEffect(() => { onDragRef.current = onDrag; }, [onDrag]);

  useEffect(() => {
    let startX = 0;
    let dragging = false;

    const onMouseMove = (e: MouseEvent) => {
      if (!dragging) return;
      const delta = e.clientX - startX;
      startX = e.clientX;
      onDragRef.current(delta);
    };

    const onMouseUp = () => {
      if (!dragging) return;
      dragging = false;
      setIsDragging(false);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };

    const onMouseDown = (e: MouseEvent) => {
      e.preventDefault();
      dragging = true;
      startX = e.clientX;
      setIsDragging(true);
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none'; // 拖拽时禁止文本选中
      document.addEventListener('mousemove', onMouseMove);
      document.addEventListener('mouseup', onMouseUp);
    };

    const el = elRef.current;
    el?.addEventListener('mousedown', onMouseDown);

    return () => {
      el?.removeEventListener('mousedown', onMouseDown);
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };
  }, []); // 不依赖 onDrag，改用 ref

  const isActive = isHovered || isDragging;

  return (
    <div
      ref={elRef}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onDoubleClick={onCollapse}
      title={onCollapse ? '拖拽调整宽度，双击折叠/展开' : '拖拽调整宽度'}
      style={{
        width: '16px',           // 足够大的触控区域
        cursor: 'col-resize',
        position: 'relative',
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 10,
        ...style,
      }}
    >
      {/* 视觉分割线 */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          bottom: 0,
          left: '50%',
          transform: 'translateX(-50%)',
          width: isActive ? '3px' : '2px',
          background: isActive
            ? 'var(--accent)'
            : 'var(--glass-border)',
          borderRadius: '2px',
          transition: 'width 0.15s ease, background 0.15s ease',
          boxShadow: isActive ? '0 0 8px var(--accent)' : 'none',
        }}
      />

      {/* 中央拖拽图标 */}
      <div
        style={{
          position: 'relative',
          zIndex: 1,
          display: 'flex',
          flexDirection: 'column',
          gap: '3px',
          opacity: isActive ? 1 : 0.4,
          transition: 'opacity 0.15s ease',
          pointerEvents: 'none',
        }}
      >
        {[0, 1, 2, 3, 4].map(i => (
          <div
            key={i}
            style={{
              width: '4px',
              height: '4px',
              borderRadius: '50%',
              background: isActive ? 'var(--accent)' : 'var(--text-muted)',
              transition: 'background 0.15s ease',
            }}
          />
        ))}
      </div>
    </div>
  );
}
