// SOP and Claude-prompt content for the Memory → SOPs page (v4 folder layout).
//
// Shape: four top-level "folders" (Mission Control Build, Import Existing
// Code, Safety Rules, Emergency Debug). Mission Control Build is the main
// operating manual — five numbered steps plus three smaller "what's next"
// cards (Open PR, Fix failed checks, Continue later). The other three folders
// each have an intro block plus a single prompt card.
//
// Data lives in this file so the page stays thin and the unit tests can
// assert structure without rendering the Clerk-wrapped page shell.

const LAST_UPDATED = "2026-05-12";

// ── Block content (used by the Safety Rules section) ────────────────────────

export type SopBlock =
  | { type: "paragraph"; text: string }
  | { type: "heading"; text: string }
  | { type: "numbered"; items: string[] }
  | { type: "bullets"; items: string[] };

// ── Top-of-page SOP gallery (four folder cards) ─────────────────────────────

export interface SopGalleryCard {
  id: string;
  title: string;
  description: string;
  /** In-page anchor the card scrolls to. */
  anchor: string;
}

export const SOP_GALLERY: SopGalleryCard[] = [
  {
    id: "mission-control-build",
    title: "Mission Control Build",
    description:
      "The main operating manual. Five steps from setup to a pushed branch, plus what to do when it's time for a PR, when checks fail, or when you come back later.",
    anchor: "#mission-control-build",
  },
  {
    id: "import-existing-code",
    title: "Import Existing Code",
    description:
      "Move a bot, script, dashboard, or tool that was built outside Mission Control into the repo without leaking secrets or running it unsafely.",
    anchor: "#import-existing-code",
  },
  {
    id: "safety-rules",
    title: "Safety Rules",
    description:
      "Rules for secrets, client data, external platforms, dry-run mode, and owner-only actions.",
    anchor: "#safety-rules",
  },
  {
    id: "emergency-debug",
    title: "Emergency Debug",
    description:
      "When something breaks: stop, diagnose, make the smallest safe fix, push only if safe.",
    anchor: "#emergency-debug",
  },
];

// ── Mission Control Build — five main steps + three extras ──────────────────
//
// The five-step flow is the spine. The three extras are smaller "what's next"
// cards that share the same shape (title, purpose, prompt) but don't get a
// step number — they're rendered under sub-headings instead.

export interface BuildStep {
  /** 1–5 for the main flow; undefined for extras. */
  number?: number;
  title: string;
  purpose: string;
  /** Prompt id; references a PROMPT_LIBRARY entry. */
  promptId: string;
}

export interface MissionControlBuild {
  title: string;
  description: string;
  steps: BuildStep[];
  extras: {
    label: string;
    step: BuildStep;
  }[];
}

export const MISSION_CONTROL_BUILD: MissionControlBuild = {
  title: "Mission Control Build",
  description:
    "Five steps every build follows. Copy the prompt at each step into Claude Code and run it before moving on.",
  steps: [
    {
      number: 1,
      title: "Start Safe",
      purpose:
        "Open Mission Control in Claude Code, confirm the repo, confirm the branch, create or continue the correct branch, and decide where the work belongs.",
      promptId: "start-mission-control-build",
    },
    {
      number: 2,
      title: "Build",
      purpose:
        "Build the bot, tool, page, workflow, agent, or feature in the right place without touching production or secrets.",
      promptId: "build-inside-mission-control",
    },
    {
      number: 3,
      title: "Test",
      purpose: "Run safe local checks and confirm nothing broke.",
      promptId: "test-mission-control-build",
    },
    {
      number: 4,
      title: "Safety Check",
      purpose:
        "Check branch, changed files, secrets, env files, private data, external actions, and dry-run/live-mode before pushing.",
      promptId: "run-pre-push-safety-check",
    },
    {
      number: 5,
      title: "Push Branch",
      purpose:
        "Commit and push the branch to GitHub without pushing to main or deploying.",
      promptId: "push-branch-safely",
    },
  ],
  extras: [
    {
      label: "When ready for PR",
      step: {
        title: "Open Pull Request",
        purpose:
          "Produce a clean PR summary so GitHub checks can run and the change can be reviewed if needed.",
        promptId: "open-pull-request-summary",
      },
    },
    {
      label: "If checks fail",
      step: {
        title: "Fix Failed Checks",
        purpose:
          "Fix only the failing issue. Smallest safe fix, no unrelated changes.",
        promptId: "fix-failed-github-checks",
      },
    },
    {
      label: "Continue later",
      step: {
        title: "Resume This Branch",
        purpose:
          "Come back to a branch later and pick up where you left off — repo state, branch summary, and the next safe step.",
        promptId: "continue-existing-mission-control-build",
      },
    },
  ],
};

