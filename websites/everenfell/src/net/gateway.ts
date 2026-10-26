/** WebSocket gateway client: the browser's only link to the game world.

Owns connection state, reconnect with backoff, request/response
matching by seq, and broadcast dispatch. Views never touch sockets;
they call request() and subscribe to pushes. No gameplay logic lives
here — the server validates every input and the client renders only
validated results.
*/
import type { GatewayOp, GatewayRequest, GatewayResponse } from './protocol';

type PushHandler = (body: Record<string, unknown>) => void;

interface Pending {
  resolve: (body: Record<string, unknown>) => void;
  reject: (err: Error) => void;
}

export interface GatewayOptions {
  url: string;
  maxBackoffMs?: number;
}

export class Gateway {
  private socket: WebSocket | null = null;
  private seq = 0;
  private pending = new Map<number, Pending>();
  private pushes = new Map<string, Set<PushHandler>>();
  private backoffMs = 1000;
  private wanted = false;

  constructor(private readonly options: GatewayOptions) {}

  get connected(): boolean {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  /** Open the connection; resolves on first open, reconnects on drops. */
  connect(): Promise<void> {
    this.wanted = true;
    return new Promise((resolve, reject) => {
      let settled = false;
      const open = () => {
        if (!this.socket) return;
        this.socket.onmessage = (event) => this.onMessage(event);
        this.socket.onclose = () => this.onClose();
        this.socket.onerror = () => {
          if (!settled) {
            settled = true;
            reject(new Error(`gateway unreachable: ${this.options.url}`));
          }
        };
        this.backoffMs = 1000;
        if (!settled) {
          settled = true;
          resolve();
        }
      };
      try {
        this.socket = new WebSocket(this.options.url);
      } catch (err) {
        reject(err instanceof Error ? err : new Error(String(err)));
        return;
      }
      this.socket.onopen = open;
      this.socket.onerror = () => {
        if (!settled) {
          settled = true;
          reject(new Error(`gateway unreachable: ${this.options.url}`));
        }
      };
    });
  }

  disconnect(): void {
    this.wanted = false;
    this.socket?.close();
    this.socket = null;
  }

  /** Request/response round trip; rejects on gateway error or timeout. */
  request(op: GatewayOp | string, body: Record<string, unknown>, timeoutMs = 8000): Promise<Record<string, unknown>> {
    if (!this.connected || !this.socket) {
      return Promise.reject(new Error('gateway not connected'));
    }
    const seq = (this.seq += 1);
    const payload: GatewayRequest = { op, seq, body };
    return new Promise((resolve, reject) => {
      const timer = window.setTimeout(() => {
        this.pending.delete(seq);
        reject(new Error(`gateway timeout: ${op}`));
      }, timeoutMs);
      this.pending.set(seq, {
        resolve: (result) => {
          window.clearTimeout(timer);
          resolve(result);
        },
        reject: (err) => {
          window.clearTimeout(timer);
          reject(err);
        },
      });
      this.socket?.send(JSON.stringify(payload));
    });
  }

  /** Subscribe to server pushes (seq 0 broadcasts). Returns unsubscribe. */
  onPush(op: GatewayOp | string, handler: PushHandler): () => void {
    let set = this.pushes.get(op);
    if (!set) {
      set = new Set();
      this.pushes.set(op, set);
    }
    set.add(handler);
    return () => {
      set?.delete(handler);
    };
  }

  private onMessage(event: MessageEvent): void {
    let msg: GatewayResponse;
    try {
      msg = JSON.parse(String(event.data)) as GatewayResponse;
    } catch {
      return;
    }
    if (msg.seq !== 0) {
      const pending = this.pending.get(msg.seq);
      if (!pending) return;
      this.pending.delete(msg.seq);
      if (msg.ok) pending.resolve(msg.body);
      else pending.reject(new Error(
        typeof msg.body?.['error'] === 'string' ? msg.body['error'] : `gateway refused ${msg.op}`,
      ));
      return;
    }
    this.pushes.get(msg.op)?.forEach((handler) => {
      try {
        handler(msg.body);
      } catch {
        // A broken subscriber must not kill the dispatch loop.
      }
    });
  }

  private onClose(): void {
    this.socket = null;
    for (const [, pending] of this.pending) {
      pending.reject(new Error('gateway closed'));
    }
    this.pending.clear();
    if (!this.wanted) return;
    const wait = Math.min(this.options.maxBackoffMs ?? 10000, this.backoffMs);
    this.backoffMs *= 2;
    window.setTimeout(() => {
      if (!this.wanted || this.connected) return;
      this.connect().catch(() => {
        // Reconnect failures ride the same backoff via onClose only
        // when a socket existed; a refused dial simply stays offline
        // until the next explicit connect() call from the shell.
      });
    }, wait);
  }
}
