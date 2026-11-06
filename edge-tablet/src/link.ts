/**
 * Uplink to the laptop's local evaluation domain (`/api/edge/ws`).
 * Reconnects on its own; every frame sent is counted for the HUD.
 */

export type LinkStatus = 'offline' | 'connecting' | 'online';

export interface LinkMessage {
  type: string;
  [key: string]: unknown;
}

const STORAGE_KEY = 'fe-edge-endpoint';

export function defaultEndpoint(): string {
  const params = new URLSearchParams(location.search);
  const fromQuery = params.get('server');
  if (fromQuery) return normalize(fromQuery);
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) return saved;
  // Served by the laptop itself (http://<laptop>:8011/edge-tablet/): reuse that host.
  if (location.protocol.startsWith('http') && location.hostname !== 'localhost' && location.port) {
    return `ws://${location.host}/api/edge/ws`;
  }
  const baked = import.meta.env.VITE_EDGE_SERVER as string | undefined;
  return baked ? normalize(baked) : '';
}

export function normalize(input: string): string {
  let value = input.trim();
  if (!value) return '';
  if (!/^wss?:\/\//.test(value)) value = `ws://${value}`;
  const url = new URL(value.replace(/^ws/, 'http'));
  if (!url.port) url.port = '8011';
  if (url.pathname === '/' || url.pathname === '') url.pathname = '/api/edge/ws';
  return url.toString().replace(/^http/, 'ws').replace(/\/$/, '');
}

export class Uplink {
  status: LinkStatus = 'offline';
  endpoint: string;
  sentFrames = 0;
  sentBytes = 0;
  lastRttMs: number | null = null;
  private ws: WebSocket | null = null;
  private retry: number | null = null;
  private pendingPing = 0;

  constructor(
    private readonly onMessage: (msg: LinkMessage) => void,
    private readonly onStatus: (status: LinkStatus) => void,
  ) {
    this.endpoint = defaultEndpoint();
  }

  setEndpoint(raw: string): void {
    this.endpoint = normalize(raw);
    localStorage.setItem(STORAGE_KEY, this.endpoint);
    this.disconnect();
    this.connect();
  }

  connect(): void {
    if (!this.endpoint || this.ws) return;
    this.setStatus('connecting');
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.endpoint);
    } catch {
      this.scheduleRetry();
      return;
    }
    this.ws = ws;
    ws.onopen = () => this.setStatus('online');
    ws.onmessage = (event) => {
      let msg: LinkMessage;
      try {
        msg = JSON.parse(String(event.data)) as LinkMessage;
      } catch {
        return;
      }
      // Only replies time the link; laptop-initiated pushes arrive whenever the evolution needs them.
      if (this.pendingPing && msg.type === 'ack') {
        this.lastRttMs = performance.now() - this.pendingPing;
        this.pendingPing = 0;
      }
      this.onMessage(msg);
    };
    ws.onclose = () => {
      this.ws = null;
      this.setStatus('offline');
      this.scheduleRetry();
    };
    ws.onerror = () => ws.close();
  }

  disconnect(): void {
    if (this.retry !== null) window.clearTimeout(this.retry);
    this.retry = null;
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
    this.setStatus('offline');
  }

  send(msg: LinkMessage): number {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return 0;
    const raw = JSON.stringify(msg);
    this.ws.send(raw);
    this.sentFrames += 1;
    const bytes = new Blob([raw]).size;
    this.sentBytes += bytes;
    this.pendingPing = performance.now();
    return bytes;
  }

  private scheduleRetry(): void {
    if (this.retry !== null || !this.endpoint) return;
    this.retry = window.setTimeout(() => {
      this.retry = null;
      this.connect();
    }, 2500);
  }

  private setStatus(status: LinkStatus): void {
    this.status = status;
    this.onStatus(status);
  }
}
