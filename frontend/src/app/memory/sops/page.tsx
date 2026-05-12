"use client";

export const dynamic = "force-dynamic";

import { BookOpen, ClipboardList, Sparkles, TriangleAlert } from "lucide-react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { CopyButton } from "@/components/hermes/CopyButton";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";

// ── Content ──────────────────────────────────────────────────────────────────
//
// SOPs are hardcoded in v1 (per spec: "it is okay to hardcode SOP cards in
// the frontend if no SOP backend exists. Do not overbuild a database right
// now.") When a SOPs API lands later, swap the SOPS / PROMPTS arrays for a
// fetch and keep the card components identical.

const LAST_UPDATED = "2026-05-12";

interface SOP {
  id: string;
  title: string;
  description: string;
  body: string;
  updated: string;
}

interface Prompt {
  id: string;
  title: string;
  description: string;
  body: string;
  updated: string;
}

const SOPS: SOP[] = [
  {
    id: "coo-builder",
    title: "COO Builder SOP",
    description:
      "How to build inside Mission Control without breaking production or waiting on owner approval for every normal action.",
    updated: LAST_UPDATED,
    body: `Mission Control Build SOP

1. Do not build directly on main.
2. Every project gets its own branch.

Branch examples:
  coo/rt-bot
  coo/chat-qc-dashboard
  coo/client-tracker
  coo/content-tool
  coo/project-name

3. Build everything inside that branch.

4. You can freely build:
  bots
  workflows
  tools
  frontend pages
  backend routes
  dashboards
  Modern Sales Agency systems
  client systems
  internal automations
  safe dry-run logic

5. Do not commit:
  API keys
  passwords
  cookies
  login sessions
  client private data
  .env files
  tokens
  secrets

6. Do not touch without owner approval:
  Render production settings
  Clerk
  Cloudflare
  DNS
  billing
  auth/security
  user roles
  production database
  migrations
  secrets
  main branch direct push
  real OnlyFans
  real OnlyMonster

7. Any bot or workflow that sends messages, posts, scrapes, logs in, deletes,
   or touches an external platform must have dry-run mode first.

8. Before pushing, run the safety check.

9. Push your branch to GitHub.

10. Open a pull request into main.

11. If GitHub checks pass and no restricted files were touched, the work
    can be merged.

12. Once merged into main, Render deploys the live Mission Control app.

Normal building does not need Zach approval.
Risky production, security, secrets, billing, auth, database, and
external platform actions do.`,
  },
  {
    id: "github-branch-workflow",
    title: "GitHub Branch Workflow",
    description:
      "The safe-by-default workflow for moving from a feature idea to a merged PR.",
    updated: LAST_UPDATED,
    body: `A branch is a safe workspace where you can build without touching the live app.

Workflow:
1. Pull the latest main.
2. Create a new branch.
3. Build your feature.
4. Test locally.
5. Run safety check.
6. Push your branch.
7. Open a pull request.
8. Wait for checks.
9. Merge only when checks pass.

Branch naming:
  coo/name-of-project
  coo/fix-name
  coo/tool-name
  coo/bot-name
  coo/workflow-name

Never push unfinished experiments directly to main.`,
  },
  {
    id: "safety-rules",
    title: "Safety Rules",
    description:
      "Which actions are safe to ship on a feature branch, which need review, and which are blocked without owner approval.",
    updated: LAST_UPDATED,
    body: `Safe to build:
  UI pages
  internal dashboards
  tools in dry-run mode
  bot drafts
  workflow drafts
  local tests
  documentation
  SOPs
  frontend improvements
  non-sensitive backend routes

Review needed:
  database migrations
  auth changes
  role changes
  permissions
  external platform integrations
  Discord routing
  Telegram routing
  GitHub workflows
  Render config
  deployment scripts

Blocked without owner approval:
  secrets
  API keys
  .env files
  billing
  Cloudflare
  Clerk
  DNS
  production database destructive changes
  deleting client data
  real OnlyFans connection
  real OnlyMonster connection
  sending/posting externally without dry-run`,
  },
  {
    id: "bot-workflow-rules",
    title: "Bot / Workflow Build Rules",
    description:
      "Every bot or workflow must be safe by default. Twelve required fields and one hard rule about external platforms.",
    updated: LAST_UPDATED,
    body: `Bots and workflows must start safe.

Every bot/workflow needs:
1. Name
2. Purpose
3. Owner
4. Project
5. Inputs
6. Outputs
7. Dry-run mode
8. Logs
9. Error handling
10. Clear safe/unsafe actions
11. Setup requirements
12. Test instructions

If it sends, posts, scrapes, logs in, deletes, or touches a platform,
it must be dry-run first.

No bot should post to Discord, Telegram, X, Reddit, OnlyFans,
OnlyMonster, or any external platform unless that behavior is
explicitly enabled and permission-gated.`,
  },
  {
    id: "render-deployment",
    title: "Render Deployment Rules",
    description:
      "What COO/builders can and cannot do with the production Render deployment.",
    updated: LAST_UPDATED,
    body: `Render production should deploy from main only.

COO/builders can:
  view logs if permitted
  test branches
  build features
  open PRs
  fix bugs

COO/builders should not:
  change production environment variables
  delete services
  change build commands
  change start commands
  change production database settings
  manually redeploy random branches to production

Production changes should come through main after safety checks.`,
  },
];

