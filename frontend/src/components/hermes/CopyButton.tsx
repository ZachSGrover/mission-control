"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

interface CopyButtonProps {
  /** The text to copy to the clipboard. */
  text: string;
  /** Visible button label. Defaults to "Copy". */
  label?: string;
  /** Optional aria-label override. */
  ariaLabel?: string;
}

export function CopyButton({ text, label = "Copy", ariaLabel }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    if (typeof navigator === "undefined" || !navigator.clipboard) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Silent — clipboard API can fail without permission; the button just
      // doesn't flash. Founder can still select the text manually.
    }
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      aria-label={ariaLabel ?? label}
      className="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium transition-colors hover:bg-white/5"
      style={{ borderColor: "var(--border)", color: "var(--foreground)" }}
    >
      {copied ? <Check size={14} /> : <Copy size={14} />}
      {copied ? "Copied" : label}
    </button>
  );
}
