"use client";

import type { ReactNode } from "react";
import { useEffect, useState } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { getApiBaseUrl } from "@/lib/api-base";

/**
 * Keepalive component: pings /health every 4 minutes to prevent backend
 * cold-starts on sleeping tiers (Render free, Railway Hobby, etc.).
 * Fire-and-forget — errors are intentionally ignored.
 */
function BackendKeepalive() {
  useEffect(() => {
    const ping = () => {
      try {
        const base = getApiBaseUrl();
        fetch(`${base}/health`, { cache: "no-store" }).catch(() => {});
      } catch {
        // noop — keepalive must never throw
      }
    };

    // Delay the first ping so it doesn't compete with the initial page render.
    const warmup = setTimeout(ping, 5000);
    const id = setInterval(ping, 4 * 60 * 1000);
    return () => {
      clearTimeout(warmup);
      clearInterval(id);
    };
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
