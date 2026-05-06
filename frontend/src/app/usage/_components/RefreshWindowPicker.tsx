"use client";

import { cn } from "@/lib/utils";

import { REFRESH_WINDOW_HOURS, type RefreshWindowHours } from "../_lib/types";

const LABEL: Record<RefreshWindowHours, string> = {
  24: "24h",
  168: "7d",
  720: "30d",
};

interface RefreshWindowPickerProps {
  value: RefreshWindowHours;
  onChange: (value: RefreshWindowHours) => void;
  disabled?: boolean;
}

/**
 * Small segmented control that picks how far back the next manual refresh
 * should pull from each provider.  Distinct from the dashboard-view range
 * picker (which only changes how data is *displayed*).  Wider windows cost
 * more outbound API requests, so we keep the selector visible alongside
 * the Refresh Usage button rather than tucking it into a settings menu.
 */
export function RefreshWindowPicker({
  value,
  onChange,
  disabled,
}: RefreshWindowPickerProps) {
  return (
    <div
      className="inline-flex rounded-lg p-0.5"
      style={{
        background: "var(--surface-strong)",
        border: "1px solid var(--border)",
        opacity: disabled ? 0.5 : 1,
      }}
      role="tablist"
      aria-label="Refresh window"
    >
      {REFRESH_WINDOW_HOURS.map((opt) => {
        const active = opt === value;
        return (
          <button
            key={opt}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => !disabled && onChange(opt)}
            disabled={disabled}
            className={cn(
              "px-3 py-1 text-xs rounded-md transition-colors",
              active ? "font-medium" : "font-normal",
            )}
            style={
              active
                ? {
                    background: "var(--accent-soft)",
                    color: "var(--accent-strong)",
                  }
                : { color: "var(--text-muted)" }
            }
          >
            {LABEL[opt]}
          </button>
        );
      })}
    </div>
  );
}
