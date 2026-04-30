"use client";

import type { ReactNode } from "react";
import { Inbox } from "lucide-react";

interface EmptyStateProps {
  title: string;
  body?: ReactNode;
  icon?: ReactNode;
}

/** Friendly empty placeholder used by every list/table on the Usage pages. */
export function EmptyState({ title, body, icon }: EmptyStateProps) {
  return (
    <div
      className="rounded-xl px-6 py-10 flex flex-col items-center text-center gap-2"
      style={{
        background: "var(--surface-strong)",
        border: "1px dashed var(--border)",
      }}
    >
      <div style={{ color: "var(--text-quiet)" }}>
        {icon ?? <Inbox className="h-5 w-5" />}
      </div>
      <p
        className="text-sm font-medium"
        style={{ color: "var(--text)" }}
      >
        {title}
      </p>
      {body && (
        <p
          className="text-xs leading-relaxed max-w-sm"
          style={{ color: "var(--text-muted)" }}
        >
          {body}
        </p>
      )}
    </div>
  );
}
