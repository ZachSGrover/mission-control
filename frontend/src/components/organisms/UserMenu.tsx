"use client";

/**
 * UserMenu — avatar button + dropdown.
 *
 * Profile image priority:
 *   1. Clerk profile photo (automatic, set at clerk.com dashboard)
 *   2. /public/avatar.png — drop any image here: frontend/public/avatar.png (64×64px)
 *   3. Initial letter fallback (default when no image available)
 */

import { useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { LogOut, Settings } from "lucide-react";

import { SignOutButton, useUser } from "@/auth/clerk";
import { clearLocalAuthToken, isLocalAuthMode } from "@/auth/localAuth";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

type UserMenuProps = {
  displayName?: string;
  displayEmail?: string;
};

function Avatar({ name, imageUrl }: { name: string; imageUrl?: string | null }) {
  const [imgError, setImgError] = useState(false);
  const initial = name.slice(0, 1).toUpperCase();
  const showImage = Boolean(imageUrl) && !imgError;
  return (
    <span
      className="h-8 w-8 rounded-full overflow-hidden flex items-center justify-center text-xs font-semibold text-white shrink-0"
      style={!showImage ? { background: "var(--accent)" } : undefined}
    >
      {showImage && imageUrl ? (
        <Image
          src={imageUrl}
          alt={name}
          width={32}
          height={32}
          className="object-cover w-full h-full"
          onError={() => setImgError(true)}
          unoptimized
        />
      ) : initial}
    </span>
  );
}

export function UserMenu({ displayName, displayEmail }: UserMenuProps) {
  const [open, setOpen] = useState(false);
  const { user } = useUser();
  const localMode = isLocalAuthMode();

  if (!user && !localMode) return null;

  const name = displayName ?? (localMode ? "Local User" : "Account");
  const email = displayEmail ?? "";
  // Clerk provides imageUrl automatically; local mode looks for /public/avatar.png
  const imageUrl: string | null =
    (user as { imageUrl?: string } | null)?.imageUrl ??
    (localMode ? "/avatar.png" : null);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label="Account menu"
          className="rounded-full transition-opacity hover:opacity-80 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
        >
          <Avatar name={name} imageUrl={imageUrl} />
        </button>
      </PopoverTrigger>

      <PopoverContent
        align="end"
        sideOffset={10}
        className="w-56 p-0 rounded-xl overflow-hidden border"
        style={{
          background: "var(--surface-strong)",
          borderColor: "var(--border-strong)",
          boxShadow: "0 8px 32px rgba(0,0,0,0.8)",
        }}
      >
        {/* Identity */}
        <div
          className="px-4 py-3 border-b"
          style={{ borderColor: "var(--border)" }}
        >
          <p className="text-sm font-semibold truncate" style={{ color: "var(--text)" }}>
            {name}
          </p>
          {email ? (
            <p className="text-xs truncate mt-0.5" style={{ color: "var(--text-quiet)" }}>
              {email}
            </p>
          ) : null}
        </div>

        {/* Actions */}
        <div className="p-1.5 space-y-0.5">
          <Link
            href="/settings"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2.5 w-full rounded-lg px-3 py-2 text-sm transition-colors"
            style={{ color: "var(--text-muted)" }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = "var(--text)"; (e.currentTarget as HTMLElement).style.background = "var(--surface-muted)"; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = "var(--text-muted)"; (e.currentTarget as HTMLElement).style.background = "transparent"; }}
          >
            <Settings className="h-4 w-4 shrink-0" />
            Settings
          </Link>

          <div className="h-px mx-1" style={{ background: "var(--border)" }} />

          {localMode ? (
            <button
              type="button"
              className="flex items-center gap-2.5 w-full rounded-lg px-3 py-2 text-sm transition-colors"
              style={{ color: "var(--text-muted)" }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = "#ef4444"; (e.currentTarget as HTMLElement).style.background = "var(--surface-muted)"; }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = "var(--text-muted)"; (e.currentTarget as HTMLElement).style.background = "transparent"; }}
              onClick={() => {
                clearLocalAuthToken();
                setOpen(false);
                window.location.reload();
              }}
            >
              <LogOut className="h-4 w-4 shrink-0" />
              Sign out
            </button>
          ) : (
            <SignOutButton>
              <button
                type="button"
                className="flex items-center gap-2.5 w-full rounded-lg px-3 py-2 text-sm transition-colors"
                style={{ color: "var(--text-muted)" }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = "#ef4444"; (e.currentTarget as HTMLElement).style.background = "var(--surface-muted)"; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = "var(--text-muted)"; (e.currentTarget as HTMLElement).style.background = "transparent"; }}
                onClick={() => setOpen(false)}
              >
                <LogOut className="h-4 w-4 shrink-0" />
                Sign out
              </button>
            </SignOutButton>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
