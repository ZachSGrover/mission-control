"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import {
  Activity,
  Bot,
  Brain,
  CalendarDays,
  ChevronDown,
  ChevronRight,
  Check,
  CloudUpload,
  FolderOpen,
  GitBranch,
  Layout,
  Loader2,
  MessageSquare,
  Network,
  Plug,
  Settings,
  Sparkles,
  TriangleAlert,
  Users,
  Wrench,
  Zap,
} from "lucide-react";

import { ApiError } from "@/api/mutator";
import {
  type healthzHealthzGetResponse,
  useHealthzHealthzGet,
} from "@/api/generated/default/default";
import { useGitSave } from "@/hooks/use-git-save";
import { useRole } from "@/hooks/use-role";
import { cn } from "@/lib/utils";

// ── Section label ─────────────────────────────────────────────────────────────

function NavSection({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p
        className="px-3 mb-1 text-[10px] font-semibold uppercase tracking-widest"
        style={{ color: "var(--text-quiet)" }}
      >
        {label}
      </p>
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

// ── Collapsible section (user setting persists to localStorage) ──────────────

function CollapsibleSection({
  label,
  storageKey,
  defaultOpen,
  children,
}: {
  label: string;
  storageKey: string;
  defaultOpen: boolean;
  children: React.ReactNode;
}) {
  // Lazy initializer reads localStorage during the first client render so
  // initial markup already matches the user's stored preference.
  const [open, setOpen] = useState<boolean>(() => {
    if (typeof window === "undefined") return defaultOpen;
    try {
      const stored = window.localStorage.getItem(storageKey);
      if (stored === "1") return true;
      if (stored === "0") return false;
    } catch { /* ignore */ }
    return defaultOpen;
  });

  const toggle = () => {
    setOpen((prev) => {
      const next = !prev;
      try { localStorage.setItem(storageKey, next ? "1" : "0"); } catch { /* ignore */ }
      return next;
    });
  };

  return (
    <div>
      <button
        type="button"
        onClick={toggle}
        className="w-full flex items-center justify-between px-3 mb-1 text-[10px] font-semibold uppercase tracking-widest transition-colors"
        style={{ color: "var(--text-quiet)" }}
      >
        <span>{label}</span>
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
      </button>
      {open && <div className="space-y-0.5">{children}</div>}
    </div>
  );
}

// ── Top-level nav link ────────────────────────────────────────────────────────

function NavLink({
  href,
  label,
  Icon,
  exact = false,
}: {
  href: string;
  label: string;
  Icon: React.ElementType;
  exact?: boolean;
}) {
  const pathname = usePathname();
  const active = exact ? pathname === href : pathname.startsWith(href);

  return (
    <Link
      href={href}
      className={cn(
        "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
        active ? "font-medium" : "font-normal",
      )}
      style={
        active
          ? { background: "var(--accent-soft)", color: "var(--accent-strong)" }
          : { color: "var(--text-muted)" }
      }
      onMouseEnter={(e) => {
        if (!active) (e.currentTarget as HTMLElement).style.color = "var(--text)";
      }}
      onMouseLeave={(e) => {
        if (!active) (e.currentTarget as HTMLElement).style.color = "var(--text-muted)";
      }}
    >
      <Icon className="h-4 w-4 shrink-0" />
      {label}
    </Link>
  );
}

// ── Sub-item nav link (indented) ──────────────────────────────────────────────

function NavSubLink({
  href,
  label,
  Icon,
  exact = false,
}: {
  href: string;
  label: string;
  Icon: React.ElementType;
  exact?: boolean;
}) {
  const pathname = usePathname();
  const active = exact ? pathname === href : pathname.startsWith(href);

  return (
    <Link
      href={href}
      className={cn(
        "flex items-center gap-2.5 rounded-lg pl-6 pr-3 py-1.5 text-[13px] transition-colors",
        active ? "font-medium" : "font-normal",
      )}
      style={
        active
          ? { background: "var(--accent-soft)", color: "var(--accent-strong)" }
          : { color: "var(--text-muted)" }
      }
      onMouseEnter={(e) => {
        if (!active) (e.currentTarget as HTMLElement).style.color = "var(--text)";
      }}
      onMouseLeave={(e) => {
        if (!active) (e.currentTarget as HTMLElement).style.color = "var(--text-muted)";
      }}
    >
      <Icon className="h-3.5 w-3.5 shrink-0" />
      {label}
    </Link>
  );
}

// ── Sidebar ───────────────────────────────────────────────────────────────────

export function DashboardSidebar() {
  const pathname = usePathname();

  const healthQuery = useHealthzHealthzGet<healthzHealthzGetResponse, ApiError>({
    query: {
      refetchInterval: 30_000,
      refetchOnMount: "always",
      retry: false,
    },
    request: { cache: "no-store" },
  });

  const okValue = healthQuery.data?.data?.ok;
  const systemStatus: "unknown" | "operational" | "degraded" =
    okValue === true ? "operational"
    : okValue === false ? "degraded"
    : healthQuery.isError ? "degraded"
    : "unknown";

  const isSettingsActive = pathname.startsWith("/settings");
  const gitSave = useGitSave();
  const { role } = useRole();

  // Auto-open "More" if the user is on a route inside it
  const moreRoutes = ["/chat/gpt", "/chat/gemini", "/chat/master", "/projects", "/memory", "/calendar", "/boards", "/agents", "/control", "/workflows", "/skills"];
  const moreOpenByRoute = moreRoutes.some((r) => pathname.startsWith(r));

  return (
    <aside
      className={cn(
        "fixed top-16 left-0 bottom-0 z-50 flex flex-col w-[260px]",
        "-translate-x-full transition-transform duration-200 ease-in-out",
        "[[data-sidebar=open]_&]:translate-x-0",
        "md:relative md:top-auto md:left-auto md:bottom-auto md:z-auto",
        "md:translate-x-0 md:w-[220px] md:shrink-0 md:h-full md:transition-none",
      )}
      style={{ background: "var(--surface)", borderRight: "1px solid var(--border)" }}
    >
      {/* ── Scrollable nav ───────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-3 py-5 space-y-5">

        {/* Primary */}
        <NavSection label="Primary">
          <NavLink href="/chat"     label="Claw" Icon={MessageSquare} exact />
          <NavLink href="/activity" label="Logs" Icon={Activity} />
        </NavSection>

        {/* More — everything working but secondary, collapsed by default */}
        <CollapsibleSection label="More" storageKey="mc_sidebar_more_open" defaultOpen={moreOpenByRoute}>
          {/* Other chat providers */}
          <NavSubLink href="/chat/gpt"     label="ChatGPT"  Icon={Zap} />
          <NavSubLink href="/chat/gemini"  label="Gemini"   Icon={Sparkles} />
          <NavSubLink href="/chat/master"  label="Master"   Icon={MessageSquare} />
          {/* Memory / Planning */}
          <NavSubLink href="/projects"  label="Projects"  Icon={FolderOpen} />
          <NavSubLink href="/memory"    label="Memory"    Icon={Brain} exact />
          <NavSubLink href="/calendar"  label="Calendar"  Icon={CalendarDays} />
          {/* Automation */}
          <NavSubLink href="/boards"    label="Boards"    Icon={Layout} />
          <NavSubLink href="/agents"    label="Agents"    Icon={Bot} />
          <NavSubLink href="/control"   label="Control"   Icon={Network} />
          <NavSubLink href="/workflows" label="Workflows" Icon={GitBranch} />
          <NavSubLink href="/skills"    label="Skills"    Icon={Wrench} />
        </CollapsibleSection>

      </div>

      {/* ── Pinned bottom: Save + Settings + status ─────────────────── */}
      <div
        className="shrink-0 px-3 pb-4 pt-2 space-y-1"
        style={{ borderTop: "1px solid var(--border)" }}
      >
        <button
          type="button"
          onClick={() => {
            if (gitSave.status === "error") gitSave.reset();
            else void gitSave.save();
          }}
          disabled={gitSave.status === "saving"}
          className={cn(
            "w-full flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-normal transition-colors disabled:opacity-60",
          )}
          style={{
            color:
              gitSave.status === "saved"  ? "var(--accent-strong)" :
              gitSave.status === "error"  ? "rgb(248 113 113)" :
              "var(--text-muted)",
          }}
          onMouseEnter={(e) => {
            if (gitSave.status === "idle")
              (e.currentTarget as HTMLElement).style.color = "var(--text)";
          }}
          onMouseLeave={(e) => {
            if (gitSave.status === "idle")
              (e.currentTarget as HTMLElement).style.color = "var(--text-muted)";
          }}
          title={gitSave.message || "Save to GitHub"}
        >
          {gitSave.status === "saving" && <Loader2 className="h-4 w-4 shrink-0 animate-spin" />}
          {gitSave.status === "saved"  && <Check className="h-4 w-4 shrink-0" />}
          {gitSave.status === "error"  && <TriangleAlert className="h-4 w-4 shrink-0" />}
          {gitSave.status === "idle"   && <CloudUpload className="h-4 w-4 shrink-0" />}
          <span className="truncate">
            {gitSave.status === "saving" ? "Saving…" :
             gitSave.status === "saved"  ? "Saved" :
             gitSave.status === "error"  ? "Save failed — tap to dismiss" :
             "Save"}
          </span>
        </button>

        {gitSave.status === "error" && gitSave.message && (
          <p className="px-3 text-[11px] leading-snug text-red-400">
            {gitSave.message}
          </p>
        )}

        <Link
          href="/settings"
          className={cn(
            "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
            isSettingsActive && !pathname.startsWith("/settings/users") && !pathname.startsWith("/settings/integrations") ? "font-medium" : "font-normal",
          )}
          style={
            isSettingsActive && !pathname.startsWith("/settings/users") && !pathname.startsWith("/settings/integrations")
              ? { background: "var(--accent-soft)", color: "var(--accent-strong)" }
              : { color: "var(--text-muted)" }
          }
          onMouseEnter={(e) => {
            if (!(isSettingsActive && !pathname.startsWith("/settings/users") && !pathname.startsWith("/settings/integrations")))
              (e.currentTarget as HTMLElement).style.color = "var(--text)";
          }}
          onMouseLeave={(e) => {
            if (!(isSettingsActive && !pathname.startsWith("/settings/users") && !pathname.startsWith("/settings/integrations")))
              (e.currentTarget as HTMLElement).style.color = "var(--text-muted)";
          }}
        >
          <Settings className="h-4 w-4 shrink-0" />
          Settings
        </Link>

        {role === "owner" && (
          <Link
            href="/settings/users"
            className={cn(
              "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
              pathname.startsWith("/settings/users") ? "font-medium" : "font-normal",
            )}
            style={
              pathname.startsWith("/settings/users")
                ? { background: "var(--accent-soft)", color: "var(--accent-strong)" }
                : { color: "var(--text-muted)" }
            }
            onMouseEnter={(e) => {
              if (!pathname.startsWith("/settings/users"))
                (e.currentTarget as HTMLElement).style.color = "var(--text)";
            }}
            onMouseLeave={(e) => {
              if (!pathname.startsWith("/settings/users"))
                (e.currentTarget as HTMLElement).style.color = "var(--text-muted)";
            }}
          >
            <Users className="h-4 w-4 shrink-0" />
            Users
          </Link>
        )}

        {role === "owner" && (
          <Link
            href="/settings/integrations"
            className={cn(
              "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
              pathname.startsWith("/settings/integrations") ? "font-medium" : "font-normal",
            )}
            style={
              pathname.startsWith("/settings/integrations")
                ? { background: "var(--accent-soft)", color: "var(--accent-strong)" }
                : { color: "var(--text-muted)" }
            }
            onMouseEnter={(e) => {
              if (!pathname.startsWith("/settings/integrations"))
                (e.currentTarget as HTMLElement).style.color = "var(--text)";
            }}
            onMouseLeave={(e) => {
              if (!pathname.startsWith("/settings/integrations"))
                (e.currentTarget as HTMLElement).style.color = "var(--text-muted)";
            }}
          >
            <Plug className="h-4 w-4 shrink-0" />
            Integrations
          </Link>
        )}

        <div className="flex items-center gap-2 px-3 py-1.5">
          <span
            className={cn(
              "h-1.5 w-1.5 rounded-full shrink-0",
              systemStatus === "operational" && "bg-emerald-500",
              systemStatus === "degraded"    && "bg-rose-500",
              systemStatus === "unknown"     && "bg-zinc-600",
            )}
          />
          <span className="text-[11px]" style={{ color: "var(--text-quiet)" }}>
            {systemStatus === "operational" ? "All systems operational"
             : systemStatus === "degraded"  ? "System degraded"
             : "Status unknown"}
          </span>
        </div>
      </div>
    </aside>
  );
}
