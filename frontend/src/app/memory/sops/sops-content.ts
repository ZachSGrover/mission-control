// SOP and Claude-prompt content for the Memory → SOPs page (v3 step-flow).
//
// Shape: one main step-by-step "Mission Control Developer SOP" walks Luis
// through every build from setup → push → PR → fixing checks → resuming.
// Three smaller SOPs (Import / Emergency / Security) sit alongside it. Below
// them, the Claude Prompt Library lists all ten prompts in the same order as
// the SOP flow, each with its own copy button.
//
// Data lives in this file so the page stays thin and so the unit tests can
// assert structure without rendering the Clerk-wrapped page shell.

const LAST_UPDATED = "2026-05-12";

// ── Block content (reused by Security Rules) ────────────────────────────────

export type SopBlock =
  | { type: "paragraph"; text: string }
  | { type: "heading"; text: string }
  | { type: "numbered"; items: string[] }
  | { type: "bullets"; items: string[] };

// ── SOP gallery (top-of-page overview cards) ────────────────────────────────

export interface SopGalleryCard {
  id: string;
  title: string;
  description: string;
  /** In-page anchor the card links to. */
  anchor: string;
}

export const SOP_GALLERY: SopGalleryCard[] = [
  {
    id: "developer",
    title: "Mission Control Developer SOP",
    description:
      "The complete step-by-step workflow for starting a build, creating the right branch, building safely, testing, pushing, and opening a PR.",
    anchor: "#developer-sop",
  },
  {
    id: "import",
    title: "Import Existing Code SOP",
    description:
      "Use when a bot, script, dashboard, or tool was built outside Mission Control and needs to be moved into the repo safely.",
    anchor: "#import-sop",
  },
  {
    id: "emergency",
    title: "Emergency Debug SOP",
    description:
      "Use when something breaks and Claude needs to diagnose and fix the smallest safe issue.",
    anchor: "#emergency-sop",
  },
  {
    id: "security",
    title: "Security and Live Action Rules",
    description:
      "Rules for secrets, client data, external platforms, dry-run mode, and owner-only actions.",
    anchor: "#security-rules",
  },
];

// ── Mission Control Developer SOP (the main step flow) ──────────────────────

export interface DeveloperStep {
  number: number;
  title: string;
  purpose: string;
  /** Prompt to use at this step. References a PROMPT_LIBRARY entry by id. */
  promptId: string;
}

export interface DeveloperSop {
  title: string;
  description: string;
  steps: DeveloperStep[];
}

export const DEVELOPER_SOP: DeveloperSop = {
  title: "Mission Control Developer SOP",
  description:
    "Eight steps from idea to merged PR. Run each prompt in order — they are designed to stack.",
  steps: [
    {
      number: 1,
      title: "Start Every Build Safely",
      purpose:
        "Make sure Claude Code is in the right repo, not on main, on a fresh branch, and knows where the work belongs.",
      promptId: "start-every-build-safely",
    },
    {
      number: 2,
      title: "Build in the Right Place",
      purpose:
        "Tell Claude what Luis is building and make sure it goes into the correct Mission Control area.",
      promptId: "build-safe",
    },
    {
      number: 3,
      title: "Test Locally",
      purpose:
        "Run safe local tests without deploying or triggering live external actions.",
      promptId: "test-build",
    },
    {
      number: 4,
      title: "Run Safety Check Before Pushing",
      purpose:
        "Check secrets, env files, client data, external actions, branch, changed files, and risky areas before pushing.",
      promptId: "run-safety-check",
    },
    {
      number: 5,
      title: "Push Branch Safely",
      purpose:
        "Push the feature branch to GitHub without pushing to main.",
      promptId: "push-branch-safely",
    },
    {
      number: 6,
      title: "Open Pull Request",
      purpose:
        "Create a clean PR summary so GitHub checks can run and the change can be reviewed if needed.",
      promptId: "open-pr-summary",
    },
    {
      number: 7,
      title: "Fix Failed Checks",
      purpose:
        "If GitHub checks fail, fix only the failing issue and do not make random changes.",
      promptId: "fix-failed-checks",
    },
    {
      number: 8,
      title: "Continue Existing Branch",
      purpose:
        "If Luis comes back later, resume work on the right branch safely.",
      promptId: "continue-existing-build",
    },
  ],
};

// ── Smaller SOPs (Import + Emergency) ───────────────────────────────────────

export interface SimpleSop {
  id: string;
  title: string;
  description: string;
  steps: string[];
  promptId: string;
}

export const IMPORT_SOP: SimpleSop = {
  id: "import-sop",
  title: "Import Existing Code SOP",
  description:
    "Move a script, dashboard, bot, or tool that was built outside Mission Control into the repo without leaking secrets or running it unsafely.",
  steps: [
    "Put existing code in a folder or zip.",
    "Use the import prompt.",
    "Import into incoming/coo-import.",
    "Inspect before running.",
    "Move secrets to env.",
    "Keep real client data out of GitHub if appropriate.",
    "Add dry-run for live actions.",
    "Continue building on the branch.",
  ],
  promptId: "import-existing-code",
};

