import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';

import type { DiskState, ReplayDisk } from './types';

const RACK_W = 0.62;
const RACK_H = 2.1;
const RACK_D = 1.05;
const ARC_R = 2.6;
const ARC_SPAN = (196 * Math.PI) / 180;
const CHASSIS = 5;
const BAYS = 6;
const BAY_PITCH = 0.078;
const NODE_POS = new THREE.Vector3(0, 0, 0.35);

const COLORS = {
  ok: new THREE.Color(0x19f58c),
  activity: new THREE.Color(0x4cc9ff),
  after: new THREE.Color(0x22d3ee),
  before: new THREE.Color(0xffa62b),
  failed: new THREE.Color(0xff2a3d),
  off: new THREE.Color(0x000000),
  caddy: new THREE.Color(0x2a3242),
  caddyFailed: new THREE.Color(0x5a1018),
};

interface Packet {
  mesh: THREE.Mesh;
  curve: THREE.QuadraticBezierCurve3 | null;
  t: number;
  speed: number;
}

interface CameraTween {
  fromPos: THREE.Vector3;
  toPos: THREE.Vector3;
  fromTarget: THREE.Vector3;
  toTarget: THREE.Vector3;
  t: number;
  duration: number;
}

function easeInOut(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

function textSprite(text: string, color = '#9fdcff', size = 64, bg = 'rgba(8,16,30,0.0)'): THREE.Sprite {
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d')!;
  ctx.font = `600 ${size}px "Segoe UI", "PingFang SC", "Noto Sans CJK SC", sans-serif`;
  const w = Math.ceil(ctx.measureText(text).width) + size;
  canvas.width = w;
  canvas.height = Math.ceil(size * 1.6);
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.font = `600 ${size}px "Segoe UI", "PingFang SC", "Noto Sans CJK SC", sans-serif`;
  ctx.fillStyle = color;
  ctx.textBaseline = 'middle';
  ctx.fillText(text, size / 2, canvas.height / 2);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }));
  const scale = 0.0032;
  sprite.scale.set(canvas.width * scale, canvas.height * scale, 1);
  return sprite;
}

function floorTexture(): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = c.height = 256;
  const g = c.getContext('2d')!;
  g.fillStyle = '#0b111c';
  g.fillRect(0, 0, 256, 256);
  g.strokeStyle = '#1a2638';
  g.lineWidth = 3;
  g.strokeRect(1.5, 1.5, 253, 253);
  g.strokeStyle = 'rgba(80,140,220,0.08)';
  g.lineWidth = 1;
  g.strokeRect(10, 10, 236, 236);
  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(36, 36);
  tex.anisotropy = 4;
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function ventTexture(): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d')!;
  g.fillStyle = '#000';
  g.fillRect(0, 0, 128, 128);
  g.fillStyle = '#3aa8ff';
  for (let y = 8; y < 128; y += 12) for (let x = 8; x < 128; x += 12) g.fillRect(x, y, 4, 4);
  g.strokeStyle = '#2b7fd0';
  g.lineWidth = 2;
  g.strokeRect(1, 1, 126, 126);
  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function screenTexture(): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = 512;
  c.height = 320;
  const g = c.getContext('2d')!;
  const grad = g.createLinearGradient(0, 0, 512, 320);
  grad.addColorStop(0, '#062038');
  grad.addColorStop(1, '#0b3a5c');
  g.fillStyle = grad;
  g.fillRect(0, 0, 512, 320);
  g.fillStyle = '#5fe3ff';
  g.font = '600 34px "Segoe UI", sans-serif';
  g.fillText('FaultEvolve · LOCAL EVAL', 28, 60);
  g.fillStyle = '#9ad8ff';
  g.font = '24px "Segoe UI", sans-serif';
  g.fillText('evaluator.py  ·  GPU bootstrap', 28, 104);
  for (let i = 0; i < 14; i += 1) {
    const h = 30 + Math.abs(Math.sin(i * 1.7)) * 120;
    g.fillStyle = i % 3 === 0 ? '#22d3ee' : '#1b6fa8';
    g.fillRect(32 + i * 32, 290 - h, 20, h);
  }
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

