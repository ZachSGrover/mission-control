"use client";

import { useEffect } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  FileDiff,
  GitBranch,
  Globe,
  Loader2,
  MessageSquare,
  TriangleAlert,
  XCircle,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  type ChangedFile,
  type GitPreview,
  type PreviewState,
} from "@/hooks/use-git-preview";
import { type SaveState } from "@/hooks/use-git-save";

// ── Helpers ──────────────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, string> = {
  modified:  "rgb(250 204 21)",
  added:     "rgb(52 211 153)",
  deleted:   "rgb(248 113 113)",
  renamed:   "rgb(96 165 250)",
  copied:    "rgb(96 165 250)",
  untracked: "rgb(167 139 250)",
  unmerged:  "rgb(248 113 113)",
  ignored:   "rgb(148 163 184)",
  other:     "rgb(148 163 184)",
};

function StatusBadge({ status }: { status: string }) {
  const color = STATUS_COLORS[status] ?? STATUS_COLORS.other;
  return (
    <span
      className="text-[10px] font-medium uppercase tracking-wider px-1.5 py-0.5 rounded shrink-0"
      style={{ background: `${color}20`, color }}
    >
      {status}
    </span>
  );
}

// ── Section primitives ───────────────────────────────────────────────────────

function Section({ icon: Icon, title, children }: { icon: React.ElementType; title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-1.5">
        <Icon className="h-3.5 w-3.5" style={{ color: "var(--text-quiet)" }} />
        <p className="text-xs font-medium uppercase tracking-wider" style={{ color: "var(--text-quiet)" }}>
          {title}
        </p>
      </div>
      {children}
    </div>
  );
}

// ── Ready-state body ─────────────────────────────────────────────────────────

