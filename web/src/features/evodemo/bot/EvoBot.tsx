/**
 * EvoBot：几何体 + 两只胶囊眼的小角色。
 *
 * 运动原则参考 bloub（MIT）的逐帧测量结论：静止时不漂浮，“活着”只靠视线
 * 漂移与眨眼；形变用指数缓出、不回弹。形状与表情数据为本项目自绘，不使用
 * Grok 的几何点集。
 *
 * 高频属性（路径、眼睛位置、眨眼）通过 ref 直接写 DOM，避免每帧重渲染；
 * `animated={false}` 时完全不跑 requestAnimationFrame，供大量节点静态展示。
 */
import { motion } from 'motion/react';
import { useEffect, useId, useRef } from 'react';

import type { BotShape } from './shapes';
import { FACE_OFFSET, SAMPLES, radiiToPath, shapeRadii } from './shapes';

export type BotMood =
  | 'idle'
  | 'look'
  | 'think'
  | 'eval'
  | 'happy'
  | 'fail'
  | 'pruned'
  | 'best'
  | 'talk'
  | 'asking'
  | 'listen';

export interface EvoBotProps {
  shape?: BotShape;
  mood?: BotMood;
  size?: number;
  color?: string;
  /** 视线跟随鼠标。 */
  follow?: boolean;
  animated?: boolean;
  /** 固定视线方向（-1..1），用于对话时“看向”某处。 */
  gaze?: { x: number; y: number };
  className?: string;
}

const CENTER = 50;
const BODY = 33;
const MORPH_MS = 480;

const pointer = { x: -1, y: -1, active: false };
if (typeof window !== 'undefined') {
  window.addEventListener(
    'pointermove',
    (e) => {
      pointer.x = e.clientX;
      pointer.y = e.clientY;
      pointer.active = true;
    },
    { passive: true },
  );
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
}

const GAZE_INTERVAL: Partial<Record<BotMood, [number, number]>> = {
  idle: [1400, 3200],
  look: [500, 1100],
  eval: [260, 620],
  listen: [1800, 3600],
  asking: [2200, 4000],
  talk: [900, 1800],
};

function bodyColor(mood: BotMood, color: string): string {
  if (mood === 'fail') return '#94A3B8';
  if (mood === 'pruned') return '#CBD5E1';
  return color;
}

