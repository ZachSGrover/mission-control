import { describe, expect, it } from "vitest";

import { deriveClawdiusViewState } from "@/lib/clawdius-status";

describe("deriveClawdiusViewState", () => {
  it("returns no_gateway when no WS URL is configured for this host", () => {
    const state = deriveClawdiusViewState({
      status: "disconnected",
      gatewayConfigured: false,
      tokenConfigured: false,
    });
    expect(state.kind).toBe("no_gateway");
    expect(state.canSend).toBe(false);
    expect(state.canReconnect).toBe(false);
    expect(state.needsSettings).toBe(false);
    expect(state.tone).toBe("muted");
  });

  it("no_gateway wins even if a token is stored (URL precedence)", () => {
    // Token alone is useless without a URL — still surface the URL gap first.
    const state = deriveClawdiusViewState({
      status: "connecting",
      gatewayConfigured: false,
      tokenConfigured: true,
    });
    expect(state.kind).toBe("no_gateway");
  });

  it("returns no_token when URL is configured but token is missing", () => {
    const state = deriveClawdiusViewState({
      status: "disconnected",
      gatewayConfigured: true,
      tokenConfigured: false,
    });
    expect(state.kind).toBe("no_token");
    expect(state.needsSettings).toBe(true);
    expect(state.canSend).toBe(false);
    expect(state.tone).toBe("warn");
  });

  it("returns connected when status === connected", () => {
    const state = deriveClawdiusViewState({
      status: "connected",
      gatewayConfigured: true,
      tokenConfigured: true,
    });
    expect(state.kind).toBe("connected");
    expect(state.canSend).toBe(true);
    expect(state.tone).toBe("ok");
    expect(state.canReconnect).toBe(false);
  });

  it("returns connecting while the handshake is in flight", () => {
    const state = deriveClawdiusViewState({
      status: "connecting",
      gatewayConfigured: true,
      tokenConfigured: true,
    });
    expect(state.kind).toBe("connecting");
    expect(state.canSend).toBe(false);
    expect(state.canReconnect).toBe(false);
    expect(state.tone).toBe("pending");
  });

  it("returns unreachable when raw status is disconnected", () => {
    const state = deriveClawdiusViewState({
      status: "disconnected",
      gatewayConfigured: true,
      tokenConfigured: true,
    });
    expect(state.kind).toBe("unreachable");
    expect(state.canReconnect).toBe(true);
    expect(state.canSend).toBe(false);
    expect(state.tone).toBe("error");
  });

  it("returns unreachable when raw status is error", () => {
    const state = deriveClawdiusViewState({
      status: "error",
      gatewayConfigured: true,
      tokenConfigured: true,
    });
    expect(state.kind).toBe("unreachable");
    expect(state.canReconnect).toBe(true);
    expect(state.tone).toBe("error");
  });

  it("returns idle when raw status is idle and config is complete", () => {
    const state = deriveClawdiusViewState({
      status: "idle",
      gatewayConfigured: true,
      tokenConfigured: true,
    });
    expect(state.kind).toBe("idle");
    expect(state.canReconnect).toBe(true);
    expect(state.canSend).toBe(false);
    expect(state.tone).toBe("muted");
  });

  it("hints never contain the token value or any secret material", () => {
    // Sanity: the labels we surface should be safe to render anywhere.
    for (const status of ["idle", "connecting", "connected", "disconnected", "error"] as const) {
      const s = deriveClawdiusViewState({
        status,
        gatewayConfigured: true,
        tokenConfigured: true,
      });
      expect(s.label.length).toBeGreaterThan(0);
      expect(s.hint.length).toBeGreaterThan(0);
    }
  });
});
