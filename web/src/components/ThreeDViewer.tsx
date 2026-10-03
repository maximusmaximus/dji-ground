import React, { useEffect, useRef, useState } from 'react';
import { Point3D } from '../types.ts';

interface Props {
  points: Point3D[];
  dronePose?: { x: number; y: number; z: number; yaw_deg: number; pitch_deg: number };
  activeSessionId?: string | null;
  onStartScan: () => Promise<void>;
  onStopScan: () => Promise<void>;
}

export const ThreeDViewer: React.FC<Props> = ({
  points,
  dronePose,
  activeSessionId,
  onStartScan,
  onStopScan,
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [rotX, setRotX] = useState(30);
  const [rotY, setRotY] = useState(-45);
  const [zoom, setZoom] = useState(15);
  const isDragging = useRef(false);
  const lastMousePos = useRef({ x: 0, y: 0 });

  // Mouse drag handlers for 3D rotation
  const handleMouseDown = (e: React.MouseEvent) => {
    isDragging.current = true;
    lastMousePos.current = { x: e.clientX, y: e.clientY };
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging.current) return;
    const dx = e.clientX - lastMousePos.current.x;
    const dy = e.clientY - lastMousePos.current.y;
    setRotY((prev) => prev + dx * 0.5);
    setRotX((prev) => Math.max(-85, Math.min(85, prev + dy * 0.5)));
    lastMousePos.current = { x: e.clientX, y: e.clientY };
  };

  const handleMouseUp = () => {
    isDragging.current = false;
  };

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    setZoom((prev) => Math.max(5, Math.min(60, prev + e.deltaY * 0.02)));
  };

  // 3D Canvas Projection Renderer
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);

    // Dark grid background
    ctx.fillStyle = '#090d13';
    ctx.fillRect(0, 0, width, height);

    const radX = (rotX * Math.PI) / 180;
    const radY = (rotY * Math.PI) / 180;

    const project = (x: number, y: number, z: number) => {
      // Rotate around Y
      const x1 = x * Math.cos(radY) - y * Math.sin(radY);
      const y1 = x * Math.sin(radY) + y * Math.cos(radY);
      const z1 = z;

      // Rotate around X
      const y2 = y1 * Math.cos(radX) - z1 * Math.sin(radX);
      const z2 = y1 * Math.sin(radX) + z1 * Math.cos(radX);
      const x2 = x1;

      // Camera projection
      const scale = (width / 2) / zoom;
      const screenX = width / 2 + x2 * scale;
      const screenY = height / 2 - z2 * scale + y2 * (scale * 0.25);
      return { sx: screenX, sy: screenY, depth: y2 };
    };

    // Render Ground Reference Grid
    ctx.strokeStyle = '#1b222d';
    ctx.lineWidth = 1;
    for (let g = -10; g <= 10; g += 2) {
      const p1 = project(g, -10, 0);
      const p2 = project(g, 10, 0);
      ctx.beginPath();
      ctx.moveTo(p1.sx, p1.sy);
      ctx.lineTo(p2.sx, p2.sy);
      ctx.stroke();

      const p3 = project(-10, g, 0);
      const p4 = project(10, g, 0);
      ctx.beginPath();
      ctx.moveTo(p3.sx, p3.sy);
      ctx.lineTo(p4.sx, p4.sy);
      ctx.stroke();
    }

    // Render 3D Point Cloud
    points.forEach((pt) => {
      const proj = project(pt.x, pt.y, pt.z);
      if (proj.sx >= 0 && proj.sx < width && proj.sy >= 0 && proj.sy < height) {
        ctx.fillStyle = `rgb(${pt.r}, ${pt.g}, ${pt.b})`;
        ctx.fillRect(proj.sx - 1, proj.sy - 1, 3, 3);
      }
    });

    // Render Drone Pose Marker & Frustum
    if (dronePose) {
      const droneProj = project(dronePose.x, dronePose.y, dronePose.z);
      ctx.fillStyle = '#ffcc00';
      ctx.beginPath();
      ctx.arc(droneProj.sx, droneProj.sy, 6, 0, Math.PI * 2);
      ctx.fill();

      // Heading vector
      const yawRad = (dronePose.yaw_deg * Math.PI) / 180;
      const hx = dronePose.x + Math.sin(yawRad) * 1.5;
      const hy = dronePose.y + Math.cos(yawRad) * 1.5;
      const headProj = project(hx, hy, dronePose.z);
      ctx.strokeStyle = '#ff3333';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(droneProj.sx, droneProj.sy);
      ctx.lineTo(headProj.sx, headProj.sy);
      ctx.stroke();
    }
  }, [points, dronePose, rotX, rotY, zoom]);

  return (
    <div style={{ backgroundColor: '#161b22', padding: '16px', borderRadius: '8px', border: '1px solid #30363d' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
        <div>
          <h3 style={{ fontSize: '14px', color: '#8b949e', textTransform: 'uppercase' }}>
            Live 3D Point Cloud Viewport
          </h3>
          <div style={{ fontSize: '11px', color: '#7ee787' }}>
            {points.length.toLocaleString()} Points Loaded | Drag to Orbit | Scroll to Zoom
          </div>
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          {!activeSessionId ? (
            <button
              onClick={onStartScan}
              style={{ padding: '6px 12px', backgroundColor: '#238636', border: 'none', borderRadius: '4px', color: '#fff', fontSize: '12px', fontWeight: 'bold', cursor: 'pointer' }}
            >
              Start 3D Scan
            </button>
          ) : (
            <button
              onClick={onStopScan}
              style={{ padding: '6px 12px', backgroundColor: '#da3633', border: 'none', borderRadius: '4px', color: '#fff', fontSize: '12px', fontWeight: 'bold', cursor: 'pointer' }}
            >
              Stop & Export (.ply)
            </button>
          )}
        </div>
      </div>

      <div
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onWheel={handleWheel}
        style={{ cursor: 'grab', userSelect: 'none', borderRadius: '6px', overflow: 'hidden' }}
      >
        <canvas ref={canvasRef} width={640} height={320} style={{ width: '100%', height: '320px', display: 'block' }} />
      </div>
    </div>
  );
};
