// Browser side of a Pramaan phone session (docs/BROWSER-VOICE.md of the
// capability catalogue). No provider code: it talks only to Pramaan's relay,
// with the short-lived session credential the app's server hands over (never
// the API key). Call actions (start, accept, reject, end) go through this app;
// this module owns the connection: hello with the credential, events with a
// resumable cursor, reconnect with back-off, mute, and 8 kHz mu-law audio.

export interface BrowserVoiceEvent {
  readonly id: string;
  readonly type: string;
  readonly at: string;
  readonly callRef?: string;
  readonly direction?: "inbound" | "outbound";
  readonly from?: string;
  readonly to?: string;
  readonly reason?: string;
  readonly correlationId?: string;
}

export type BrowserPhoneState = "connecting" | "ready" | "reconnecting" | "closed";

/** Close codes after which reconnecting cannot help. */
export const BROWSER_PHONE_FINAL_CODES: Readonly<Record<number, string>> = {
  4401: "credential",
  4403: "origin",
  4410: "session_ended",
};

interface SocketLike {
  binaryType: string;
  readonly readyState: number;
  onopen: ((event: unknown) => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  onclose: ((event: { code: number }) => void) | null;
  send(data: string | Uint8Array): void;
  close(code?: number, reason?: string): void;
}

export interface BrowserPhoneOptions {
  readonly connectUrl: string;
  readonly credential: string;
  /** The last event id handled, to resume after a page reload. */
  readonly cursor?: string;
  readonly onEvent?: (event: BrowserVoiceEvent) => void;
  /** 8 kHz mono samples from the call, -1 to 1. */
  readonly onAudio?: (samples: Float32Array) => void;
  readonly onState?: (state: BrowserPhoneState, reason?: string) => void;
  /** Test seam. Default: the global WebSocket. */
  readonly WebSocket?: new (url: string) => SocketLike;
  readonly maxBackoffMs?: number;
}

export interface BrowserPhone {
  setCredential(credential: string): void;
  /** Pramaan holds the agent's audio back while muted. Also stop the mic track. */
  mute(muted: boolean): void;
  /** 8 kHz mono samples from the microphone; sent only while connected. */
  sendAudio(samples: Float32Array): void;
  readonly cursor: string | undefined;
  close(): void;
}

const BIAS = 0x84;
const CLIP = 32635;

/** G.711 mu-law, 8 bits per sample. */
export function encodeMuLaw(samples: Float32Array): Uint8Array {
  const out = new Uint8Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    let sample = Math.round(Math.max(-1, Math.min(1, samples[i] ?? 0)) * 32767);
    const sign = sample < 0 ? 0x80 : 0;
    if (sign) sample = -sample;
    sample = Math.min(sample, CLIP) + BIAS;
    let exponent = 7;
    for (let mask = 0x4000; (sample & mask) === 0 && exponent > 0; mask >>= 1) exponent--;
    const mantissa = (sample >> (exponent + 3)) & 0x0f;
    out[i] = ~(sign | (exponent << 4) | mantissa) & 0xff;
  }
  return out;
}

export function decodeMuLaw(bytes: Uint8Array): Float32Array {
  const out = new Float32Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) {
    const u = ~(bytes[i] ?? 0) & 0xff;
    const exponent = (u >> 4) & 0x07;
    const magnitude = ((((u & 0x0f) << 3) + BIAS) << exponent) - BIAS;
    out[i] = (u & 0x80 ? -magnitude : magnitude) / 32768;
  }
  return out;
}

const seqOf = (id: string | undefined) => (id ? Number(id.slice(3)) || 0 : 0);

export function connectBrowserPhone(options: BrowserPhoneOptions): BrowserPhone {
  const Socket =
    options.WebSocket ??
    (globalThis as unknown as { WebSocket: new (url: string) => SocketLike }).WebSocket;
  const maxBackoff = options.maxBackoffMs ?? 8000;
  let credential = options.credential;
  let cursor = options.cursor;
  let socket: SocketLike | undefined;
  let muted = false;
  let stopped = false;
  let attempt = 0;
  let ready = false;

  function open() {
    ready = false;
    const ws = new Socket(options.connectUrl);
    socket = ws;
    ws.binaryType = "arraybuffer";
    ws.onopen = () => {
      // The credential travels in the first message, never in the URL.
      ws.send(JSON.stringify({ type: "hello", credential, ...(cursor ? { cursor } : {}) }));
    };
    ws.onmessage = ({ data }) => {
      if (typeof data !== "string") {
        const bytes = data instanceof ArrayBuffer ? new Uint8Array(data) : (data as Uint8Array);
        options.onAudio?.(decodeMuLaw(bytes));
        return;
      }
      const message = JSON.parse(data) as { type?: string; event?: BrowserVoiceEvent };
      if (message.type === "ready") {
        ready = true;
        attempt = 0;
        if (muted) ws.send(JSON.stringify({ type: "mute", muted }));
        options.onState?.("ready");
      } else if (message.type === "event" && message.event) {
        // Each event once: a replay after a reconnect never repeats one.
        if (seqOf(message.event.id) <= seqOf(cursor)) return;
        cursor = message.event.id;
        options.onEvent?.(message.event);
      }
    };
    ws.onclose = ({ code }) => {
      if (socket !== ws) return;
      socket = undefined;
      ready = false;
      const final = BROWSER_PHONE_FINAL_CODES[code];
      if (stopped || final || code === 4409) {
        stopped = true;
        options.onState?.("closed", final ?? (code === 4409 ? "replaced" : undefined));
        return;
      }
      options.onState?.("reconnecting");
      const delay = Math.min(maxBackoff, 500 * 2 ** attempt++);
      setTimeout(() => {
        if (!stopped) open();
      }, delay);
    };
  }

  options.onState?.("connecting");
  open();
  return {
    setCredential(next) {
      credential = next;
    },
    mute(next) {
      muted = next;
      if (ready) socket?.send(JSON.stringify({ type: "mute", muted }));
    },
    sendAudio(samples) {
      if (ready && !muted) socket?.send(encodeMuLaw(samples));
    },
    get cursor() {
      return cursor;
    },
    close() {
      stopped = true;
      socket?.close(1000, "closed by the page");
    },
  };
}