// ── Import / Emergency folders (intro + single prompt each) ─────────────────

export interface IntroFolder {
  id: string;
  title: string;
  description: string;
  intro: string;
  promptId: string;
}

export const IMPORT_FOLDER: IntroFolder = {
  id: "import-existing-code",
  title: "Import Existing Code",
  description:
    "Move outside-built code into the repo safely. Real API keys may be used at runtime but never committed; real client data may be used internally but raw dumps must not be committed; live external actions need explicit dry-run / live-mode gates.",
  intro:
    "Use the prompt below to drop a script, dashboard, bot, or tool into incoming/coo-import/ and audit it before anything runs.",
  promptId: "import-existing-code-into-mission-control",
};

export const EMERGENCY_FOLDER: IntroFolder = {
  id: "emergency-debug",
  title: "Emergency Debug",
  description:
    "Stop the bleed first, fix the exact issue second. Smallest safe fix only.",
  intro:
    "Paste this prompt into Claude Code when something breaks. It forces find-the-exact-file, smallest-safe-fix posture and never rebuilds from scratch.",
  promptId: "emergency-debug-prompt",
};

// ── Safety Rules (readable prose, no copy button) ───────────────────────────

export interface SafetyRules {
  id: string;
  title: string;
  description: string;
  blocks: SopBlock[];
}

export const SAFETY_RULES: SafetyRules = {
  id: "safety-rules",
  title: "Safety Rules",
  description:
    "Rules for secrets, client data, external platforms, dry-run mode, and owner-only actions. Read once, reference whenever.",
  blocks: [
    { type: "heading", text: "Normal building is allowed" },
    {
      type: "bullets",
      items: [
        "UI pages",
        "dashboards",
        "bots",
        "agents",
        "tools",
        "workflows",
        "docs",
        "safe local tests",
        "dry-run automations",
      ],
    },
    { type: "heading", text: "Keep out of GitHub" },
    {
      type: "bullets",
      items: [
        "API keys",
        "passwords",
        "cookies",
        "tokens",
        "login sessions",
        ".env files",
        "private client data dumps",
      ],
    },
    { type: "heading", text: "Owner-only or review required" },
    {
      type: "bullets",
      items: [
        "Render production settings",
        "Clerk",
        "Cloudflare",
        "DNS",
        "billing",
        "auth/security",
        "roles",
        "production database",
        "migrations",
        "real OnlyFans",
        "real OnlyMonster",
        "live sending / posting / scraping / deleting",
        "external platform actions without dry-run",
      ],
    },
    { type: "heading", text: "Dry-run rule" },
    {
      type: "paragraph",
      text: "Any bot, tool, or workflow that sends, posts, scrapes, logs in, deletes, or touches an external platform must start with:",
    },
    {
      type: "bullets",
      items: ["DRY_RUN=true", "ALLOW_LIVE_EXTERNAL_ACTIONS=false"],
    },
  ],
};