const PROMPTS: Prompt[] = [
  {
    id: "start-feature-branch",
    title: "Start a Safe Mission Control Feature Branch",
    description:
      "Paste at the start of any new feature. Forces the assistant to plan before changing code.",
    updated: LAST_UPDATED,
    body: `You are working inside the Mission Control / Digidle OS repo.

Do not work directly on main.
Do not touch secrets.
Do not change production env vars.
Do not deploy.
Do not push to main.
Do not connect real OnlyFans.
Do not connect real OnlyMonster.
Do not run external platform actions.

Goal:
Create a safe feature branch for this work.

Task:
1. Pull latest main.
2. Create a new branch named:
   PASTE_BRANCH_NAME_HERE

3. Inspect the repo structure.
4. Tell me where this feature should live.
5. Do not make code changes until you explain the plan.

Return:
  current branch
  new branch created
  where you plan to build
  any risks`,
  },
  {
    id: "build-safe-bot-tool",
    title: "Build a Safe Bot or Tool",
    description:
      "Paste when you want the assistant to add a new bot or tool with dry-run + logs + setup, without touching external services.",
    updated: LAST_UPDATED,
    body: `You are building a bot/tool inside Mission Control / Digidle OS.

Do not rebuild from scratch.
Do not touch secrets.
Do not deploy.
Do not push to main.
Do not run live external actions.
Do not connect real OnlyFans.
Do not connect real OnlyMonster.
Do not send Discord, Telegram, X, Reddit, OnlyFans, or OnlyMonster messages.

Build this as safe by default.

Requirements:
1. Add the bot/tool in the correct existing section.
2. Include dry-run mode.
3. Include logs.
4. Include clear setup requirements.
5. Include status.
6. Do not expose secrets in frontend.
7. Do not run real external actions.
8. Add test instructions.
9. Run local checks.
10. Stop before merging or deploying.

Return:
  what you built
  files changed
  how to test
  what is safe
  what is blocked
  whether ready for PR`,
  },
  {
    id: "safety-check",
    title: "Run Safety Check Before Pushing",
    description:
      "Paste right before pushing. The assistant audits the branch for secrets, auth/security, and external-platform code.",
    updated: LAST_UPDATED,
    body: `Before pushing this Mission Control branch, run a safety review.

Do not deploy.
Do not push to main.
Do not print secrets.

Check:
1. Current branch
2. Git status
3. Files changed
4. Any .env files staged
5. Any API keys or tokens
6. Any auth/security changes
7. Any database/migration changes
8. Any Render/Clerk/Cloudflare changes
9. Any external platform actions
10. Any OnlyFans or OnlyMonster code
11. Any destructive commands
12. Whether dry-run mode exists if needed

Run the repo safety check if available.

Return:
  SAFE, REVIEW NEEDED, or BLOCKED.

Include:
  reason
  files that need review
  whether this can be pushed as a branch
  whether this can be merged to main`,
  },
  {
    id: "pr-summary",
    title: "Open Pull Request Summary",
    description:
      "Paste to produce a clean PR summary covering what changed, how to test, and the safety posture.",
    updated: LAST_UPDATED,
    body: `Write a clean pull request summary for this Mission Control branch.

Include:
1. What changed
2. Why it changed
3. How to test
4. Screenshots needed yes/no
5. Safety notes
6. Does it touch secrets
7. Does it touch auth/security
8. Does it touch database/migrations
9. Does it touch external platform actions
10. Does it touch OnlyFans or OnlyMonster
11. Is there dry-run mode
12. Rollback plan

Keep it clear and short.`,
  },
  {
    id: "import-existing-code",
    title: "Import Existing COO Code Safely",
    description:
      "Paste when bringing in code from outside the repo. Forces inspection before any execution.",
    updated: LAST_UPDATED,
    body: `You are importing existing COO-built code into Mission Control safely.

Do not rebuild from scratch.
Do not deploy.
Do not push to main.
Do not touch secrets.
Do not run live external actions.
Do not connect real OnlyFans.
Do not connect real OnlyMonster.
Do not send Discord, Telegram, X, Reddit, OnlyFans, or OnlyMonster messages.
Do not run destructive commands.

The files are located here:
  PASTE_FILE_PATH_HERE

Task:
1. Copy/import files into:
   incoming/coo-import/

2. Inspect everything before running anything.
3. Identify:
   file structure
   languages used
   what it does
   how it runs
   inputs
   outputs
   API keys needed
   external services touched
   safety risks
   where it belongs in Mission Control

4. If safe, wrap it as:
   Tool, Bot, Workflow, Agent, or Modern Sales Agency page.

5. Add dry-run mode first.
6. Add logs.
7. Do not expose secrets.
8. Do not run unsafe external actions.

Return:
  what was imported
  where it was added
  files changed
  how to test
  safety risks
  whether ready for PR`,
  },
];

