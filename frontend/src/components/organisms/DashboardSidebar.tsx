"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BookOpen,
  Bot,
  Brain,
  CalendarDays,
  Check,
  Circle,
  ClipboardList,
  CloudUpload,
  Folder,
  FolderOpen,
  GitBranch,
  Hash,
  Layout,
  Loader2,
  MessageSquare,
  Network,
  Pin,
  Plug,
  Settings,
  Settings2,
  Star,
  TriangleAlert,
  Users,
  Wrench,
} from "lucide-react";

import { ApiError } from "@/api/mutator";
import {
  type healthzHealthzGetResponse,
  useHealthzHealthzGet,
} from "@/api/generated/default/default";
import { ManageSidebar } from "@/components/organisms/ManageSidebar";
import { SavePreviewModal } from "@/components/organisms/SavePreviewModal";
import { useGitPreview } from "@/hooks/use-git-preview";
import { useGitSave } from "@/hooks/use-git-save";
import { useRole } from "@/hooks/use-role";
import {
  loadLayout,
  saveLayout,
  type SidebarIconKey,
  type SidebarItemDef,
  type SidebarLayout,
} from "@/lib/sidebar-store";
import { cn } from "@/lib/utils";

// ── Icon registry ────────────────────────────────────────────────────────────

const ICON_REGISTRY: Record<SidebarIconKey, React.ElementType> = {
  MessageSquare,
  FolderOpen,
  Brain,
  CalendarDays,
  Layout,
  Bot,
  Network,
  GitBranch,
  Wrench,
  ClipboardList,
  Activity,
  BookOpen,
  Settings,
  Users,
  Plug,
  Circle,
  Star,
  Pin,
  Hash,
  Folder,
  CloudUpload,
};

function resolveIcon(key: SidebarIconKey): React.ElementType {
  return ICON_REGISTRY[key] ?? Hash;
}

// ── Active matching ──────────────────────────────────────────────────────────

function isItemActive(item: SidebarItemDef, pathname: string): boolean {
  if (item.activeMode === "exact") return pathname === item.href;
  if (!pathname.startsWith(item.href)) return false;
  if (item.excludePrefixes?.some((p) => pathname.startsWith(p))) return false;
  return true;
}

// ── Section label ────────────────────────────────────────────────────────────

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

// ── Nav link ─────────────────────────────────────────────────────────────────

function NavLink({
  href,
  label,
  Icon,
  active,
}: {
  href: string;
  label: string;
  Icon: React.ElementType;
  active: boolean;
}) {
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

// ── Save action button (Git commit + push to GitHub) ────────────────────────
// Rendered when an item has `kind: "action"` and `actionKey: "git-save"`.
// The item is stored in the sidebar layout, so its label/position/icon are
// user-customizable — but the action itself (POST /api/v1/git/save) is fixed.

function SaveButton({ label, Icon }: { label: string; Icon: React.ElementType }) {
  const gitSave = useGitSave();
  const gitPreview = useGitPreview();
  const [previewOpen, setPreviewOpen] = useState(false);

  const handleClick = () => {
    if (gitSave.status === "error") {
      gitSave.reset();
      return;
    }
    if (gitSave.status === "saving") return;
    // Always open the preview modal first — never commit/push without confirmation.
    gitPreview.reset();
    setPreviewOpen(true);
  };

  return (
    <>
      <button
        type="button"
        onClick={handleClick}
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
        title={gitSave.message || `${label} to GitHub (preview first)`}
      >
        {gitSave.status === "saving" && <Loader2 className="h-4 w-4 shrink-0 animate-spin" />}
        {gitSave.status === "saved"  && <Check className="h-4 w-4 shrink-0" />}
        {gitSave.status === "error"  && <TriangleAlert className="h-4 w-4 shrink-0" />}
        {gitSave.status === "idle"   && <Icon className="h-4 w-4 shrink-0" />}
        <span className="truncate text-left">
          {gitSave.status === "saving" ? "Saving…" :
           gitSave.status === "saved"  ? "Saved" :
           gitSave.status === "error"  ? "Save failed — tap to dismiss" :
           label}
        </span>
      </button>
      {gitSave.status === "error" && gitSave.message && (
        <p className="px-3 text-[11px] leading-snug text-red-400">{gitSave.message}</p>
      )}
      <SavePreviewModal
        open={previewOpen}
        onOpenChange={setPreviewOpen}
        previewState={gitPreview}
        saveState={gitSave}
        onConfirm={() => { void gitSave.save(); }}
      />
    </>
  );
}

// ── Sidebar ──────────────────────────────────────────────────────────────────

export function DashboardSidebar() {
  const pathname = usePathname();
  const { role } = useRole();

  // Start from seed (deterministic for SSR); load from localStorage after mount.
  const [layout, setLayout] = useState<SidebarLayout>(() => loadLayout());
  const [manageOpen, setManageOpen] = useState(false);

  useEffect(() => {
    // Re-load on mount to pick up client-side localStorage (SSR may have seeded only).
    setLayout(loadLayout());
  }, []);

  const handleLayoutChange = (next: SidebarLayout) => {
    setLayout(next);
    saveLayout(next);
  };

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

  const visibleCategories = useMemo(() => {
    return layout.categories.map((cat) => {
      const items = cat.items.filter((it) => {
        if (it.hidden) return false;
        if (it.requireRole === "owner" && role !== "owner") return false;
        return true;
      });
      return { ...cat, items };
    });
  }, [layout, role]);

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
        {visibleCategories.map((cat) => {
          if (cat.items.length === 0) return null;
          return (
            <NavSection key={cat.id} label={cat.label}>
              {cat.items.map((it) => {
                const Icon = resolveIcon(it.iconKey);
                if (it.kind === "action" && it.actionKey === "git-save") {
                  return <SaveButton key={it.id} label={it.label} Icon={Icon} />;
                }
                return (
                  <NavLink
                    key={it.id}
                    href={it.href}
                    label={it.label}
                    Icon={Icon}
                    active={isItemActive(it, pathname)}
                  />
                );
              })}
            </NavSection>
          );
        })}
      </div>

      {/* ── Pinned bottom: status + manage ──────────────────────────── */}
      <div
        className="shrink-0 px-3 pb-4 pt-2"
        style={{ borderTop: "1px solid var(--border)" }}
      >
        <div className="flex items-center justify-between gap-2 px-3 py-1.5">
          <div className="flex items-center gap-2 min-w-0">
            <span
              className={cn(
                "h-1.5 w-1.5 rounded-full shrink-0",
                systemStatus === "operational" && "bg-emerald-500",
                systemStatus === "degraded"    && "bg-rose-500",
                systemStatus === "unknown"     && "bg-zinc-600",
              )}
            />
            <span className="text-[11px] truncate" style={{ color: "var(--text-quiet)" }}>
              {systemStatus === "operational" ? "All systems operational"
               : systemStatus === "degraded"  ? "System degraded"
               : "Status unknown"}
            </span>
          </div>
          <button
            type="button"
            onClick={() => setManageOpen(true)}
            title="Manage sidebar"
            className="shrink-0 rounded p-1 transition-colors"
            style={{ color: "var(--text-quiet)" }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = "var(--text)"; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = "var(--text-quiet)"; }}
          >
            <Settings2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <ManageSidebar
        open={manageOpen}
        onOpenChange={setManageOpen}
        layout={layout}
        onLayoutChange={handleLayoutChange}
      />
    </aside>
  );
}
