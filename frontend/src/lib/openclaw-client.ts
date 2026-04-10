"use client";

// OpenClaw Gateway WebSocket Client
// Handles the full connection lifecycle: handshake → auth → send/receive messages

export type ConnectionStatus = "idle" | "connecting" | "connected" | "disconnected" | "error";

export interface ChatEvent {
  runId: string;
  sessionKey: string;
  seq: number;
  state: "delta" | "final" | "aborted" | "error";
  message?: unknown;
  errorMessage?: string;
  stopReason?: string;
}

type PendingRequest = {
  resolve: (value: unknown) => void;
  reject: (reason: unknown) => void;
};

function uuid(): string {
  return crypto.randomUUID();
}

// Pull readable text out of whatever shape OpenClaw returns as message content
export function extractText(message: unknown): string {
  if (!message || typeof message !== "object") return "";
  const m = message as Record<string, unknown>;

  // Anthropic streaming delta: { delta: { type: "text_delta", text: "..." } }
  if (m.delta && typeof m.delta === "object") {
    const d = m.delta as Record<string, unknown>;
    if (typeof d.text === "string") return d.text;
  }

  // Anthropic complete message: { content: [{ type: "text", text: "..." }] }
  if (Array.isArray(m.content)) {
    return m.content
      .filter((b): b is Record<string, unknown> => typeof b === "object" && b !== null)
      .filter((b) => b.type === "text" && typeof b.text === "string")
      .map((b) => b.text as string)
      .join("");
  }

  // Flat text field
  if (typeof m.text === "string") return m.text;

  // Nested content string
  if (typeof m.content === "string") return m.content;

  return "";
}

export class OpenClawClient {
  private ws: WebSocket | null = null;
  private pending = new Map<string, PendingRequest>();
  private onChatEvent: (event: ChatEvent) => void;
  private onStatusChange: (status: ConnectionStatus) => void;
  private url: string;
  private token: string;
  private destroyed = false;

  constructor(opts: {
    url: string;
    token: string;
    onChatEvent: (event: ChatEvent) => void;
    onStatusChange: (status: ConnectionStatus) => void;
  }) {
    this.url = opts.url;
    this.token = opts.token;
    this.onChatEvent = opts.onChatEvent;
    this.onStatusChange = opts.onStatusChange;
  }

  connect(): void {
    if (this.ws) return;
    this.destroyed = false;
    this.onStatusChange("connecting");

    const ws = new WebSocket(this.url);
    this.ws = ws;

    ws.onopen = () => {
      // Wait for connect.challenge event from server before sending anything
    };

    ws.onmessage = (event: MessageEvent) => {
      this.handleFrame(event.data as string);
    };

    ws.onerror = () => {
      this.onStatusChange("error");
    };

    ws.onclose = () => {
      this.ws = null;
      if (!this.destroyed) {
        this.onStatusChange("disconnected");
      }
    };
  }

  disconnect(): void {
    this.destroyed = true;
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.onStatusChange("idle");
  }

  async sendMessage(sessionKey: string, text: string, model?: string): Promise<void> {
    const params: Record<string, unknown> = {
      sessionKey,
      message: text,
      deliver: false,
      idempotencyKey: uuid(),
    };
    void model; // OpenClaw chat.send does not accept a model property
    await this.request("chat.send", params);
  }

  // Internal: send a JSON-RPC style request and wait for the matching response
  private request(method: string, params: unknown): Promise<unknown> {
    return new Promise((resolve, reject) => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
        reject(new Error("WebSocket is not connected"));
        return;
      }
      const id = uuid();
      this.pending.set(id, { resolve, reject });
      this.ws.send(
        JSON.stringify({ type: "req", id, method, params })
      );
    });
  }

  private handleFrame(raw: string): void {
    let frame: Record<string, unknown>;
    try {
      frame = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return;
    }

    const type = frame.type as string;

    // Server-initiated event
    if (type === "event") {
      const eventName = frame.event as string;

      if (eventName === "connect.challenge") {
        // Respond to challenge with our credentials
        void this.respondToChallenge();
        return;
      }

      if (eventName === "chat") {
        this.onChatEvent(frame.payload as ChatEvent);
        return;
      }

      return;
    }

    // Response to one of our requests
    if (type === "res") {
      const id = frame.id as string;
      const pending = this.pending.get(id);
      if (!pending) return;
      this.pending.delete(id);

      if (frame.ok) {
        pending.resolve(frame.payload);
      } else {
        const e = frame.error;
        const errMsg = e
          ? (typeof e === "object"
              ? ((e as Record<string, unknown>).message as string | undefined) ?? JSON.stringify(e)
              : String(e))
          : "Request failed";
        pending.reject(new Error(errMsg));
      }
    }
  }

  private async respondToChallenge(): Promise<void> {
    try {
      await this.request("connect", {
        minProtocol: 3,
        maxProtocol: 3,
        role: "operator",
        scopes: ["operator.read", "operator.write", "operator.admin"],
        client: {
          id: "openclaw-control-ui",  // operator UI client — preserves scopes with local token auth
          version: "1.0.0",
          platform: "darwin",
          mode: "ui",
        },
        auth: {
          token: this.token,
        },
      });
      this.onStatusChange("connected");
    } catch (err) {
      console.error("[openclaw] Auth failed:", err);
      this.onStatusChange("error");
    }
  }
}
