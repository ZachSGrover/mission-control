/**
 * Small formatters scoped to the Usage Tracker UI.
 *
 * Kept local rather than added to `@/lib/formatters` so the Usage section
 * can iterate without rippling changes elsewhere.
 */

const numberFormatter = new Intl.NumberFormat("en-US");

const usdFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});

const usdPreciseFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
});

export function formatUsd(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  // Below a cent we still want some precision so 0.0123 doesn't render as $0.00.
  if (Math.abs(value) > 0 && Math.abs(value) < 0.01) {
    return usdPreciseFormatter.format(value);
  }
  return usdFormatter.format(value);
}

export function formatTokens(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return numberFormatter.format(Math.max(0, Math.round(value)));
}

export function formatCompactNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const v = Math.abs(value);
  if (v >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return numberFormatter.format(value);
}

// Backend serializes naive UTC datetimes (no 'Z' suffix). JavaScript's Date
// constructor would otherwise parse them as local time, giving negative
// "-14101s ago" results on the UI. Append 'Z' when missing.
function parseAsUtc(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const hasTz = /[zZ]|[+-]\d\d:\d\d$/.test(iso);
  const date = new Date(hasTz ? iso : `${iso}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatRelative(iso: string | null | undefined): string {
  const date = parseAsUtc(iso);
  if (!date) return "Never";
  const diffMs = Date.now() - date.getTime();
  // Treat tiny clock skew (within a few seconds in either direction) as "just now".
  if (Math.abs(diffMs) < 5000) return "Just now";
  if (diffMs < 0) return "Just now";
  const sec = Math.round(diffMs / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const days = Math.round(hr / 24);
  if (days < 7) return `${days}d ago`;
  return date.toLocaleDateString();
}

export function formatDate(iso: string | null | undefined): string {
  const d = parseAsUtc(iso);
  if (!d) return "—";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
