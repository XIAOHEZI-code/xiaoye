import { useEffect, useState, useRef, useCallback } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { X, RefreshCw } from 'lucide-react';

interface Node {
  id: string;
  name: string;
  label: string;
  val: number;
}

interface Link {
  source: string;
  target: string;
  type: string;
  mechanism: string;
  context: string;
}

interface GraphData {
  nodes: Node[];
  links: Link[];
}

export function KnowledgeGraphViewer({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<GraphData>({ nodes: [], links: [] });
  const [loading, setLoading] = useState(true);
  const fgRef = useRef<any>(null);

  useEffect(() => {
    fetch('/api/v1/graph?limit=500')
      .then(res => res.json())
      .then((d: GraphData) => {
        setData(d);
        setLoading(false);
      })
      .catch(e => {
        console.error(e);
        setLoading(false);
      });
  }, []);

  const getNodeColor = (label: string) => {
    switch (label) {
      case 'Material': return '#3b82f6'; // blue
      case 'Process': return '#f59e0b'; // amber
      case 'Property': return '#10b981'; // green
      case 'Structure': return '#8b5cf6'; // purple
      case 'Equipment': return '#64748b'; // slate
      default: return '#9ca3af'; // gray
    }
  };

  const drawNode = useCallback((node: any, ctx: any, globalScale: any) => {
    const label = node.name;
    const fontSize = 12 / globalScale;
    ctx.font = `${fontSize}px "Inter", "Microsoft YaHei", sans-serif`;
    const textWidth = ctx.measureText(label).width;
    const bckgDimensions = [textWidth, fontSize].map(n => n + fontSize * 0.4);

    ctx.fillStyle = 'rgba(20, 20, 20, 0.8)';
    ctx.beginPath();
    ctx.roundRect(
      node.x - bckgDimensions[0] / 2, 
      node.y - bckgDimensions[1] / 2, 
      bckgDimensions[0], 
      bckgDimensions[1],
      4
    );
    ctx.fill();

    ctx.strokeStyle = getNodeColor(node.label);
    ctx.lineWidth = 1.5 / globalScale;
    ctx.stroke();

    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = '#ffffff';
    ctx.fillText(label, node.x, node.y);

    node.__bckgDimensions = bckgDimensions;
  }, []);

  return (
    <div style={{
      position: 'fixed',
      top: 0, left: 0, right: 0, bottom: 0,
      zIndex: 50,
      backgroundColor: 'rgba(0,0,0,0.8)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '16px',
      backdropFilter: 'blur(4px)'
    }}>
      <div style={{
        backgroundColor: 'var(--panel-bg)',
        width: '100%',
        maxWidth: '90vw',
        height: '90vh',
        borderRadius: '16px',
        boxShadow: 'var(--glass-shadow)',
        display: 'flex',
        flexDirection: 'column',
        border: '1px solid var(--glass-border)',
        overflow: 'hidden',
        position: 'relative'
      }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '16px',
          borderBottom: '1px solid var(--glass-border)',
          backgroundColor: 'rgba(0,0,0,0.2)'
        }}>
          <h2 style={{
            fontSize: '1.1rem',
            fontWeight: 500,
            color: 'var(--text-primary)',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            margin: 0
          }}>
            <div style={{
              width: '10px', height: '10px', 
              borderRadius: '50%', 
              backgroundColor: '#3b82f6',
              animation: 'pulse 2s infinite'
            }} />
            冶金知识图谱全景可视化 (Knowledge Graph)
          </h2>
          <button 
            onClick={onClose}
            style={{
              background: 'none', border: 'none',
              color: 'var(--text-muted)',
              cursor: 'pointer', padding: '8px',
              borderRadius: '8px',
              display: 'flex', alignItems: 'center'
            }}
            onMouseOver={(e) => e.currentTarget.style.color = 'var(--text-primary)'}
            onMouseOut={(e) => e.currentTarget.style.color = 'var(--text-muted)'}
          >
            <X size={20} />
          </button>
        </div>

        <div style={{ flex: 1, position: 'relative', backgroundColor: 'var(--base-bg)' }}>
          {loading ? (
            <div style={{
              position: 'absolute', inset: 0,
              display: 'flex', flexDirection: 'column',
              alignItems: 'center', justifyContent: 'center',
              color: 'var(--text-muted)'
            }}>
              <RefreshCw className="animate-spin w-8 h-8 mb-4" size={32} style={{ animation: 'spin 1s linear infinite', color: '#3b82f6' }} />
              <span style={{ fontSize: '1.1rem' }}>正在从 Neo4j 提取高维图谱结构...</span>
            </div>
          ) : (
            <ForceGraph2D
              ref={fgRef}
              graphData={data}
              nodeCanvasObject={drawNode}
              nodePointerAreaPaint={(node: any, color, ctx) => {
                ctx.fillStyle = color;
                const bckgDimensions = node.__bckgDimensions;
                bckgDimensions && ctx.fillRect(
                  node.x - bckgDimensions[0] / 2, 
                  node.y - bckgDimensions[1] / 2, 
                  bckgDimensions[0], 
                  bckgDimensions[1]
                );
              }}
              linkColor={() => 'rgba(255,255,255,0.15)'}
              linkWidth={1.5}
              linkDirectionalArrowLength={4}
              linkDirectionalArrowRelPos={1}
              onNodeClick={(node) => {
                fgRef.current?.centerAt(node.x, node.y, 1000);
                fgRef.current?.zoom(4, 1000);
              }}
              linkCanvasObjectMode={() => 'after'}
              linkCanvasObject={(link: any, ctx: any, _globalScale: any) => {
                const MAX_FONT_SIZE = 5;
                const start = link.source;
                const end = link.target;
                
                if (typeof start !== 'object' || typeof end !== 'object') return;

                const textPos = Object.assign({}, ...['x', 'y'].map(c => ({
                  [c]: start[c] + (end[c] - start[c]) / 2
                })));

                const relLink = { x: end.x - start.x, y: end.y - start.y };
                const maxTextLength = Math.sqrt(Math.pow(relLink.x, 2) + Math.pow(relLink.y, 2)) - 10;

                let textAngle = Math.atan2(relLink.y, relLink.x);
                if (textAngle > Math.PI / 2) textAngle = -(Math.PI - textAngle);
                if (textAngle < -Math.PI / 2) textAngle = -(-Math.PI - textAngle);

                const label = link.type;

                ctx.font = '1px Sans-Serif';
                const fontSize = Math.min(MAX_FONT_SIZE, maxTextLength / ctx.measureText(label).width);
                ctx.font = `${fontSize}px Sans-Serif`;
                const textWidth = ctx.measureText(label).width;
                const bckgDimensions = [textWidth, fontSize].map(n => n + fontSize * 0.2); 

                ctx.save();
                ctx.translate(textPos.x, textPos.y);
                ctx.rotate(textAngle);

                ctx.fillStyle = 'rgba(0, 0, 0, 0.8)';
                ctx.fillRect(- bckgDimensions[0] / 2, - bckgDimensions[1] / 2, bckgDimensions[0], bckgDimensions[1]);

                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillStyle = 'rgba(255, 255, 255, 0.7)';
                ctx.fillText(label, 0, 0);
                ctx.restore();
              }}
            />
          )}

          {/* Legend */}
          <div style={{
            position: 'absolute', bottom: '24px', left: '24px',
            backgroundColor: 'rgba(0,0,0,0.6)',
            backdropFilter: 'blur(8px)',
            padding: '20px', borderRadius: '12px',
            border: '1px solid var(--glass-border)',
            fontSize: '0.85rem', color: 'var(--text-primary)',
            display: 'flex', flexDirection: 'column', gap: '12px',
            pointerEvents: 'none', boxShadow: '0 10px 30px rgba(0,0,0,0.5)'
          }}>
            <h3 style={{ margin: 0, borderBottom: '1px solid rgba(255,255,255,0.2)', paddingBottom: '8px', color: 'white', fontWeight: 500 }}>Neo4j Ontology</h3>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div style={{ width: '12px', height: '12px', borderRadius: '2px', backgroundColor: '#3b82f6' }}/><span>Material (材料)</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div style={{ width: '12px', height: '12px', borderRadius: '2px', backgroundColor: '#f59e0b' }}/><span>Process (工艺)</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div style={{ width: '12px', height: '12px', borderRadius: '2px', backgroundColor: '#10b981' }}/><span>Property (性能)</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div style={{ width: '12px', height: '12px', borderRadius: '2px', backgroundColor: '#8b5cf6' }}/><span>Structure (组织)</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div style={{ width: '12px', height: '12px', borderRadius: '2px', backgroundColor: '#64748b' }}/><span>Equipment (设备)</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
