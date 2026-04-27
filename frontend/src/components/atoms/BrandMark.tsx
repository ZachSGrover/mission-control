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
 *   Defaults to "Digidle OS".
 */

"use client";

import Image from "next/image";
import { useState } from "react";

const LOGO_SRC = "/logo.png"; // drop your logo here: frontend/public/logo.png
const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME ?? "Digidle OS";

export function BrandMark({ compact = false }: { compact?: boolean }) {
  const [logoError, setLogoError] = useState(false);

  return (
    <div className="flex items-center gap-2">
      {/* Logo — shows image if /public/logo.png exists, else gradient fallback */}
      {!logoError ? (
        <div className="relative h-6 w-6 shrink-0 rounded-md overflow-hidden">
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
        <div className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-gradient-to-br from-blue-600 to-blue-700 text-[10px] font-semibold text-white">
          <span className="font-heading tracking-[0.2em]">
            {APP_NAME.slice(0, 1).toUpperCase()}
          </span>
        </div>
      )}

      {/* Wordmark — hidden in compact mode (e.g. tight nav drawer rails).
          `leading-none` collapses the line-box to the font-size so flex
          `items-center` actually centers the visible glyphs against the logo
          rather than centering a tall line-box that pulls the caps upward. */}
      {!compact && (
        <span className="font-heading text-[11px] uppercase tracking-[0.18em] text-strong whitespace-nowrap leading-none">
          {APP_NAME}
        </span>
      )}
    </div>
  );
}