export const EMERGENCY_SOP: SimpleSop = {
  id: "emergency-sop",
  title: "Emergency Debug SOP",
  description:
    "Something broke. Stop, diagnose, make the smallest safe fix, push only if safe. Do not panic-deploy.",
  steps: [
    "Stop changing things.",
    "Do not deploy.",
    "Do not push to main.",
    "Identify exact error.",
    "Fix smallest possible issue.",
    "Run local checks.",
    "Push only if safe.",
  ],
  promptId: "emergency-debug",
};

// ── Security and Live Action Rules (readable prose, no copy button) ─────────

export interface SecurityRules {
  id: string;
  title: string;
  description: string;
  blocks: SopBlock[];
}

export const SECURITY_RULES: SecurityRules = {
  id: "security-rules",
  title: "Security and Live Action Rules",
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
// Order matches the Developer SOP flow, with Import and Emergency at the end.
// Each prompt's `step` field (if present) links it to a Developer SOP step.

export interface Prompt {
  id: string;
  /** Developer SOP step number (1–8). Omitted for Import (9) and Emergency (10). */
  step?: number;
  title: string;
  whenToUse: string;
  description: string;
  /** First two short lines of the prompt shown in the card (no copy). */
  preview: string;
  /** Full prompt copied by the Copy button. */
  body: string;
  updated: string;
}

export const PROMPT_LIBRARY: Prompt[] = [
  {
    id: "start-every-build-safely",
    step: 1,
    title: "Start Every Mission Control Build Safely",
    whenToUse:
      "Paste this into Claude Code before building any bot, agent, workflow, tool, page, import, or bug fix.",
    description:
      "Checks repo, branch, safety, correct placement, risk level, and dry-run requirements before any code changes happen.",
    updated: LAST_UPDATED,
    preview:
      "You are helping me build inside the Mission Control / Digidle OS repo safely.\nThis prompt must run BEFORE any coding starts.",
    body: `You are helping me build inside the Mission Control / Digidle OS repo safely.

This prompt must run BEFORE any coding starts.

Do not write code yet.
Do not deploy.
Do not push to main.
Do not touch secrets.
Do not change production env vars.
Do not change Render, Clerk, Cloudflare, DNS, billing, auth, roles, production database, or production settings.
Do not connect real OnlyFans.
Do not connect real OnlyMonster.
Do not run live external actions.
Do not send messages, post, scrape, log in, delete, or touch external platforms unless dry-run mode is planned first.

Goal:
Prepare a safe workspace for the build and tell me exactly where this work should live inside Mission Control.

Step 1:
Confirm I am inside the Mission Control / Digidle OS repo.

Run checks to identify:
current folder
current git branch
git status
remote origin
latest main status

Step 2:
If current branch is main, stop and create a new feature branch before doing any work.

Ask me what I am building if I have not already said it.

Step 3:
Classify the build type.

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
Other

Step 4:
Create a safe branch name based on the build.

Use this format:
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

Step 5:
Pull latest main before creating the branch.

Then create or switch to the correct feature branch.

Step 6:
Inspect the repo and choose the correct place to build.

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
Before coding, create a short build plan.

Include:
1. What I am building
2. Where it will live
3. Files likely to change
4. Whether it needs frontend
5. Whether it needs backend
6. Whether it needs a database or migration
7. Whether it touches external services
8. Whether it uses client data
9. Whether it needs API keys
10. Whether it needs dry-run mode
11. What is safe to do now
12. What is blocked until owner approval

Step 8:
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

Step 9:
If the build touches external systems, plan dry-run mode first.

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

Step 10:
Do not start coding until you return this setup report:

A. Repo confirmed
B. Current branch before setup
C. New branch created or selected
D. Build type
E. Recommended Mission Control location
F. Files likely to change
G. Risk level
H. Dry-run requirements
I. Blocked actions
J. Exact next build plan

After returning the setup report, wait for me to confirm before making code changes.`,
  },
  {
    id: "build-safe",
    step: 2,
    title: "Build a Safe Bot, Tool, Agent, Workflow, or Page",
    whenToUse:
      "After the setup prompt has identified the correct Mission Control location.",
    description:
      "Builds in the right existing section with dry-run defaults, no secret exposure, and clear setup/test instructions. Stops before merge or deploy.",
    updated: LAST_UPDATED,
    preview:
      "You are building inside Mission Control / Digidle OS.\nBuild this in the correct existing Mission Control section.",
    body: `You are building inside Mission Control / Digidle OS.

Do not rebuild from scratch.
Do not touch secrets.
Do not deploy.
Do not push to main.
Do not run live external actions.
Do not connect real OnlyFans.
Do not connect real OnlyMonster.
Do not send Discord, Telegram, X, Reddit, OnlyFans, or OnlyMonster messages unless live mode has been explicitly approved.

Build this in the correct existing Mission Control section.

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
    id: "test-build",
    step: 3,
    title: "Test This Build Safely",
    whenToUse: "After Claude has built the feature on the branch.",
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
E. Whether safe to push branch`,
  },
  {
    id: "run-safety-check",
    step: 4,
    title: "Run Safety Check Before Pushing",
    whenToUse: "Right before pushing your branch to GitHub.",
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
    title: "Push This Branch Safely",
    whenToUse: "After the safety check returns SAFE or you have resolved REVIEW NEEDED.",
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
4. Confirm no env files, secrets, client data dumps, logs, cookies, or sessions are staged.
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
    id: "open-pr-summary",
    step: 6,
    title: "Open Pull Request Summary",
    whenToUse: "Right before opening a pull request into main.",
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
    id: "fix-failed-checks",
    step: 7,
    title: "Fix Failed GitHub Checks",
    whenToUse: "When CI on the PR fails and you need the smallest safe fix.",
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
    id: "continue-existing-build",
    step: 8,
    title: "Continue Existing Mission Control Build",
    whenToUse:
      "When Luis returns to a branch later and needs to pick up where he left off.",
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
    id: "import-existing-code",
    title: "Import Existing Code Into Mission Control",
    whenToUse:
      "When a bot, script, dashboard, or tool was built outside Mission Control and needs to move into the repo safely.",
    description:
      "Eleven-step import flow: branch + folder + audit + README + dry-run. Real API keys may be used at runtime but never committed; real client data may be used internally but not committed as raw dumps; live external actions require explicit dry-run/live mode gates.",
    updated: LAST_UPDATED,
    preview:
      "You are helping move my existing code into the Mission Control / Digidle OS GitHub repo safely.\nDo not push to main. Do not deploy. Do not touch secrets.",
    body: `You are helping move my existing code into the Mission Control / Digidle OS GitHub repo safely.

Do not push to main.
Do not deploy.
Do not touch secrets.
Do not commit API keys, passwords, cookies, tokens, login sessions, or private client data.
Do not change Render, Clerk, Cloudflare, DNS, billing, auth, roles, production database, or production settings.
Do not connect real OnlyFans.
Do not connect real OnlyMonster.
Do not send messages, post, scrape, log in, delete, or touch external platforms unless dry-run mode is added first.

Safety model for imports:
Real API keys may be used at runtime, but they must never be committed — keep them in .env (gitignored).
Real client data may be used internally for testing, but raw dumps must not be committed to the repo.
Any live external action must sit behind an explicit dry-run / live mode gate (DRY_RUN=true by default).

Goal:
Move my existing code into the correct Mission Control branch and folder so I can continue building it safely.

Step 1:
Confirm I am inside the Mission Control repo.

Step 2:
Pull latest main.

Step 3:
Create a new branch named:
coo/import-existing-code

If that branch already exists, create a unique branch name like:
coo/import-existing-code-v2

Step 4:
Create this folder:
incoming/coo-import/

Step 5:
Move or copy my existing code into:
incoming/coo-import/

If the code is somewhere else on my computer, ask me for the file path.

Step 6:
Inspect the imported code before running anything.

Tell me:
1. What files were imported
2. What language it uses
3. What the code does
4. How it currently runs
5. What inputs it needs
6. What outputs it creates
7. Whether it uses API keys
8. Whether it touches client data
9. Whether it sends, posts, scrapes, logs in, deletes, or touches any external platform
10. Whether it should become a Tool, Bot, Workflow, Agent, or Modern Sales Agency page inside Mission Control

Step 7:
Do not run the code unless it is clearly safe.
If it can send, post, scrape, log in, delete, or touch client data, do not run it yet.

Step 8:
Create a README.md inside:
incoming/coo-import/

The README must explain:
1. What this code does
2. How to run it
3. What setup it needs
4. What inputs it needs
5. What outputs it creates
6. What external services it touches
7. What risks exist
8. What still needs to be done

Step 9:
Add dry-run mode if the code touches any external service.

Step 10:
After the audit, recommend the right final place inside Mission Control:
Tools
Bots
Workflows
Agents
Modern Sales Agency
OnlyFans Intelligence
Other

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
    id: "emergency-debug",
    title: "Emergency Debug Prompt",
    whenToUse: "When something breaks and you need the smallest safe fix.",
    description:
      "Forces find-the-exact-file, make-the-smallest-safe-fix posture. No rebuilds, no production changes.",
    updated: LAST_UPDATED,
    preview:
      "You are debugging Mission Control.\nFind the exact error. Make the smallest safe fix.",
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
  },
];
