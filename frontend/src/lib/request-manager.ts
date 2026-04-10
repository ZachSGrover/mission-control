// Module-level singleton — persists across tab switches within the SPA session.
// Tracks active AI streaming requests per provider so responses continue
// running even when the user navigates away from a tab.

export type RequestStatus = "pending" | "streaming" | "complete" | "error";

export interface ActiveRequest {
  id: string;
  provider: string;
  status: RequestStatus;
  assistantMsgId: string;
  partialText: string;
  errorMsg?: string;
  startedAt: number;
}

type Listener = () => void;
// Callback fired when a request completes — persists even after the component unmounts
type CompleteCallback = (finalText: string, assistantMsgId: string) => void;
type FailCallback = (errorMsg: string, assistantMsgId: string) => void;

class RequestManager {
  private _requests = new Map<string, ActiveRequest>();
  private _listeners = new Set<Listener>();
  private _onComplete = new Map<string, CompleteCallback>();
  private _onFail = new Map<string, FailCallback>();

  // Subscribe to any state change. Returns unsubscribe fn.
  subscribe(fn: Listener): () => void {
    this._listeners.add(fn);
    return () => this._listeners.delete(fn);
  }

  private _notify() {
    for (const fn of this._listeners) fn();
  }

  getActive(provider: string): ActiveRequest | undefined {
    return this._requests.get(provider);
  }

  isActive(provider: string): boolean {
    const req = this._requests.get(provider);
    return req?.status === "pending" || req?.status === "streaming";
  }

  /**
   * Register a callback that fires when this provider's request completes.
   * The callback is held even if the component unmounts — use it to persist
   * the final response to localStorage.
   */
  onComplete(provider: string, cb: CompleteCallback): void {
    this._onComplete.set(provider, cb);
  }

  onFail(provider: string, cb: FailCallback): void {
    this._onFail.set(provider, cb);
  }

  start(provider: string, assistantMsgId: string): string {
    const id = crypto.randomUUID();
    this._requests.set(provider, {
      id,
      provider,
      status: "pending",
      assistantMsgId,
      partialText: "",
      startedAt: Date.now(),
    });
    this._notify();
    return id;
  }

  appendDelta(provider: string, delta: string) {
    const req = this._requests.get(provider);
    if (!req) return;
    req.status = "streaming";
    req.partialText += delta;
    this._notify();
  }

  setFinalText(provider: string, text: string) {
    const req = this._requests.get(provider);
    if (!req) return;
    req.partialText = text;
  }

  complete(provider: string) {
    const req = this._requests.get(provider);
    if (!req) return;
    req.status = "complete";
    this._notify();

    // Fire the save callback immediately (before cleanup) so localStorage
    // is written even if the component is currently unmounted.
    const cb = this._onComplete.get(provider);
    if (cb) {
      cb(req.partialText, req.assistantMsgId);
      this._onComplete.delete(provider);
    }

    // Brief window so reconnecting components can read final state
    setTimeout(() => {
      this._requests.delete(provider);
      this._notify();
    }, 2500);
  }

  fail(provider: string, errorMsg: string) {
    const req = this._requests.get(provider);
    if (!req) return;
    req.status = "error";
    req.errorMsg = errorMsg;
    this._notify();

    const cb = this._onFail.get(provider);
    if (cb) {
      cb(errorMsg, req.assistantMsgId);
      this._onFail.delete(provider);
    }

    setTimeout(() => {
      this._requests.delete(provider);
      this._notify();
    }, 3000);
  }
}

export const requestManager = new RequestManager();
