"use client";

import type { ReactNode } from "react";
import { useEffect, useState } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/**
 * Keepalive component: pings /health every 4 minutes to prevent backend
 * cold-starts on sleeping tiers (Render free, Railway Hobby, etc.).
 * Fire-and-forget — errors are intentionally ignored.
 */
function BackendKeepalive() {
  useEffect(() => {
    const ping = () => {
      try {
        const base = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/+$/, "");
        const url = base
          ? `${base}/health`
          : typeof window !== "undefined"
          ? `${window.location.protocol}//${window.location.hostname}:8000/health`
          : null;
        if (url) fetch(url, { cache: "no-store" }).catch(() => {});
      } catch {
        // noop — keepalive must never throw
      }
    };

    ping(); // warm the backend on first page load
    const id = setInterval(ping, 4 * 60 * 1000);
    return () => clearInterval(id);
  }, []);

  return null;
}

export function QueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // 2 minutes — data stays fresh; tabs no longer refetch on every switch.
            staleTime: 2 * 60_000,
            // 30 minutes — keep unused results in memory so navigating back
            // to a page shows cached data instantly instead of a loading state.
            gcTime: 30 * 60_000,
            // Disabled — was the primary cause of every tab/window switch
            // triggering a full API reload across all mounted components.
            refetchOnWindowFocus: false,
            // Keep this on so stale data refreshes after a network outage.
            refetchOnReconnect: true,
            retry: 1,
          },
          mutations: {
            retry: 0,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={client}>
      <BackendKeepalive />
      {children}
    </QueryClientProvider>
  );
}