export class DataHall {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly camera: THREE.PerspectiveCamera;
  readonly controls: OrbitControls;
  onPick: ((index: number) => void) | null = null;

  private composer: EffectComposer;
  private bloom: UnrealBloomPass;
  private clock = new THREE.Clock();
  private disks: ReplayDisk[];
  private index = new Map<string, number>();
  private states: DiskState[];
  private pullOut: Float32Array;
  private blinkPhase: Float32Array;
  private failedAt: Float32Array;
  private caddies!: THREE.InstancedMesh;
  private leds!: THREE.InstancedMesh;
  private halos!: THREE.InstancedMesh;
  private rackBars: THREE.Mesh[] = [];
  private rackMatrices: THREE.Matrix4[] = [];
  private bayLocal: THREE.Vector3[] = [];
  private packets: Packet[] = [];
  private air!: THREE.Points;
  private airSpeed!: Float32Array;
  private nodeRing!: THREE.Mesh;
  private nodeRing2!: THREE.Mesh;
  private nodeBeam!: THREE.Mesh;
  private alertLight: THREE.PointLight;
  private alertIndex = -1;
  private tween: CameraTween | null = null;
  private returnTimer: number | null = null;
  private idleSince = 0;
  private swayT0 = -1;
  private scratch = new THREE.Matrix4();
  private tmpColor = new THREE.Color();
  private raycaster = new THREE.Raycaster();
  private readonly overviewPos = new THREE.Vector3(0, 3.7, 5.0);
  private readonly overviewTarget = new THREE.Vector3(0, 0.85, -0.75);

