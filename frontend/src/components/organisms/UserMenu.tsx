"use client";

import { useState } from "react";
import Link from "next/link";
import { LogOut, Settings } from "lucide-react";

import { SignOutButton, useUser } from "@/auth/clerk";
import { clearLocalAuthToken, isLocalAuthMode } from "@/auth/localAuth";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

type UserMenuProps = {
  displayName?: string;
  displayEmail?: string;
};

export function UserMenu({ displayName, displayEmail }: UserMenuProps) {
  const [open, setOpen] = useState(false);
  const { user } = useUser();
  const localMode = isLocalAuthMode();

  if (!user && !localMode) return null;

  const name = displayName ?? (localMode ? "Local User" : "Account");
  const email = displayEmail ?? (localMode ? "" : "");
  const initial = name.slice(0, 1).toUpperCase();

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label="Account menu"
          className="h-8 w-8 rounded-full flex items-center justify-center text-xs font-semibold text-white transition-opacity hover:opacity-80 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          style={{ background: "var(--accent)" }}
        >
          {initial}
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