function PreviewBody({ preview }: { preview: GitPreview }) {
  return (
    <div className="flex flex-col gap-4">
      {/* Branch + remote */}
      <div className="grid grid-cols-2 gap-4">
        <Section icon={GitBranch} title="Current branch">
          <p className="text-sm font-mono" style={{ color: "var(--text)" }}>
            {preview.branch} <span style={{ color: "var(--text-quiet)" }}>→</span>{" "}
            <span style={{ color: "var(--accent-strong)" }}>{preview.willPushBranch}</span>
          </p>
        </Section>
        <Section icon={Globe} title="Remote">
          <p className="text-sm font-mono truncate" style={{ color: "var(--text)" }} title={preview.remote}>
            {preview.remote || <span style={{ color: "var(--text-quiet)" }}>(no remote)</span>}
          </p>
        </Section>
      </div>

      {/* Commit message */}
      <Section icon={MessageSquare} title="Commit message">
        <code
          className="block rounded-md border px-3 py-2 text-xs"
          style={{
            background: "var(--surface-2, var(--surface))",
            borderColor: "var(--border)",
            color: "var(--text)",
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          }}
        >
          {preview.commitMessage}
        </code>
      </Section>

      {/* Warning box — always shown */}
      <div
        className="rounded-md border p-3 flex items-start gap-2"
        style={{ background: "rgb(251 146 60 / 0.08)", borderColor: "rgb(251 146 60 / 0.35)" }}
      >
        <TriangleAlert className="h-4 w-4 mt-0.5 shrink-0" style={{ color: "rgb(251 146 60)" }} />
        <div className="text-xs leading-relaxed" style={{ color: "var(--text)" }}>
          <p className="font-medium mb-0.5">This will commit local code changes and push them to GitHub <code className="font-mono">{preview.willPushBranch}</code>.</p>
          <p style={{ color: "var(--text-muted)" }}>
            Runbooks and Sidebar layout are localStorage only — they are <strong>not</strong> included
            unless you&apos;ve exported them to repo files.
          </p>
        </div>
      </div>

      {/* Suspicious files warning */}
      {preview.suspiciousFiles.length > 0 && (
        <div
          className="rounded-md border p-3"
          style={{ background: "rgb(248 113 113 / 0.08)", borderColor: "rgb(248 113 113 / 0.35)" }}
        >
          <div className="flex items-center gap-2 mb-1.5">
            <AlertTriangle className="h-4 w-4 shrink-0" style={{ color: "rgb(248 113 113)" }} />
            <p className="text-xs font-medium" style={{ color: "rgb(248 113 113)" }}>
              {preview.suspiciousFiles.length} suspicious file
              {preview.suspiciousFiles.length === 1 ? "" : "s"} staged
            </p>
          </div>
          <ul className="text-xs space-y-1 pl-6 list-disc" style={{ color: "var(--text)" }}>
            {preview.suspiciousFiles.map((s) => (
              <li key={s.path}>
                <span className="font-mono">{s.path}</span>{" "}
                <span style={{ color: "var(--text-quiet)" }}>— {s.reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Changed files list */}
      <Section icon={FileDiff} title={`Changed files (${preview.changedFiles.length})`}>
        {preview.changedFiles.length === 0 ? (
          <p className="text-xs italic" style={{ color: "var(--text-quiet)" }}>
            Working tree clean. {preview.statusSummary}
          </p>
        ) : (
          <div
            className="rounded-md border max-h-48 overflow-auto"
            style={{ background: "var(--surface-2, var(--surface))", borderColor: "var(--border)" }}
          >
            <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
              {preview.changedFiles.map((cf: ChangedFile) => (
                <li key={cf.path} className="flex items-center gap-2 px-3 py-1.5">
                  <StatusBadge status={cf.status} />
                  <span className="text-xs font-mono truncate flex-1" style={{ color: "var(--text)" }} title={cf.path}>
                    {cf.path}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Section>

      {/* Diff stat */}
      {preview.diffStat && (
        <Section icon={FileDiff} title="Diff summary">
          <pre
            className="rounded-md border p-3 text-xs max-h-40 overflow-auto"
            style={{
              background: "var(--surface-2, var(--surface))",
              borderColor: "var(--border)",
              color: "var(--text)",
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
            }}
          >
            {preview.diffStat}
          </pre>
        </Section>
      )}
    </div>
  );
}

// ── Modal ────────────────────────────────────────────────────────────────────

export function SavePreviewModal({
  open,
  onOpenChange,
  previewState,
  saveState,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  previewState: PreviewState;
  saveState: SaveState;
  onConfirm: () => void;
}) {
  const { status, preview, error, load } = previewState;

  // Load on open
  useEffect(() => {
    if (open && status === "idle") {
      void load();
    }
  }, [open, status, load]);

  const hasChanges = preview?.hasChanges ?? false;
  const canConfirm = status === "ready" && hasChanges && saveState.status !== "saving";
  const saving = saveState.status === "saving";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Save to GitHub</DialogTitle>
        </DialogHeader>

        <p className="text-sm -mt-1 mb-1" style={{ color: "var(--text-muted)" }}>
          Review changes before committing and pushing to <code className="font-mono">main</code>.
        </p>

        <div className="max-h-[60vh] overflow-auto pr-1">
          {status === "loading" && (
            <div className="flex items-center gap-2 py-8 justify-center" style={{ color: "var(--text-muted)" }}>
              <Loader2 className="h-4 w-4 animate-spin" />
              <span className="text-sm">Loading preview…</span>
            </div>
          )}

          {status === "error" && (
            <div
              className="rounded-md border p-4 flex items-start gap-2"
              style={{ background: "rgb(248 113 113 / 0.08)", borderColor: "rgb(248 113 113 / 0.35)" }}
            >
              <XCircle className="h-4 w-4 mt-0.5 shrink-0" style={{ color: "rgb(248 113 113)" }} />
              <div className="text-sm" style={{ color: "var(--text)" }}>
                <p className="font-medium mb-1">Preview failed</p>
                <p style={{ color: "var(--text-muted)" }}>{error}</p>
              </div>
            </div>
          )}

          {status === "ready" && preview && !hasChanges && (
            <div
              className="rounded-md border p-4 flex items-start gap-2"
              style={{ background: "rgb(52 211 153 / 0.08)", borderColor: "rgb(52 211 153 / 0.35)" }}
            >
              <CheckCircle2 className="h-4 w-4 mt-0.5 shrink-0" style={{ color: "rgb(52 211 153)" }} />
              <div className="text-sm" style={{ color: "var(--text)" }}>
                <p className="font-medium mb-1">No changes to save</p>
                <p style={{ color: "var(--text-muted)" }}>
                  Working tree is clean and up to date with <code className="font-mono">{preview.willPushBranch}</code>.
                </p>
              </div>
            </div>
          )}

          {status === "ready" && preview && hasChanges && <PreviewBody preview={preview} />}
        </div>

        <DialogFooter>
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button
            size="sm"
            disabled={!canConfirm}
            onClick={() => {
              onConfirm();
              onOpenChange(false);
            }}
            title={
              !hasChanges
                ? "Nothing to save"
                : status !== "ready"
                  ? "Waiting for preview"
                  : "Commit all staged changes and push to GitHub"
            }
          >
            {saving ? (
              <>
                <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
                Saving…
              </>
            ) : (
              "Confirm Save to GitHub"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
