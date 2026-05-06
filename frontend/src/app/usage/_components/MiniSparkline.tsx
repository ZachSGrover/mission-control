"use client";

/**
 * Minimal SVG sparkline — one polyline, no axes, no library.
 *
 * Intentionally tiny so we don't pull in recharts wrapper machinery for a
 * single 14-day cost trend on the Daily page.  If we later want axes/legend
 * we can swap for the existing recharts components.
 */
export function MiniSparkline({
  values,
  width = 480,
  height = 80,
  color = "#3b82f6",
}: {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
}) {
  if (values.length === 0) return null;
  const max = Math.max(...values, 0);
  const min = Math.min(...values, 0);
  const range = max - min || 1;

  const padX = 2;
  const padY = 4;
  const innerW = width - padX * 2;
  const innerH = height - padY * 2;

  const pts = values
    .map((v, i) => {
      const x =
        values.length === 1
          ? innerW / 2 + padX
          : padX + (i * innerW) / (values.length - 1);
      const y = padY + innerH - ((v - min) / range) * innerH;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <svg
      width="100%"
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="Daily spend trend"
    >
      <polyline
        fill="none"
        stroke={color}
        strokeWidth="2"
        strokeLinejoin="round"
        strokeLinecap="round"
        points={pts}
      />
    </svg>
  );
}