const EMERGENCY_PROMPT: Prompt = {
  id: "emergency-debug",
  title: "Emergency Debug Prompt",
  description:
    "Paste when something breaks. Forces the smallest safe fix without rebuilds or production changes.",
  updated: LAST_UPDATED,
  body: `You are debugging Mission Control.

Do not rebuild from scratch.
Do not deploy.
Do not push to main.
Do not touch secrets.
Do not change production settings.

Find the exact error.
Identify the exact file.
Make the smallest safe fix.
Run local tests.
Return what broke, what changed, and whether it is safe.`,
};

const EMERGENCY_RULES_BODY = `If something breaks:
1. Stop working.
2. Do not push to main.
3. Do not deploy.
4. Do not change env vars.
5. Save the error message.
6. Run a read-only diagnosis.
7. Ask Claude to identify the exact file and cause.
8. Fix only the broken thing.
9. Test locally.
10. Push only after safety checks pass.`;

// ── Cards ────────────────────────────────────────────────────────────────────

function SectionHeading({
  Icon,
  label,
  hint,
}: {
  Icon: React.ElementType;
  label: string;
  hint?: string;
}) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <Icon className="h-4 w-4" style={{ color: "var(--text-muted)" }} />
      <h2
        className="text-xs font-semibold uppercase tracking-widest"
        style={{ color: "var(--text-quiet)" }}
      >
        {label}
      </h2>
      {hint && (
        <span className="text-[11px]" style={{ color: "var(--text-quiet)" }}>
          — {hint}
        </span>
      )}
    </div>
  );
}

function SopCard({ sop }: { sop: SOP }) {
  return (
    <article
      className="rounded-xl p-4 space-y-3"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
      }}
      data-testid={`sop-card-${sop.id}`}
    >
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold" style={{ color: "var(--text)" }}>
            {sop.title}
          </h3>
          <p
            className="mt-1 text-xs leading-relaxed"
            style={{ color: "var(--text-muted)" }}
          >
            {sop.description}
          </p>
        </div>
        <CopyButton text={sop.body} ariaLabel={`Copy ${sop.title}`} />
      </header>

      <pre
        className="overflow-x-auto rounded-lg p-3 text-xs leading-relaxed whitespace-pre-wrap font-mono"
        style={{
          background: "var(--surface-strong)",
          border: "1px solid var(--border)",
          color: "var(--text)",
        }}
      >
        {sop.body}
      </pre>

      <footer className="text-[11px]" style={{ color: "var(--text-quiet)" }}>
        Last updated {sop.updated}
      </footer>
    </article>
  );
}