export function EvoBot({
  shape = 'circle',
  mood = 'idle',
  size = 48,
  color = '#2563EB',
  follow = false,
  animated = true,
  gaze,
  className,
}: EvoBotProps) {
  const uid = useId().replace(/:/g, '');
  const svgRef = useRef<SVGSVGElement>(null);
  const bodyRef = useRef<SVGPathElement>(null);
  const shineRef = useRef<SVGPathElement>(null);
  const eyesRef = useRef<SVGGElement>(null);
  const radii = useRef<Float32Array>(new Float32Array(shapeRadii(shape)));
  const morph = useRef<{ from: Float32Array; to: Float32Array; start: number } | null>(null);
  const moodRef = useRef(mood);
  const gazeRef = useRef(gaze);
  moodRef.current = mood;
  gazeRef.current = gaze;

  const writePath = () => {
    const d = radiiToPath(radii.current, BODY, CENTER, CENTER);
    bodyRef.current?.setAttribute('d', d);
    shineRef.current?.setAttribute('d', d);
  };
  const writePathRef = useRef(writePath);
  writePathRef.current = writePath;

  const face = FACE_OFFSET[shape];
  const eyeY = CENTER + face.dy * BODY;
  const eyeDx = 10 * face.spread;

  useEffect(() => {
    const target = shapeRadii(shape);
    if (!animated || prefersReducedMotion()) {
      radii.current = new Float32Array(target);
      writePathRef.current();
      return;
    }
    morph.current = { from: new Float32Array(radii.current), to: target, start: performance.now() };
  }, [shape, animated]);

  useEffect(() => {
    if (!animated || prefersReducedMotion()) return;
    let raf = 0;
    let last = performance.now();
    let gx = 0;
    let gy = 0;
    let tx = 0;
    let ty = 0;
    let nextGaze = 0;
    let nextBlink = last + 800 + Math.random() * 2400;
    let blinkStart = -1;

    const tick = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const m = morph.current;
      if (m) {
        const t = Math.min(1, (now - m.start) / MORPH_MS);
        const e = t >= 1 ? 1 : 1 - Math.pow(2, -10 * t);
        for (let i = 0; i < SAMPLES; i += 1) {
          radii.current[i] = m.from[i] + (m.to[i] - m.from[i]) * e;
        }
        writePathRef.current();
        if (t >= 1) morph.current = null;
      }

      const md = moodRef.current;
      const fixed = gazeRef.current;
      if (fixed) {
        tx = fixed.x;
        ty = fixed.y;
      } else if (follow && pointer.active && svgRef.current) {
        const box = svgRef.current.getBoundingClientRect();
        const dx = pointer.x - (box.left + box.width / 2);
        const dy = pointer.y - (box.top + box.height / 2);
        const dist = Math.hypot(dx, dy) || 1;
        const reach = Math.min(1, dist / 260);
        tx = (dx / dist) * reach;
        ty = (dy / dist) * reach;
      } else if (md === 'think') {
        tx = Math.sin(now / 320) * 0.9;
        ty = -0.45;
      } else if (now > nextGaze) {
        const range = GAZE_INTERVAL[md] ?? [1600, 3000];
        nextGaze = now + range[0] + Math.random() * (range[1] - range[0]);
        const wide = md === 'eval' || md === 'look';
        tx = (Math.random() * 2 - 1) * (wide ? 1 : 0.55);
        ty = (Math.random() * 2 - 1) * (wide ? 0.8 : 0.4);
      }
      const k = Math.min(1, dt * (md === 'eval' ? 18 : 9));
      gx += (tx - gx) * k;
      gy += (ty - gy) * k;

      let blink = 1;
      if (blinkStart < 0 && now > nextBlink) blinkStart = now;
      if (blinkStart >= 0) {
        const p = now - blinkStart;
        if (p < 110) blink = 1 - (p / 110) * 0.92;
        else if (p < 320) blink = 0.08 + ((p - 110) / 210) * 0.92;
        else {
          blinkStart = -1;
          nextBlink = now + 2200 + Math.random() * 3600;
        }
      }

      const ox = CENTER + gx * 7;
      const oy = eyeY + gy * 5;
      eyesRef.current?.setAttribute(
        'transform',
        `translate(${ox.toFixed(2)} ${oy.toFixed(2)}) scale(1 ${blink.toFixed(3)}) translate(${-CENTER} ${-eyeY})`,
      );
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [animated, follow, eyeY]);

  const fill = bodyColor(mood, color);
  const initialPath = radiiToPath(radii.current, BODY, CENTER, CENTER);

  return (
    <motion.div
      className={`evo-bot evo-bot--${mood} ${className ?? ''}`}
      style={{ width: size, height: size }}
      animate={moodMotion(mood)}
      transition={moodTransition(mood)}
    >
      {(mood === 'eval' || mood === 'best') && <span className="evo-bot__ring" />}
      {mood === 'best' && <span className="evo-bot__star">★</span>}
      <svg ref={svgRef} viewBox="0 0 100 100" width={size} height={size} aria-hidden="true">
        <defs>
          <linearGradient id={`g${uid}`} x1="0.2" y1="0" x2="0.8" y2="1">
            <stop offset="0" stopColor="#ffffff" stopOpacity="0.28" />
            <stop offset="0.55" stopColor="#ffffff" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path
          ref={bodyRef}
          d={initialPath}
          fill={fill}
          stroke={fill}
          strokeWidth={9}
          strokeLinejoin="round"
          style={{ transition: 'fill 300ms ease, stroke 300ms ease' }}
        />
        <path ref={shineRef} d={initialPath} fill={`url(#g${uid})`} style={{ pointerEvents: 'none' }} />
        <g ref={eyesRef}>
          <Eyes mood={mood} cx={CENTER} cy={eyeY} dx={eyeDx} />
        </g>
      </svg>
    </motion.div>
  );
}

function Eyes({ mood, cx, cy, dx }: { mood: BotMood; cx: number; cy: number; dx: number }) {
  const xs = [cx - dx, cx + dx];
  if (mood === 'fail') {
    return (
      <g stroke="#fff" strokeWidth={4} strokeLinecap="round">
        {xs.map((x) => (
          <g key={x}>
            <line x1={x - 4.5} y1={cy - 4.5} x2={x + 4.5} y2={cy + 4.5} />
            <line x1={x + 4.5} y1={cy - 4.5} x2={x - 4.5} y2={cy + 4.5} />
          </g>
        ))}
      </g>
    );
  }
  if (mood === 'happy' || mood === 'best') {
    return (
      <g stroke="#fff" strokeWidth={4.5} strokeLinecap="round" fill="none">
        {xs.map((x) => (
          <path key={x} d={`M${x - 5} ${cy + 2} Q${x} ${cy - 7} ${x + 5} ${cy + 2}`} />
        ))}
      </g>
    );
  }
  if (mood === 'pruned') {
    return (
      <g stroke="#fff" strokeWidth={4} strokeLinecap="round">
        {xs.map((x) => (
          <line key={x} x1={x - 4} y1={cy} x2={x + 4} y2={cy} />
        ))}
      </g>
    );
  }
  const tall = mood === 'asking' ? 19 : mood === 'think' ? 12 : 16;
  return (
    <g fill="#fff">
      {xs.map((x) => (
        <rect key={x} x={x - 3.6} y={cy - tall / 2} width={7.2} height={tall} rx={3.6} />
      ))}
    </g>
  );
}

function moodMotion(mood: BotMood) {
  switch (mood) {
    case 'happy':
      return { y: [0, -10, 0, -4, 0], scaleX: [1, 0.94, 1.04, 1], scaleY: [1, 1.06, 0.96, 1], rotate: 0, opacity: 1 };
    case 'best':
      return { y: [0, -12, 0], scale: [1, 1.18, 1.12], rotate: 0, opacity: 1 };
    case 'fail':
      return { y: 2, scaleX: 1.08, scaleY: 0.84, rotate: 0, opacity: 0.9 };
    case 'pruned':
      return { y: 0, scale: 0.92, rotate: 0, opacity: 0.55 };
    case 'asking':
      return { y: 0, scale: 1, rotate: -9, opacity: 1 };
    case 'talk':
      return { y: [0, -3, 0], scale: 1, rotate: 0, opacity: 1 };
    default:
      return { y: 0, scale: 1, scaleX: 1, scaleY: 1, rotate: 0, opacity: 1 };
  }
}

function moodTransition(mood: BotMood) {
  if (mood === 'talk') return { duration: 0.5, repeat: Infinity, ease: 'easeInOut' as const };
  if (mood === 'happy' || mood === 'best') return { duration: 0.7, ease: [0.16, 1, 0.3, 1] as const };
  return { type: 'spring' as const, stiffness: 260, damping: 20 };
}