  constructor(canvas: HTMLCanvasElement, disks: ReplayDisk[]) {
    this.disks = disks;
    disks.forEach((d, i) => this.index.set(d.sn, i));
    this.states = disks.map(() => 'ok');
    this.pullOut = new Float32Array(disks.length);
    this.failedAt = new Float32Array(disks.length).fill(-1);
    this.blinkPhase = new Float32Array(disks.length).map(() => Math.random() * Math.PI * 2);

    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.6));
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;

    this.scene.background = new THREE.Color(0x04070d);
    this.scene.fog = new THREE.FogExp2(0x04070d, 0.075);
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

    this.camera = new THREE.PerspectiveCamera(42, 1, 0.05, 80);
    this.camera.position.copy(this.overviewPos);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.target.copy(this.overviewTarget);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.maxPolarAngle = Math.PI * 0.48;
    this.controls.minDistance = 0.6;
    this.controls.maxDistance = 14;
    this.controls.addEventListener('start', () => {
      this.tween = null;
      this.idleSince = performance.now();
      this.swayT0 = -1;
    });

    this.buildLights();
    this.buildRoom();
    this.buildRacks();
    this.buildBays();
    this.buildAir();
    this.buildEdgeNode();
    this.buildPackets();

    this.alertLight = new THREE.PointLight(0xff2a3d, 0, 2.4, 1.6);
    this.scene.add(this.alertLight);

    this.composer = new EffectComposer(this.renderer);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    this.bloom = new UnrealBloomPass(new THREE.Vector2(512, 512), 0.95, 0.55, 0.62);
    this.composer.addPass(this.bloom);
    this.composer.addPass(new OutputPass());

    canvas.addEventListener('pointerup', (e) => this.pick(e));
    window.addEventListener('resize', () => this.resize());
    this.resize();
    this.idleSince = performance.now();
    this.renderer.setAnimationLoop(() => this.frame());
  }

  // ------------------------------------------------------------------ build
  private buildLights(): void {
    this.scene.add(new THREE.HemisphereLight(0x8fb8ff, 0x05070c, 0.35));
    const key = new THREE.DirectionalLight(0xbcd7ff, 0.9);
    key.position.set(3, 6, 4);
    this.scene.add(key);
    const aisle = new THREE.SpotLight(0x7fc4ff, 7, 10, Math.PI / 4, 0.6, 1.3);
    aisle.position.set(0, 4.2, -0.2);
    aisle.target.position.set(0, 0, -0.9);
    this.scene.add(aisle, aisle.target);
  }

  /** Flat arc lying in the XZ plane, following the rack ring (angle 0 = straight behind the node). */
  private arcGeometry(inner: number, outer: number, span: number): THREE.BufferGeometry {
    const geo = new THREE.RingGeometry(inner, outer, 96, 1, Math.PI / 2 - span / 2, span);
    geo.rotateX(-Math.PI / 2);
    return geo;
  }

  private buildRoom(): void {
    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(40, 40),
      new THREE.MeshStandardMaterial({ map: floorTexture(), color: 0x9fb2cc, metalness: 0.75, roughness: 0.28, envMapIntensity: 0.6 }),
    );
    floor.rotation.x = -Math.PI / 2;
    this.scene.add(floor);

    const vent = ventTexture();
    vent.repeat.set(7, 7);
    const vents = new THREE.Mesh(
      new THREE.CircleGeometry(ARC_R - RACK_D / 2 - 0.15, 72),
      new THREE.MeshBasicMaterial({ map: vent, transparent: true, opacity: 0.4, blending: THREE.AdditiveBlending, depthWrite: false }),
    );
    vents.rotation.x = -Math.PI / 2;
    vents.position.set(0, 0.004, 0);
    this.scene.add(vents);

    const stripMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(0xbfe6ff).multiplyScalar(2.2), toneMapped: false, side: THREE.DoubleSide });
    const trayMat = new THREE.MeshStandardMaterial({ color: 0xd99a2b, metalness: 0.6, roughness: 0.45, side: THREE.DoubleSide });
    const strip = new THREE.Mesh(this.arcGeometry(ARC_R * 0.62 - 0.02, ARC_R * 0.62 + 0.02, ARC_SPAN), stripMat);
    strip.position.y = 3.15;
    const tray = new THREE.Mesh(this.arcGeometry(ARC_R - 0.17, ARC_R + 0.17, ARC_SPAN * 1.08), trayMat);
    tray.position.y = 2.45;
    this.scene.add(strip, tray);
    const cableGeo = new THREE.BoxGeometry(0.3, 0.05, 0.015);
    for (let i = 0; i < 40; i += 1) {
      const a = -ARC_SPAN * 0.52 + (i / 39) * ARC_SPAN * 1.04;
      const cable = new THREE.Mesh(cableGeo, new THREE.MeshStandardMaterial({ color: i % 4 === 0 ? 0x2f7bff : 0x1a1f2b, roughness: 0.7 }));
      cable.position.set(ARC_R * Math.sin(a), 2.5, -ARC_R * Math.cos(a));
      cable.rotation.y = -a;
      this.scene.add(cable);
    }
    const floorGlow = new THREE.Mesh(
      new THREE.RingGeometry(0.55, 0.62, 64),
      new THREE.MeshBasicMaterial({ color: new THREE.Color(0x22d3ee).multiplyScalar(1.6), toneMapped: false, transparent: true, opacity: 0.8 }),
    );
    floorGlow.rotation.x = -Math.PI / 2;
    floorGlow.position.set(NODE_POS.x, 0.005, NODE_POS.z);
    this.scene.add(floorGlow);
  }

  /** Racks stand on an arc around the edge node, drive fronts facing inward. */
  private rackMatrix(rack: number, count: number): THREE.Matrix4 {
    const a = -ARC_SPAN / 2 + (count > 1 ? rack / (count - 1) : 0.5) * ARC_SPAN;
    const m = new THREE.Matrix4().makeRotationY(-a);
    m.setPosition(ARC_R * Math.sin(a), 0, -ARC_R * Math.cos(a));
    return m;
  }

  private buildRacks(): void {
    const body = new THREE.MeshStandardMaterial({ color: 0x141a26, metalness: 0.85, roughness: 0.38 });
    const post = new THREE.MeshStandardMaterial({ color: 0x232c3d, metalness: 0.9, roughness: 0.3 });
    const glass = new THREE.MeshPhysicalMaterial({
      color: 0x8fb6ff, metalness: 0, roughness: 0.06, transparent: true, opacity: 0.1, depthWrite: false,
    });
    const edgeMat = new THREE.LineBasicMaterial({ color: 0x2c6fb0, transparent: true, opacity: 0.55 });
    const faceplate = new THREE.MeshStandardMaterial({ color: 0x1c2331, metalness: 0.8, roughness: 0.42 });
    const rackCount = Math.max(...this.disks.map((d) => d.rack)) + 1;

    for (let r = 0; r < rackCount; r += 1) {
      const m = this.rackMatrix(r, rackCount);
      this.rackMatrices.push(m);
      const g = new THREE.Group();
      g.applyMatrix4(m);
      const parts: Array<[number, number, number, number, number, number, THREE.Material]> = [
        [0.03, RACK_H, RACK_D, -RACK_W / 2 + 0.015, RACK_H / 2, 0, body],
        [0.03, RACK_H, RACK_D, RACK_W / 2 - 0.015, RACK_H / 2, 0, body],
        [RACK_W, 0.04, RACK_D, 0, RACK_H - 0.02, 0, body],
        [RACK_W, 0.08, RACK_D, 0, 0.04, 0, body],
        [RACK_W, RACK_H, 0.02, 0, RACK_H / 2, -RACK_D / 2 + 0.01, body],
        [0.04, RACK_H, 0.04, -RACK_W / 2 + 0.05, RACK_H / 2, RACK_D / 2 - 0.03, post],
        [0.04, RACK_H, 0.04, RACK_W / 2 - 0.05, RACK_H / 2, RACK_D / 2 - 0.03, post],
      ];
      for (const [w, h, d, x, y, z, mat] of parts) {
        const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
        mesh.position.set(x, y, z);
        g.add(mesh);
      }
      for (let k = 0; k < CHASSIS; k += 1) {
        const plate = new THREE.Mesh(new THREE.BoxGeometry(RACK_W - 0.1, 0.205, 0.02), faceplate);
        plate.position.set(0, this.chassisY(k), RACK_D / 2 - 0.035);
        g.add(plate);
        const ear = new THREE.Mesh(
          new THREE.BoxGeometry(0.014, 0.012, 0.005),
          new THREE.MeshBasicMaterial({ color: new THREE.Color(0x4cc9ff).multiplyScalar(2), toneMapped: false }),
        );
        ear.position.set(RACK_W / 2 - 0.085, this.chassisY(k) + 0.08, RACK_D / 2 - 0.022);
        g.add(ear);
      }
      const door = new THREE.Mesh(new THREE.PlaneGeometry(RACK_W - 0.02, RACK_H - 0.06), glass);
      door.position.set(0, RACK_H / 2, RACK_D / 2 + 0.012);
      g.add(door);
      const frame = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(RACK_W, RACK_H, RACK_D)), edgeMat);
      frame.position.set(0, RACK_H / 2, 0);
      g.add(frame);
      const bar = new THREE.Mesh(
        new THREE.BoxGeometry(RACK_W - 0.06, 0.018, 0.012),
        new THREE.MeshBasicMaterial({ color: COLORS.ok.clone().multiplyScalar(1.6), toneMapped: false }),
      );
      bar.position.set(0, RACK_H - 0.07, RACK_D / 2 + 0.016);
      g.add(bar);
      this.rackBars.push(bar);
      const label = textSprite(`R${String(r + 1).padStart(2, '0')}`, '#8fd3ff', 56);
      label.position.set(0, RACK_H + 0.16, RACK_D / 2);
      g.add(label);
      this.scene.add(g);
    }
  }

  private chassisY(k: number): number {
    return 1.78 - k * 0.33;
  }

  private buildBays(): void {
    const n = this.disks.length;
    this.caddies = new THREE.InstancedMesh(
      new THREE.BoxGeometry(0.068, 0.17, 0.035),
      new THREE.MeshStandardMaterial({ metalness: 0.7, roughness: 0.35 }),
      n,
    );
    this.leds = new THREE.InstancedMesh(
      new THREE.BoxGeometry(0.014, 0.014, 0.006),
      new THREE.MeshBasicMaterial({ toneMapped: false }),
      n,
    );
    this.halos = new THREE.InstancedMesh(
      new THREE.BoxGeometry(0.084, 0.188, 0.004),
      new THREE.MeshBasicMaterial({ toneMapped: false, transparent: true, opacity: 0.95 }),
      n,
    );
    for (let s = 0; s < CHASSIS * BAYS; s += 1) {
      const k = Math.floor(s / BAYS);
      const j = s % BAYS;
      this.bayLocal.push(new THREE.Vector3((j - (BAYS - 1) / 2) * BAY_PITCH - 0.03, this.chassisY(k), RACK_D / 2 - 0.005));
    }
    for (let i = 0; i < n; i += 1) {
      this.caddies.setColorAt(i, COLORS.caddy);
      this.leds.setColorAt(i, COLORS.ok);
      this.halos.setColorAt(i, COLORS.off);
    }
    this.updateBayMatrices();
    this.scene.add(this.caddies, this.leds, this.halos);
  }

  private bayMatrix(i: number, local: THREE.Vector3, out: THREE.Matrix4): THREE.Matrix4 {
    const d = this.disks[i];
    const pos = this.bayLocal[d.slot % this.bayLocal.length];
    out.makeTranslation(pos.x + local.x, pos.y + local.y, pos.z + local.z + this.pullOut[i]);
    return out.premultiply(this.rackMatrices[d.rack]);
  }

  private updateBayMatrices(): void {
    const zero = new THREE.Vector3();
    const led = new THREE.Vector3(0.0, -0.064, 0.019);
    const halo = new THREE.Vector3(0, 0, -0.016);
    const hidden = new THREE.Matrix4().makeScale(0, 0, 0);
    for (let i = 0; i < this.disks.length; i += 1) {
      this.caddies.setMatrixAt(i, this.bayMatrix(i, zero, this.scratch));
      this.leds.setMatrixAt(i, this.bayMatrix(i, led, this.scratch));
      if (this.states[i] === 'ok') this.halos.setMatrixAt(i, hidden);
      else this.halos.setMatrixAt(i, this.bayMatrix(i, halo, this.scratch));
    }
    this.caddies.instanceMatrix.needsUpdate = true;
    this.leds.instanceMatrix.needsUpdate = true;
    this.halos.instanceMatrix.needsUpdate = true;
  }

  private buildAir(): void {
    const count = 700;
    const reach = ARC_R - RACK_D / 2 - 0.1;
    const pos = new Float32Array(count * 3);
    this.airSpeed = new Float32Array(count);
    for (let i = 0; i < count; i += 1) {
      const r = Math.sqrt(Math.random()) * reach;
      const a = Math.random() * Math.PI * 2;
      pos[i * 3] = r * Math.sin(a);
      pos[i * 3 + 1] = Math.random() * 2.4;
      pos[i * 3 + 2] = -r * Math.cos(a);
      this.airSpeed[i] = 0.12 + Math.random() * 0.25;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    this.air = new THREE.Points(
      geo,
      new THREE.PointsMaterial({ color: 0x5fb6ff, size: 0.018, transparent: true, opacity: 0.55, blending: THREE.AdditiveBlending, depthWrite: false }),
    );
    this.scene.add(this.air);
  }

  private buildEdgeNode(): void {
    const g = new THREE.Group();
    g.position.copy(NODE_POS);
    const pedestal = new THREE.Mesh(
      new THREE.CylinderGeometry(0.42, 0.48, 0.75, 6),
      new THREE.MeshStandardMaterial({ color: 0x111827, metalness: 0.85, roughness: 0.3 }),
    );
    pedestal.position.y = 0.375;
    g.add(pedestal);
    const base = new THREE.Mesh(
      new THREE.BoxGeometry(0.5, 0.025, 0.34),
      new THREE.MeshStandardMaterial({ color: 0x9aa4b5, metalness: 0.9, roughness: 0.25 }),
    );
    base.position.set(0, 0.765, 0.04);
    g.add(base);
    const screen = new THREE.Mesh(
      new THREE.PlaneGeometry(0.48, 0.3),
      new THREE.MeshBasicMaterial({ map: screenTexture(), toneMapped: false }),
    );
    screen.position.set(0, 0.93, -0.12);
    screen.rotation.x = -0.18;
    screen.rotation.y = 0;
    g.add(screen);

    const ringMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(0x22d3ee).multiplyScalar(2.2), toneMapped: false });
    this.nodeRing = new THREE.Mesh(new THREE.TorusGeometry(0.55, 0.012, 8, 6), ringMat);
    this.nodeRing.rotation.x = Math.PI / 2;
    this.nodeRing.position.set(NODE_POS.x, 1.25, NODE_POS.z);
    this.nodeRing2 = new THREE.Mesh(new THREE.TorusGeometry(0.4, 0.008, 8, 64), ringMat);
    this.nodeRing2.rotation.x = Math.PI / 2;
    this.nodeRing2.position.set(NODE_POS.x, 1.45, NODE_POS.z);
    this.nodeBeam = new THREE.Mesh(
      new THREE.CylinderGeometry(0.05, 0.22, 2.6, 24, 1, true),
      new THREE.MeshBasicMaterial({ color: 0x22d3ee, transparent: true, opacity: 0.12, blending: THREE.AdditiveBlending, side: THREE.DoubleSide, depthWrite: false }),
    );
    this.nodeBeam.position.set(NODE_POS.x, 1.3, NODE_POS.z);
    const label = textSprite('本地评估域 · 笔记本', '#7ee8ff', 40);
    label.position.set(NODE_POS.x, 1.78, NODE_POS.z);
    const sub = textSprite('数据不出域', '#ffd28a', 30);
    sub.position.set(NODE_POS.x, 1.66, NODE_POS.z);
    this.scene.add(g, this.nodeRing, this.nodeRing2, this.nodeBeam, label, sub);
  }

  private buildPackets(): void {
    const geo = new THREE.SphereGeometry(0.022, 10, 10);
    for (let i = 0; i < 160; i += 1) {
      const mesh = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: COLORS.activity.clone().multiplyScalar(2.5), toneMapped: false }));
      mesh.visible = false;
      this.scene.add(mesh);
      this.packets.push({ mesh, curve: null, t: 0, speed: 1 });
    }
  }

  // ----------------------------------------------------------------- public
  diskIndex(sn: string): number {
    return this.index.get(sn) ?? -1;
  }

  diskWorldPosition(i: number): THREE.Vector3 {
    return new THREE.Vector3().setFromMatrixPosition(this.bayMatrix(i, new THREE.Vector3(), new THREE.Matrix4()));
  }

  private diskNormal(i: number): THREE.Vector3 {
    return new THREE.Vector3(0, 0, 1).transformDirection(this.rackMatrices[this.disks[i].rack]);
  }

  setState(i: number, state: DiskState): void {
    if (i < 0) return;
    this.states[i] = state;
    const halo = state === 'failed' ? COLORS.failed : state === 'alarm-before' ? COLORS.before : state === 'ok' ? COLORS.off : COLORS.after;
    this.halos.setColorAt(i, this.tmpColor.copy(halo).multiplyScalar(state === 'failed' ? 2.4 : 1.8));
    this.caddies.setColorAt(i, state === 'failed' ? COLORS.caddyFailed : COLORS.caddy);
    this.halos.instanceColor!.needsUpdate = true;
    this.caddies.instanceColor!.needsUpdate = true;
    this.updateBayMatrices();
    this.refreshRackBars();
  }

  resetAll(): void {
    for (let i = 0; i < this.disks.length; i += 1) {
      this.states[i] = 'ok';
      this.pullOut[i] = 0;
      this.failedAt[i] = -1;
      this.halos.setColorAt(i, COLORS.off);
      this.caddies.setColorAt(i, COLORS.caddy);
    }
    this.halos.instanceColor!.needsUpdate = true;
    this.caddies.instanceColor!.needsUpdate = true;
    this.alertIndex = -1;
    this.alertLight.intensity = 0;
    this.updateBayMatrices();
    this.refreshRackBars();
    this.overview();
  }

  fail(i: number): void {
    if (i < 0) return;
    this.failedAt[i] = this.clock.elapsedTime;
    this.alertIndex = i;
    this.setState(i, 'failed');
    this.alertLight.position.copy(this.diskWorldPosition(i)).add(this.diskNormal(i).multiplyScalar(0.25));
    this.focus(i);
  }

  uplink(count: number): void {
    const racks = this.rackMatrices.length;
    for (let k = 0; k < count; k += 1) {
      const r = Math.floor(Math.random() * racks);
      const from = new THREE.Vector3(0, RACK_H + 0.02, 0).applyMatrix4(this.rackMatrices[r]);
      from.x += (Math.random() - 0.5) * 0.4;
      const to = new THREE.Vector3(NODE_POS.x, 1.25, NODE_POS.z);
      const mid = from.clone().lerp(to, 0.5);
      mid.y = 2.9 + Math.random() * 0.4;
      this.launch(new THREE.QuadraticBezierCurve3(from, mid, to), COLORS.activity, 0.55 + Math.random() * 0.3, k * 0.04);
    }
  }

  downlink(indices: number[], color: 'after' | 'before'): void {
    indices.forEach((i, k) => {
      const from = new THREE.Vector3(NODE_POS.x, 1.25, NODE_POS.z);
      const to = this.diskWorldPosition(i).add(this.diskNormal(i).multiplyScalar(0.05));
      const mid = from.clone().lerp(to, 0.5);
      mid.y = 3.0;
      this.launch(new THREE.QuadraticBezierCurve3(from, mid, to), COLORS[color], 0.45, k * 0.06);
    });
  }

  private launch(curve: THREE.QuadraticBezierCurve3, color: THREE.Color, speed: number, delay: number): void {
    const p = this.packets.find((x) => x.curve === null);
    if (!p) return;
    p.curve = curve;
    p.t = -delay * speed;
    p.speed = speed;
    (p.mesh.material as THREE.MeshBasicMaterial).color.copy(color).multiplyScalar(2.5);
  }

  focus(i: number): void {
    const p = this.diskWorldPosition(i);
    const n = this.diskNormal(i);
    const camPos = p.clone().add(n.multiplyScalar(1.25)).add(new THREE.Vector3(0.45, 0.25, 0));
    this.tweenTo(camPos, p, 1.6);
    this.swayT0 = -1;
    if (this.returnTimer !== null) window.clearTimeout(this.returnTimer);
    this.returnTimer = window.setTimeout(() => {
      this.returnTimer = null;
      this.overview();
    }, 5200);
  }

  overview(): void {
    this.tweenTo(this.overviewPos.clone(), this.overviewTarget.clone(), 2.0);
    this.idleSince = performance.now();
  }

  private tweenTo(pos: THREE.Vector3, target: THREE.Vector3, duration: number): void {
    this.tween = {
      fromPos: this.camera.position.clone(),
      toPos: pos,
      fromTarget: this.controls.target.clone(),
      toTarget: target,
      t: 0,
      duration,
    };
  }

  private refreshRackBars(): void {
    this.rackBars.forEach((bar, r) => {
      let color = COLORS.ok;
      for (let i = 0; i < this.disks.length; i += 1) {
        if (this.disks[i].rack !== r) continue;
        if (this.states[i] === 'failed') {
          color = COLORS.failed;
          break;
        }
        if (this.states[i] !== 'ok') color = COLORS.after;
      }
      (bar.material as THREE.MeshBasicMaterial).color.copy(color).multiplyScalar(1.6);
    });
  }

  private pick(e: PointerEvent): void {
    if (!this.onPick) return;
    const rect = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(ndc, this.camera);
    const hit = this.raycaster.intersectObject(this.caddies, false)[0];
    if (hit && hit.instanceId !== undefined) this.onPick(hit.instanceId);
  }

  private resize(): void {
    const w = window.innerWidth;
    const h = window.innerHeight;
    this.renderer.setSize(w, h, false);
    this.composer.setSize(w, h);
    this.bloom.resolution.set(w / 2, h / 2);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  // ------------------------------------------------------------------ frame
  private frame(): void {
    const dt = Math.min(this.clock.getDelta(), 0.05);
    const t = this.clock.elapsedTime;

    if (this.tween) {
      const tw = this.tween;
      tw.t += dt / tw.duration;
      const k = easeInOut(Math.min(tw.t, 1));
      this.camera.position.lerpVectors(tw.fromPos, tw.toPos, k);
      this.controls.target.lerpVectors(tw.fromTarget, tw.toTarget, k);
      if (tw.t >= 1) this.tween = null;
    } else if (performance.now() - this.idleSince > 9000 && this.returnTimer === null) {
      if (this.swayT0 < 0) {
        this.swayT0 = t + 2.0;
        this.tweenTo(this.overviewPos.clone(), this.overviewTarget.clone(), 2.0);
      } else {
        const s = t - this.swayT0;
        const k = Math.min(1, Math.max(0, s / 5));
        this.camera.position.set(
          this.overviewPos.x + k * Math.sin(s * 0.13) * 1.1,
          this.overviewPos.y + k * Math.sin(s * 0.21) * 0.2,
          this.overviewPos.z - k * (1 - Math.cos(s * 0.16)) * 0.45,
        );
        this.controls.target.copy(this.overviewTarget);
      }
    }

    let moved = false;
    for (let i = 0; i < this.disks.length; i += 1) {
      const state = this.states[i];
      let target = 0;
      if (state === 'failed') target = 0.09;
      if (Math.abs(this.pullOut[i] - target) > 1e-4) {
        this.pullOut[i] += (target - this.pullOut[i]) * Math.min(1, dt * 3);
        moved = true;
      }
      let color: THREE.Color;
      let intensity: number;
      if (state === 'failed') {
        color = COLORS.failed;
        intensity = 1.6 + 1.4 * Math.sin(t * 9);
      } else if (state === 'ok') {
        const blink = Math.sin(t * (5 + (i % 7)) + this.blinkPhase[i]) > 0.55;
        color = blink ? COLORS.activity : COLORS.ok;
        intensity = blink ? 2.4 : 1.1;
      } else {
        color = state === 'alarm-before' || state === 'alarm-both' ? COLORS.before : COLORS.after;
        intensity = 1.6 + 0.9 * Math.sin(t * 4 + this.blinkPhase[i]);
      }
      this.leds.setColorAt(i, this.tmpColor.copy(color).multiplyScalar(intensity));
    }
    this.leds.instanceColor!.needsUpdate = true;
    if (moved) this.updateBayMatrices();

    if (this.alertIndex >= 0) this.alertLight.intensity = 2.2 + 1.8 * Math.sin(t * 9);

    const pos = this.air.geometry.getAttribute('position') as THREE.BufferAttribute;
    for (let i = 0; i < pos.count; i += 1) {
      let y = pos.getY(i) + this.airSpeed[i] * dt;
      if (y > 2.6) y = 0;
      pos.setY(i, y);
    }
    pos.needsUpdate = true;

    this.nodeRing.rotation.z += dt * 0.6;
    this.nodeRing2.rotation.z -= dt * 1.1;
    (this.nodeBeam.material as THREE.MeshBasicMaterial).opacity = 0.1 + 0.05 * Math.sin(t * 2.2);

    for (const p of this.packets) {
      if (!p.curve) continue;
      p.t += dt * p.speed;
      if (p.t < 0) {
        p.mesh.visible = false;
        continue;
      }
      if (p.t >= 1) {
        p.curve = null;
        p.mesh.visible = false;
        continue;
      }
      p.mesh.visible = true;
      p.curve.getPoint(p.t, p.mesh.position);
    }

    this.controls.update();
    this.composer.render();
  }
}
