"use client";

import { useCallback, useState } from "react";
import { Eye, EyeOff } from "lucide-react";

import { useAuthFetch } from "@/hooks/use-auth-fetch";

import {
  removeOpenAiCredentials,
  saveOpenAiCredentials,
} from "../_lib/api";
import type { UsageSettings } from "../_lib/types";

interface OpenAiCredentialsCardProps {
  settings: UsageSettings | null;
  onChanged: () => void;
}

/**
 * Editable card for the OpenAI Admin Usage credentials.
 *
 * The admin key is masked at all times once saved — the input itself is
 * cleared after a successful save so the raw value never round-trips
 * through the DOM after submission.  The org id is a public identifier
 * (`org-…`), so it is shown in full alongside its input.
 */
export function OpenAiCredentialsCard({
  settings,
  onChanged,
}: OpenAiCredentialsCardProps) {
  const { fetchWithAuth } = useAuthFetch();
  const [adminKeyInput, setAdminKeyInput] = useState("");
  const [orgIdInput, setOrgIdInput] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [busy, setBusy] = useState<"idle" | "saving" | "removing">("idle");
  const [feedback, setFeedback] = useState<{ ok: boolean; msg: string } | null>(
    null,
  );

  const flash = useCallback((ok: boolean, msg: string) => {
    setFeedback({ ok, msg });
    setTimeout(() => setFeedback(null), 4000);
  }, []);

  const adminConfigured = !!settings?.openai_admin_configured;
  const adminPreview = settings?.openai_admin_preview ?? null;
  const adminSource = settings?.openai_admin_source ?? "none";
  const orgIdSet = !!settings?.openai_org_id_set;
  const orgIdValue = settings?.openai_org_id_value ?? null;
  const orgIdSource = settings?.openai_org_id_source ?? "none";

  const handleSave = useCallback(async () => {
    if (busy !== "idle") return;
    const trimmedKey = adminKeyInput.trim();
    const trimmedOrg = orgIdInput.trim();
    if (!trimmedKey && !trimmedOrg) {
      flash(false, "Enter an admin key, an organization ID, or both before saving.");
      return;
    }
    setBusy("saving");
    try {
      const payload: { admin_key?: string; org_id?: string } = {};
      if (trimmedKey) payload.admin_key = trimmedKey;
      if (trimmedOrg) payload.org_id = trimmedOrg;
      await saveOpenAiCredentials(fetchWithAuth, payload);
      // Clear inputs immediately so the raw key is not retained anywhere
      // visible (DOM, React state, devtools snapshots).
      setAdminKeyInput("");
      setOrgIdInput("");
      setShowKey(false);
      flash(true, "Saved.");
      onChanged();
    } catch (e) {
      flash(false, e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy("idle");
    }
  }, [adminKeyInput, busy, fetchWithAuth, flash, onChanged, orgIdInput]);

  const handleRemove = useCallback(async () => {
    if (busy !== "idle") return;
    if (!adminConfigured && !orgIdSet) {
      flash(false, "Nothing to remove — no credentials configured.");
      return;
    }
    setBusy("removing");
    try {
      await removeOpenAiCredentials(fetchWithAuth);
      setAdminKeyInput("");
      setOrgIdInput("");
      flash(true, "Removed.");
      onChanged();
    } catch (e) {
      flash(false, e instanceof Error ? e.message : "Remove failed");
    } finally {
      setBusy("idle");
    }
  }, [adminConfigured, busy, fetchWithAuth, flash, onChanged, orgIdSet]);

  const saveDisabled = busy !== "idle";
  const removeDisabled =
    busy !== "idle" || (!adminConfigured && !orgIdSet);

  return (
    <div
      className="rounded-xl p-5 space-y-4"
      style={{
        background: "var(--surface-strong)",
        border: "1px solid var(--border)",
      }}
    >
      <div>
        <h3
          className="text-base font-semibold"
          style={{ color: "var(--text)" }}
        >
          OpenAI Usage Tracking
        </h3>
        <p
          className="mt-1 text-xs leading-relaxed"
          style={{ color: "var(--text-muted)" }}
        >
          Used <strong>only</strong> to fetch usage and cost reports from the
          OpenAI Admin API. This is <strong>not</strong> your normal OpenAI
          API key — create a dedicated admin key with the &ldquo;Usage and
          cost&rdquo; read scope at{" "}
          <a
            href="https://platform.openai.com/settings/organization/admin-keys"
            target="_blank"
            rel="noreferrer"
            className="underline"
            style={{ color: "var(--accent-strong)" }}
          >
            platform.openai.com → Admin keys
          </a>
          . Stored encrypted in Mission Control; never logged in full.
        </p>
      </div>

      {/* Admin key */}
      <div className="space-y-1.5">
        <label className="block">
          <span className="text-xs font-medium" style={{ color: "var(--text)" }}>
            Admin key
          </span>
        </label>
        <StatusLine
          configured={adminConfigured}
          source={adminSource}
          previewLabel={adminPreview ?? undefined}
          previewSecret
        />
        <div className="flex items-stretch gap-2">
          <div className="flex-1 relative">
            <input
              type={showKey ? "text" : "password"}
              autoComplete="off"
              spellCheck={false}
              value={adminKeyInput}
              onChange={(e) => setAdminKeyInput(e.target.value)}
              placeholder={
                adminConfigured
                  ? "Enter a new admin key to replace the saved one"
                  : "sk-admin-..."
              }
              disabled={busy !== "idle"}
              className="w-full rounded-lg px-3 py-2 pr-10 text-sm font-mono focus:outline-none disabled:opacity-50"
              style={{
                background: "var(--surface-muted, var(--surface))",
                border: "1px solid var(--border-strong, var(--border))",
                color: "var(--text)",
              }}
            />
            {adminKeyInput && (
              <button
                type="button"
                onClick={() => setShowKey((s) => !s)}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded"
                style={{ color: "var(--text-quiet)" }}
                aria-label={showKey ? "Hide key" : "Show key"}
                title={showKey ? "Hide key" : "Show key"}
              >
                {showKey ? (
                  <EyeOff className="h-4 w-4" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Organization ID */}
      <div className="space-y-1.5">
        <label className="block">
          <span className="text-xs font-medium" style={{ color: "var(--text)" }}>
            Organization ID
          </span>
        </label>
        <StatusLine
          configured={orgIdSet}
          source={orgIdSource}
          // Org IDs are public identifiers — surface in full.
          previewLabel={orgIdValue ?? undefined}
          previewSecret={false}
        />
        <input
          type="text"
          autoComplete="off"
          spellCheck={false}
          value={orgIdInput}
          onChange={(e) => setOrgIdInput(e.target.value)}
          placeholder={
            orgIdSet ? "Enter a new org ID to replace the saved one" : "org-..."
          }
          disabled={busy !== "idle"}
          className="w-full rounded-lg px-3 py-2 text-sm font-mono focus:outline-none disabled:opacity-50"
          style={{
            background: "var(--surface-muted, var(--surface))",
            border: "1px solid var(--border-strong, var(--border))",
            color: "var(--text)",
          }}
        />
      </div>

      <div className="flex items-center justify-between gap-3 pt-1">
        <p
          className="text-xs"
          style={{
            color: feedback
              ? feedback.ok
                ? "#22c55e"
                : "#ef4444"
              : "var(--text-quiet)",
          }}
        >
          {feedback?.msg ?? ""}
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void handleRemove()}
            disabled={removeDisabled}
            className="rounded-lg px-3 py-2 text-sm transition-opacity disabled:opacity-40"
            style={{
              background: "transparent",
              border: "1px solid var(--border)",
              color: "var(--text-muted)",
            }}
          >
            {busy === "removing" ? "Removing…" : "Remove"}
          </button>
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={saveDisabled}
            className="rounded-lg px-4 py-2 text-sm font-medium text-white transition-opacity disabled:opacity-40"
            style={{ background: "var(--accent)" }}
          >
            {busy === "saving" ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

function StatusLine({
  configured,
  source,
  previewLabel,
  previewSecret,
}: {
  configured: boolean;
  source: "db" | "env" | "none";
  previewLabel?: string;
  previewSecret: boolean;
}) {
  if (!configured) {
    return (
      <p className="text-[11px]" style={{ color: "var(--text-quiet)" }}>
        Status:{" "}
        <span style={{ color: "var(--text-muted)" }}>Not configured</span>
      </p>
    );
  }
  const sourceLabel =
    source === "db" ? "saved" : source === "env" ? "from .env" : "configured";
  return (
    <p className="text-[11px]" style={{ color: "var(--text-quiet)" }}>
      Status:{" "}
      <span style={{ color: "#22c55e" }}>Configured ({sourceLabel})</span>
      {previewLabel && (
        <>
          {" · "}
          <span
            className="font-mono"
            style={{ color: previewSecret ? "var(--text-muted)" : "var(--text)" }}
          >
            {previewLabel}
          </span>
        </>
      )}
    </p>
  );
}
