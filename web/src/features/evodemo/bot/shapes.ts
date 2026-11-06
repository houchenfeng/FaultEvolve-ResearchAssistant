/**
 * EvoBot 的几何形状。
 *
 * 每个形状都表示成极坐标半径数组 r(θ)：同一组角度采样，形变只需逐点插值，
 * 不需要对齐顶点。多边形的圆角由渲染时同色粗描边 + round join 得到。
 * 角度在 SVG 坐标系下（y 向下），所以 -π/2 是正上方。
 */

export type BotShape = 'circle' | 'squircle' | 'hex' | 'diamond' | 'triangle';

export const SAMPLES = 72;

const TAU = Math.PI * 2;

function polygonRadius(theta: number, sides: number, rotation: number): number {
  const apothem = Math.cos(Math.PI / sides);
  const sector = TAU / sides;
  const local = ((((theta - rotation) % sector) + sector) % sector) - sector / 2;
  return apothem / Math.cos(local);
}

function squircleRadius(theta: number): number {
  const c = Math.abs(Math.cos(theta));
  const s = Math.abs(Math.sin(theta));
  return 1 / Math.pow(Math.pow(c, 4) + Math.pow(s, 4), 1 / 4);
}

function radiusAt(shape: BotShape, theta: number): number {
  switch (shape) {
    case 'circle':
      return 1;
    case 'squircle':
      return squircleRadius(theta) * 0.9;
    case 'hex':
      return polygonRadius(theta, 6, 0) * 1.02;
    case 'diamond':
      return polygonRadius(theta, 4, 0) * 1.08;
    case 'triangle':
      return polygonRadius(theta, 3, -Math.PI / 2) * 1.16;
  }
}

const cache = new Map<BotShape, Float32Array>();

export function shapeRadii(shape: BotShape): Float32Array {
  const hit = cache.get(shape);
  if (hit) return hit;
  const out = new Float32Array(SAMPLES);
  for (let i = 0; i < SAMPLES; i += 1) {
    out[i] = radiusAt(shape, (i / SAMPLES) * TAU);
  }
  cache.set(shape, out);
  return out;
}

export function radiiToPath(radii: Float32Array, scale: number, cx: number, cy: number): string {
  let d = '';
  for (let i = 0; i < SAMPLES; i += 1) {
    const theta = (i / SAMPLES) * TAU;
    const x = cx + Math.cos(theta) * radii[i] * scale;
    const y = cy + Math.sin(theta) * radii[i] * scale;
    d += `${i === 0 ? 'M' : 'L'}${x.toFixed(2)} ${y.toFixed(2)}`;
  }
  return `${d}Z`;
}

/** 脸在形状里的位置修正：三角形重心偏下，眼睛跟着下移。 */
export const FACE_OFFSET: Record<BotShape, { dy: number; spread: number }> = {
  circle: { dy: -0.04, spread: 1 },
  squircle: { dy: -0.04, spread: 1.05 },
  hex: { dy: -0.02, spread: 1 },
  diamond: { dy: 0, spread: 0.85 },
  triangle: { dy: 0.22, spread: 0.8 },
};

export const ISLAND_SHAPE = {
  temporal: 'circle',
  ensemble: 'hex',
  operations: 'diamond',
} as const satisfies Record<string, BotShape>;
