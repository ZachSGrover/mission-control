"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BookOpen,
  Bot,
  Brain,
  CalendarDays,
  Check,
  CloudUpload,
  FolderOpen,
  Gauge,
  GitBranch,
  Hammer,
  Heart,
  Layout,
  Loader2,
  MessageSquare,
  Network,
  Plug,
  Settings,
  Shield,
  Siren,
  TriangleAlert,
  Users,
  Wrench,
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

// ── Top-level nav link ────────────────────────────────────────────────────────

function NavLink({
  href,
  label,
  Icon,
  exact = false,
  description,
  testId,
}: {
  href: string;
  label: string;
  Icon: React.ElementType;
  exact?: boolean;
  /** Hover tooltip describing what this surface does. */
  description?: string;
  testId?: string;
}) {
  const pathname = usePathname();
  const active = exact ? pathname === href : pathname.startsWith(href);

  return (
    <Link
      href={href}
      title={description}
      data-testid={testId}
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

  const gitSave = useGitSave();
  const { role } = useRole();

  const settingsActive =
    pathname === "/settings" ||
    (pathname.startsWith("/settings") &&
      !pathname.startsWith("/settings/users") &&
      !pathname.startsWith("/settings/integrations"));

  const usersActive = pathname.startsWith("/settings/users");
  const integrationsActive = pathname.startsWith("/settings/integrations");
  const guideActive = pathname.startsWith("/guide");
  const securityActive = pathname.startsWith("/security");
  const usageActive = pathname.startsWith("/usage");

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

        {/* Chat — one unified assistant */}
        <NavSection label="Chat">
          <NavLink href="/chat" label="Chat" Icon={MessageSquare} exact />
        </NavSection>

        {/* Memory */}
        <NavSection label="Memory">
          <NavLink
            href="/projects"
            label="Projects"
            Icon={FolderOpen}
            description="Active initiatives, briefs, and ongoing work."
          />
          <NavLink
            href="/memory"
            label="Memory"
            Icon={Brain}
            exact
            description="Long-term notes the assistant should remember."
          />
          <NavLink
            href="/calendar"
            label="Calendar"
            Icon={CalendarDays}
            description="Time-based view of upcoming work and deadlines."
          />
        </NavSection>

        {/* Automation */}
        <NavSection label="Automation">
          <NavLink
            href="/hermes"
            label="Hermes"
            Icon={Siren}
            description="System guardian — alerts, health checks, on-call wiring."
          />
          <NavLink
            href="/boards"
            label="Boards"
            Icon={Layout}
            description="Planning and task boards (kanban-style)."
          />
          <NavLink
            href="/agents"
            label="Agents"
            Icon={Bot}
            description="AI workers that reason, build, or execute internal tasks."
          />
          <NavLink
            href="/control"
            label="Control"
            Icon={Network}
            description="Distributed device + agent control plane."
          />
          <NavLink
            href="/workflows"
            label="Workflows"
            Icon={GitBranch}
            description="Repeatable process flows and automations."
          />
          <NavLink
            href="/skills"
            label="Skills"
            Icon={Wrench}
            description="Reusable capability packs the assistant can install."
          />
          {/* Bots — operator role surface.  Visible to owner + operator only. */}
          {(role === "owner" || role === "operator") && (
            <NavLink
              href="/bots"
              label="Bots"
              Icon={Bot}
              description="Operational automations that run agency tasks."
              testId="nav-bots"
            />
          )}
          {(role === "owner" || role === "operator") && (
            <NavLink
              href="/bots/builder"
              label="Bot Builder"
              Icon={Hammer}
              description="Author bot specs (sandbox-only) for owner approval."
              testId="nav-bot-builder"
            />
          )}
          <NavLink
            href="/activity"
            label="Logs"
            Icon={Activity}
            description="Audit-friendly log feed.  Empty until events flow in."
          />
        </NavSection>

        {/* Business / Intelligence — analytics + spend products. */}
        <NavSection label="Business / Intelligence">
          <NavLink
            href="/of-intelligence"
            label="OnlyFans Intelligence"
            Icon={Heart}
            description="OF chatter QC + analytics."
          />
        </NavSection>

        {/* System */}
        <NavSection label="System">
          {/* Save — action button styled to match nav links */}
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
            <span className="truncate text-left">
              {gitSave.status === "saving" ? "Saving…" :
               gitSave.status === "saved"  ? "Saved" :
               gitSave.status === "error"  ? "Save failed — tap to dismiss" :
               "Save"}
            </span>
          </button>
          {gitSave.status === "error" && gitSave.message && (
            <p className="px-3 text-[11px] leading-snug text-red-400">{gitSave.message}</p>
          )}

          <Link
            href="/guide"
            className={cn(
              "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
              guideActive ? "font-medium" : "font-normal",
            )}
            style={
              guideActive
                ? { background: "var(--accent-soft)", color: "var(--accent-strong)" }
                : { color: "var(--text-muted)" }
            }
            onMouseEnter={(e) => {
              if (!guideActive) (e.currentTarget as HTMLElement).style.color = "var(--text)";
            }}
            onMouseLeave={(e) => {
              if (!guideActive) (e.currentTarget as HTMLElement).style.color = "var(--text-muted)";
            }}
          >
            <BookOpen className="h-4 w-4 shrink-0" />
            Guide
          </Link>

          <Link
            href="/settings"
            className={cn(
              "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
              settingsActive ? "font-medium" : "font-normal",
            )}
            style={
              settingsActive
                ? { background: "var(--accent-soft)", color: "var(--accent-strong)" }
                : { color: "var(--text-muted)" }
            }
            onMouseEnter={(e) => {
              if (!settingsActive) (e.currentTarget as HTMLElement).style.color = "var(--text)";
            }}
            onMouseLeave={(e) => {
              if (!settingsActive) (e.currentTarget as HTMLElement).style.color = "var(--text-muted)";
            }}
          >
            <Settings className="h-4 w-4 shrink-0" />
            Settings
          </Link>

          <Link
            href="/usage"
            data-testid="nav-usage"
            title="Token spend, model usage, and cost ceilings."
            className={cn(
              "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
              usageActive ? "font-medium" : "font-normal",
            )}
            style={
              usageActive
                ? { background: "var(--accent-soft)", color: "var(--accent-strong)" }
                : { color: "var(--text-muted)" }
            }
            onMouseEnter={(e) => {
              if (!usageActive) (e.currentTarget as HTMLElement).style.color = "var(--text)";
            }}
            onMouseLeave={(e) => {
              if (!usageActive) (e.currentTarget as HTMLElement).style.color = "var(--text-muted)";
            }}
          >
            <Gauge className="h-4 w-4 shrink-0" />
            Usage Tracker
          </Link>

          {role === "owner" && (
            <Link
              href="/settings/users"
              className={cn(
                "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
                usersActive ? "font-medium" : "font-normal",
              )}
              style={
                usersActive
                  ? { background: "var(--accent-soft)", color: "var(--accent-strong)" }
                  : { color: "var(--text-muted)" }
              }
              onMouseEnter={(e) => {
                if (!usersActive) (e.currentTarget as HTMLElement).style.color = "var(--text)";
              }}
              onMouseLeave={(e) => {
                if (!usersActive) (e.currentTarget as HTMLElement).style.color = "var(--text-muted)";
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
                integrationsActive ? "font-medium" : "font-normal",
              )}
              style={
                integrationsActive
                  ? { background: "var(--accent-soft)", color: "var(--accent-strong)" }
                  : { color: "var(--text-muted)" }
              }
              onMouseEnter={(e) => {
                if (!integrationsActive) (e.currentTarget as HTMLElement).style.color = "var(--text)";
              }}
              onMouseLeave={(e) => {
                if (!integrationsActive) (e.currentTarget as HTMLElement).style.color = "var(--text-muted)";
              }}
            >
              <Plug className="h-4 w-4 shrink-0" />
              Integrations
            </Link>
          )}

          {role === "owner" && (
            <Link
              href="/security"
              data-testid="nav-security"
              className={cn(
                "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
                securityActive ? "font-medium" : "font-normal",
              )}
              style={
                securityActive
                  ? { background: "var(--accent-soft)", color: "var(--accent-strong)" }
                  : { color: "var(--text-muted)" }
              }
              onMouseEnter={(e) => {
                if (!securityActive) (e.currentTarget as HTMLElement).style.color = "var(--text)";
              }}
              onMouseLeave={(e) => {
                if (!securityActive) (e.currentTarget as HTMLElement).style.color = "var(--text-muted)";
              }}
            >
              <Shield className="h-4 w-4 shrink-0" />
              Security
            </Link>
          )}
        </NavSection>

      </div>

      {/* ── Pinned bottom: status ────────────────────────────────────── */}
      <div
        className="shrink-0 px-3 pb-4 pt-2"
        style={{ borderTop: "1px solid var(--border)" }}
      >
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