// ── Claude prompt library ───────────────────────────────────────────────────
//
// Order matches the SOP flow:
//   1–5  → Mission Control Build main steps
//   6–8  → Mission Control Build extras (PR, fix failed, continue later)
//   9    → Import Existing Code
//   10   → Emergency Debug
//
// Each prompt's optional `step` field is the Mission Control Build step
// number (1–5). Extras and Import/Emergency do not carry a step.

export interface Prompt {
  id: string;
  step?: number;
  title: string;
  whenToUse: string;
  description: string;
  /** First two short lines of the prompt shown in the step / folder card. */
  preview: string;
  /** Full prompt body — what the Copy button puts on the clipboard. */
  body: string;
  updated: string;
}

export const PROMPT_LIBRARY: Prompt[] = [
  {
    id: "start-mission-control-build",
    step: 1,
    title: "Start Mission Control Build",
    whenToUse: "Paste this first before building anything.",
    description:
      "Sets up the repo, branch, build plan, placement, and safety classification. Returns a setup report and waits for your confirmation before coding.",
    updated: LAST_UPDATED,
    preview:
      "You are helping me build inside the Mission Control / Digidle OS repo.\nThis is the required startup prompt before any coding.",
    body: `You are helping me build inside the Mission Control / Digidle OS repo.

This is the required startup prompt before any coding.

Do not write code yet.
Do not deploy.
Do not push to main.
Do not open a pull request yet.
Do not touch secrets.
Do not print secrets.
Do not change Render, Clerk, Cloudflare, DNS, billing, auth, roles, production database, or production settings.
Do not connect real OnlyFans.
Do not connect real OnlyMonster.
Do not run live external actions.
Do not send messages, post, scrape, log in, delete, repost, or touch external platforms unless dry-run mode is planned first.

Goal:
Set up the correct branch and build plan so I can work safely inside Mission Control.

Step 1:
Confirm this folder is the Mission Control / Digidle OS repo.

Check:
current folder
git remote
current branch
git status

If this is not the Mission Control repo, stop and tell me to open the correct folder.

Step 2:
Fetch latest GitHub state.

Run:
git fetch origin

Step 3:
If I am on main, do not build on main.

Ask what I am building if I have not already said it.

Then create a new branch from latest main using this format:
coo/name-of-build

Examples:
coo/leak-scan-bot
coo/rt-bot
coo/chat-qc-bot
coo/discord-organizer
coo/revenue-dashboard
coo/content-strategy-tool
coo/import-existing-code

If the branch already exists, use:
coo/name-of-build-v2

Step 4:
If I am already on a coo/* feature branch, ask whether I want to continue this branch or create a new one.

Do not switch branches if there are uncommitted changes.
First explain what is changed.

Step 5:
Classify what I am building.

Choose one:
Bot
Agent
Tool
Workflow
Dashboard
Python Script
HTML Tool
Modern Sales Agency Feature
OnlyFans Intelligence Feature
Chat QC Feature
Bug Fix
UI Cleanup
Import Existing Code
Other

Step 6:
Decide where the work belongs inside Mission Control.

Use this placement logic:
Bots go under the existing Bots system.
Agents go under the existing Agents system.
Tools go under the existing Tools or integrations area.
Workflows go under the existing Workflows system.
Modern Sales Agency features go under the Modern Sales Agency section.
OnlyFans Intelligence features go under OnlyFans Intelligence.
Chat QC features go under Modern Sales Agency or OnlyFans Intelligence depending on current structure.
Imported code goes first into:
incoming/coo-import/

Do not invent a new structure unless the existing structure clearly has no place for it.

Step 7:
Apply safety classification.

SAFE:
UI pages
internal dashboards
documentation
SOPs
read-only tools
dry-run tools
local-only tests

REVIEW NEEDED:
database migrations
auth changes
role changes
permission changes
GitHub workflow changes
Render config changes
Discord or Telegram routing
external integrations
client data handling

OWNER ONLY:
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
live sending/posting/scraping without dry-run
production deploy settings

Step 8:
If this touches external systems, plan dry-run mode first.

External systems include:
AdsPower
PhantomBuster
X/Twitter
Instagram
Reddit
Discord
Telegram
OnlyFans
OnlyMonster
Notion
Google Drive
Render
Cloudflare
Clerk

Default rule:
DRY_RUN=true
ALLOW_LIVE_EXTERNAL_ACTIONS=false

Step 9:
Return this setup report before coding:

A. Repo confirmed
B. Current branch before setup
C. Branch selected or created
D. Build type
E. Recommended Mission Control location
F. Files likely to change
G. Risk level
H. Dry-run requirements
I. Blocked actions
J. Exact build plan

Wait for me to confirm before making code changes.`,
  },
  {
    id: "build-inside-mission-control",
    step: 2,
    title: "Build Inside Mission Control",
    whenToUse: "Use after the Start Safe prompt gives the branch and build plan.",
    description:
      "Builds in the right existing section with dry-run defaults, no secret exposure, clear setup/test instructions, and stops before merge or deploy.",
    updated: LAST_UPDATED,
    preview:
      "You are building inside Mission Control / Digidle OS.\nBuild this in the correct existing Mission Control section based on the setup plan.",
    body: `You are building inside Mission Control / Digidle OS.

Do not rebuild from scratch.
Do not touch secrets.
Do not deploy.
Do not push to main.
Do not run live external actions.
Do not connect real OnlyFans.
Do not connect real OnlyMonster.
Do not send Discord, Telegram, X, Reddit, OnlyFans, or OnlyMonster messages unless live mode has been explicitly approved.

Build this in the correct existing Mission Control section based on the setup plan.

Requirements:
1. Preserve existing architecture.
2. Build in the location identified by the setup prompt.
3. Add clear UI if this is user-facing.
4. Add backend only if needed.
5. Do not expose secrets in frontend.
6. If it touches external systems, default to dry-run mode.
7. Add logs or clear output where useful.
8. Add setup requirements.
9. Add error handling.
10. Add test instructions.
11. Do not remove working systems.
12. Stop before merge or deploy.

Return:
A. What you built
B. Files changed
C. How to test
D. What is safe
E. What is blocked
F. Whether ready for safety check`,
  },
  {
    id: "test-mission-control-build",
    step: 3,
    title: "Test Mission Control Build",
    whenToUse: "Use after building, before pushing.",
    description:
      "Runs typecheck, lint, unit tests, and (if safe) the relevant e2e checks. Confirms no secrets are exposed and no live external actions ran.",
    updated: LAST_UPDATED,
    preview:
      "Test this Mission Control branch safely.\nDo not deploy. Do not push to main. Do not run live external actions.",
    body: `Test this Mission Control branch safely.

Do not deploy.
Do not push to main.
Do not run live external actions.
Do not print secrets.
Do not connect real OnlyFans.
Do not connect real OnlyMonster.

Run appropriate local checks:
typecheck
lint
unit tests
relevant e2e tests if safe
build if reasonable
manual route check if needed

Also verify:
1. App still opens.
2. Touched page loads.
3. Existing related pages still work.
4. No secrets are exposed.
5. No live external actions ran.
6. Dry-run mode is respected if applicable.

Return:
A. Tests run
B. Results
C. Any failures
D. Exact fix needed if failed
E. Whether safe to run pre-push safety check`,
  },
  {
    id: "run-pre-push-safety-check",
    step: 4,
    title: "Run Pre-Push Safety Check",
    whenToUse: "Use right before pushing anything to GitHub.",
    description:
      "Audits the branch for secrets, env files, auth/security drift, external-platform code, and client data before you push.",
    updated: LAST_UPDATED,
    preview:
      "Before pushing this Mission Control branch, run a safety review.\nDo not deploy. Do not push to main. Do not print secrets.",
    body: `Before pushing this Mission Control branch, run a safety review.

Do not deploy.
Do not push to main.
Do not print secrets.

Check:
1. Current branch
2. Confirm branch is not main
3. Git status
4. Files changed
5. Any .env files staged
6. Any API keys or tokens
7. Any auth/security changes
8. Any database/migration changes
9. Any Render/Clerk/Cloudflare changes
10. Any external platform actions
11. Any OnlyFans or OnlyMonster code
12. Any destructive commands
13. Whether dry-run mode exists if needed
14. Whether client data is being committed
15. Whether logs, cookies, sessions, or private data are staged

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
    id: "push-branch-safely",
    step: 5,
    title: "Push Branch Safely",
    whenToUse:
      "Use only after the safety check says SAFE or REVIEW NEEDED with acceptable notes.",
    description:
      "Commits the intended files, pushes the feature branch to origin, and reports what to do next. Never pushes to main, never deploys.",
    updated: LAST_UPDATED,
    preview:
      "Push this Mission Control branch safely.\nDo not push to main. Do not deploy manually. Do not print secrets.",
    body: `Push this Mission Control branch safely.

Do not push to main.
Do not deploy manually.
Do not print secrets.

Before pushing:
1. Confirm current branch is not main.
2. Confirm working tree is clean or only intended commits exist.
3. Confirm safety check is SAFE or explain REVIEW NEEDED.
4. Confirm no env files, secrets, private client data dumps, logs, cookies, or sessions are staged.
5. Confirm commit message is clear.

Then:
1. Commit intended files if not already committed.
2. Push the current branch to origin.
3. Do not merge.
4. Do not deploy.

Return:
A. Branch pushed
B. Commit hash
C. Files committed
D. PR command or PR URL if created
E. Whether GitHub checks started
F. Anything that needs review`,
  },
  {
    id: "open-pull-request-summary",
    title: "Open Pull Request Summary",
    whenToUse: "Use when the branch is ready to propose into main.",
    description:
      "Produces a clean PR summary covering what changed, how to test, and the full safety posture.",
    updated: LAST_UPDATED,
    preview:
      "Write a clean pull request summary for this Mission Control branch.\nKeep it clear and short.",
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
    id: "fix-failed-github-checks",
    title: "Fix Failed GitHub Checks",
    whenToUse: "Use when GitHub checks fail after pushing a branch.",
    description:
      "Identifies the exact failing check, the root-cause file, and applies the smallest fix. Never rebuilds from scratch.",
    updated: LAST_UPDATED,
    preview:
      "Fix the failed GitHub checks for this Mission Control PR.\nDo not rebuild from scratch. Do not make unrelated changes.",
    body: `Fix the failed GitHub checks for this Mission Control PR.

Do not rebuild from scratch.
Do not make unrelated changes.
Do not deploy.
Do not push to main.
Do not touch secrets.
Do not change production settings.

Steps:
1. Identify the exact failing check.
2. Read the exact error.
3. Identify the exact file causing the failure.
4. Make the smallest safe fix.
5. Run the relevant local test.
6. Commit only the fix.
7. Push to the same branch.
8. Do not merge.

Return:
A. Failed check
B. Root cause
C. File changed
D. Fix applied
E. Test result
F. Commit hash
G. Whether checks restarted`,
  },
  {
    id: "continue-existing-mission-control-build",
    title: "Continue Existing Mission Control Build",
    whenToUse: "Use when returning to a branch that already exists.",
    description:
      "Confirms repo + branch state, summarizes what the branch is building, identifies the next safe step. No coding until the continuation plan is shown.",
    updated: LAST_UPDATED,
    preview:
      "Continue work on an existing Mission Control branch safely.\nDo not work on main. Do not deploy. Do not touch secrets.",
    body: `Continue work on an existing Mission Control branch safely.

Do not work on main.
Do not deploy.
Do not touch secrets.
Do not run live external actions.

Steps:
1. Confirm repo.
2. Show current branch.
3. If on main, stop and ask which branch to continue.
4. Pull latest updates for the current branch.
5. Show git status.
6. Summarize what this branch appears to be building.
7. Identify next safe step.
8. Do not code until you show the continuation plan.

Return:
A. Current branch
B. Branch status
C. What this branch is for
D. Current changed files
E. Next safe step
F. Risks or blockers`,
  },
  {
    id: "import-existing-code-into-mission-control",
    title: "Import Existing Code Into Mission Control",
    whenToUse:
      "Use when code was built outside Mission Control and needs to be moved in.",
    description:
      "Eleven-step import flow. Real API keys may be used at runtime but never committed; raw client data dumps stay out of the repo; live external actions require dry-run and live-mode gates.",
    updated: LAST_UPDATED,
    preview:
      "You are importing existing code into Mission Control safely.\nDo not push to main. Do not deploy. Do not touch secrets.",
    body: `You are importing existing code into Mission Control safely.

Do not push to main.
Do not deploy.
Do not touch secrets.
Do not commit API keys, passwords, cookies, tokens, login sessions, or private client data.
Do not change Render, Clerk, Cloudflare, DNS, billing, auth, roles, production database, or production settings.
Do not connect real OnlyFans.
Do not connect real OnlyMonster.
Do not send messages, post, scrape, log in, delete, or touch external platforms unless dry-run mode is added first.

Goal:
Move existing code into the correct Mission Control branch and folder so I can continue building it safely.

Step 1:
Confirm I am inside the Mission Control repo.

Step 2:
Fetch latest main.

Step 3:
Create a new branch named:
coo/import-existing-code

If that branch already exists, create a unique branch name like:
coo/import-existing-code-v2

Step 4:
Create this folder:
incoming/coo-import/

Step 5:
Move or copy the existing code into:
incoming/coo-import/

If the code is somewhere else on my computer, ask me for the file path.

Step 6:
Inspect the imported code before running anything.

Tell me:
1. What files were imported
2. What language it uses
3. What the code does
4. How it runs
5. What inputs it needs
6. What outputs it creates
7. Whether it uses API keys
8. Whether it touches client data
9. Whether it sends, posts, scrapes, logs in, deletes, or touches external platforms
10. Whether it should become a Tool, Bot, Workflow, Agent, Modern Sales Agency page, OnlyFans Intelligence feature, or other

Step 7:
Real API keys may be used at runtime, but must never be committed.
Real client data may be used internally, but raw dumps must not be committed.
Live external actions require explicit dry-run and live-mode gates.

Step 8:
Do not run the code unless it is clearly safe.
If it can send, post, scrape, log in, delete, or touch client data, do not run it yet.

Step 9:
Create a README.md inside the import folder.

The README must explain:
1. What this code does
2. How to run it
3. What setup it needs
4. What inputs it needs
5. What outputs it creates
6. What external services it touches
7. What risks exist
8. What still needs to be done

Step 10:
Add or plan dry-run mode if the code touches any external service.

Step 11:
Do not merge.
Do not deploy.
Do not push to main.

Return:
A. Current branch
B. Files imported
C. What the code does
D. Safety risks
E. Recommended Mission Control location
F. What to build next
G. Whether it is safe to continue building on this branch`,
  },
  {
    id: "emergency-debug-prompt",
    title: "Emergency Debug Prompt",
    whenToUse: "Use when something breaks.",
    description:
      "Forces find-the-exact-file, smallest-safe-fix posture. No rebuilds, no production changes.",
    updated: LAST_UPDATED,
    preview:
      "You are debugging Mission Control.\nFind the exact error. Make the smallest safe fix.",
    body: `You are debugging Mission Control.

Do not rebuild from scratch.
Do not deploy.
Do not push to main.
Do not touch secrets.
Do not change production settings.
Do not make unrelated changes.

Find the exact error.
Identify the exact file.
Make the smallest safe fix.
Run the relevant local test.
Return what broke, what changed, and whether it is safe.`,
  },
];
