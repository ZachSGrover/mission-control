/**
 * BrandMark — sidebar logo + wordmark.
 *
 * To use your own logo image:
 *   1. Drop your logo file into: frontend/public/logo.png  (or .svg / .webp)
 *   2. It will automatically appear in place of the "D" gradient box.
 *   3. Recommended size: 40×40px, transparent background.
 *
 * To change the wordmark text:
 *   Set NEXT_PUBLIC_APP_NAME in your Vercel environment variables.
 *   Defaults to "Digital OS".
 */

"use client";

import Image from "next/image";
import { useState } from "react";

const LOGO_SRC = "/logo.png"; // drop your logo here: frontend/public/logo.png
const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME ?? "Digital OS";

export function BrandMark({ compact = false }: { compact?: boolean }) {
  const [logoError, setLogoError] = useState(false);

  return (
    <div className="flex items-center gap-3">
      {/* Logo — shows image if /public/logo.png exists, else gradient fallback */}
      {!logoError ? (
        <div className="relative h-9 w-9 shrink-0 rounded-lg overflow-hidden shadow-sm">
          <Image
            src={LOGO_SRC}
            alt={APP_NAME}
            fill
            className="object-contain"
            onError={() => setLogoError(true)}
            priority
            unoptimized
          />
        </div>
      ) : (
        <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-blue-600 to-blue-700 text-xs font-semibold text-white shadow-sm">
          <span className="font-heading tracking-[0.2em]">
            {APP_NAME.slice(0, 1).toUpperCase()}
          </span>
        </div>
      )}

      {/* Wordmark — hidden in compact mode (e.g. Electron where the macOS
          window title already shows the app name and header space is tight). */}
      {!compact && (
        <div className="leading-tight">
          <div className="font-heading text-sm uppercase tracking-[0.22em] text-strong">
            {APP_NAME}
          </div>
        </div>
      )}
    </div>
  );
}