function PromptCard({ prompt }: { prompt: Prompt }) {
  return (
    <article
      className="rounded-xl p-4 space-y-3"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
      }}
      data-testid={`prompt-card-${prompt.id}`}
    >
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold" style={{ color: "var(--text)" }}>
            {prompt.title}
          </h3>
          <p
            className="mt-1 text-xs leading-relaxed"
            style={{ color: "var(--text-muted)" }}
          >
            {prompt.description}
          </p>
        </div>
        <CopyButton text={prompt.body} ariaLabel={`Copy ${prompt.title}`} />
      </header>

      <pre
        className="overflow-x-auto rounded-lg p-3 text-xs leading-relaxed whitespace-pre-wrap font-mono"
        style={{
          background: "var(--surface-strong)",
          border: "1px solid var(--border)",
          color: "var(--text)",
        }}
      >
        {prompt.body}
      </pre>

      <footer className="text-[11px]" style={{ color: "var(--text-quiet)" }}>
        Last updated {prompt.updated}
      </footer>
    </article>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

function SOPsContent() {
  return (
    <main className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-3xl px-6 py-8 space-y-10">
        <header className="space-y-2">
          <h1 className="text-xl font-semibold" style={{ color: "var(--text)" }}>
            Standard Operating Procedures
          </h1>
          <p
            className="text-sm leading-relaxed"
            style={{ color: "var(--text-muted)" }}
          >
            Safety rails for the COO and team. Build freely on a branch, ship
            through GitHub checks, and only loop the owner in for production,
            security, billing, and live external platforms. Every section has a
            Copy button so the rules can be pasted into Claude or a runbook.
          </p>
        </header>

        <section>
          <SectionHeading Icon={BookOpen} label="SOPs" hint="copy the rules into any session" />
          <div className="space-y-4">
            {SOPS.map((sop) => (
              <SopCard key={sop.id} sop={sop} />
            ))}
          </div>
        </section>

        <section>
          <SectionHeading
            Icon={Sparkles}
            label="Claude prompt library"
            hint="paste before kicking off a task"
          />
          <div className="space-y-4">
            {PROMPTS.map((prompt) => (
              <PromptCard key={prompt.id} prompt={prompt} />
            ))}
          </div>
        </section>

        <section>
          <SectionHeading
            Icon={TriangleAlert}
            label="Emergency"
            hint="if something breaks"
          />
          <div className="space-y-4">
            <SopCard
              sop={{
                id: "emergency-rules",
                title: "Emergency Rules",
                description:
                  "Ten steps the second something breaks. The first three are all variants of: stop pushing.",
                body: EMERGENCY_RULES_BODY,
                updated: LAST_UPDATED,
              }}
            />
            <PromptCard prompt={EMERGENCY_PROMPT} />
          </div>
        </section>

        <footer
          className="rounded-xl p-4 text-xs leading-relaxed"
          style={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            color: "var(--text-muted)",
          }}
        >
          <p>
            <ClipboardList
              className="inline-block h-3 w-3 mr-1 align-middle"
              style={{ color: "var(--text-quiet)" }}
            />
            SOPs are hardcoded in v1. When the SOP backend lands, the cards will
            pull from a versioned store but the layout stays the same.
          </p>
        </footer>
      </div>
    </main>
  );
}

export default function SOPsPage() {
  return (
    <DashboardShell>
      <DashboardSidebar />
      <SignedIn>
        <SOPsContent />
      </SignedIn>
      <SignedOut>
        <SignedOutPanel
          message="Sign in to read Mission Control SOPs"
          forceRedirectUrl="/memory/sops"
        />
      </SignedOut>
    </DashboardShell>
  );
}
