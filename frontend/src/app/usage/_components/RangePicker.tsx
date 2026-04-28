"use client";

import { cn } from "@/lib/utils";

import type { RangeKey } from "../_lib/types";

const OPTIONS: { value: RangeKey; label: string }[] = [
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
  { value: "30d", label: "30d" },
  { value: "mtd", label: "MTD" },
];

interface RangePickerProps {
  value: RangeKey;
  onChange: (value: RangeKey) => void;
}

export function RangePicker({ value, onChange }: RangePickerProps) {
  return (
    <div
      className="inline-flex rounded-lg p-0.5"
      style={{
        background: "var(--surface-strong)",
        border: "1px solid var(--border)",
      }}
      role="tablist"
      aria-label="Time range"
    >
      {OPTIONS.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(opt.value)}
            className={cn(
              "px-3 py-1 text-xs rounded-md transition-colors",
              active ? "font-medium" : "font-normal",
            )}
            style={
              active
                ? { background: "var(--accent-soft)", color: "var(--accent-strong)" }
                : { color: "var(--text-muted)" }
            }
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
