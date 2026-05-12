// SOP and Claude-prompt content for the Memory → SOPs page (v2 gallery).
//
// Content lives in this file so the page can stay thin and so the unit tests
// can assert structure without rendering the Clerk-wrapped page shell. When a
// SOPs API lands, swap the constants for a fetch and the card components in
// ./components.tsx keep working unchanged.

const LAST_UPDATED = "2026-05-12";

// ── SOP library ─────────────────────────────────────────────────────────────

export type SopBlock =
  | { type: "paragraph"; text: string }
  | { type: "heading"; text: string }
  | { type: "numbered"; items: string[] }
  | { type: "bullets"; items: string[] };

export interface Sop {
  id: string;
  title: string;
  category: string;
  description: string;
  updated: string;
  blocks: SopBlock[];
}

export const SOP_LIBRARY: Sop[] = [
  {
    id: "mission-control-build-sop",
    title: "Mission Control Build SOP",
    category: "Workflow",
    description:
      "Safety rails for building bots, workflows, tools, and pages. Normal building does not need owner approval — only production, security, secrets, billing, auth, database, and external platform actions do.",
    updated: LAST_UPDATED,
    blocks: [
      {
        type: "paragraph",
        text: "Build everything on a feature branch, ship through GitHub checks, and only loop the owner in for the categories below. These are the rules every COO/builder follows.",
      },
      { type: "heading", text: "The twelve rules" },
      {
        type: "numbered",
        items: [
          "Do not build directly on main.",
          "Every project gets its own branch (examples: coo/rt-bot, coo/chat-qc-dashboard, coo/client-tracker, coo/content-tool, coo/project-name).",
          "Build everything inside that branch.",
          "You can freely build bots, workflows, tools, frontend pages, backend routes, dashboards, Modern Sales Agency systems, client systems, internal automations, and safe dry-run logic.",
          "Never commit API keys, passwords, cookies, login sessions, client private data, .env files, tokens, or secrets.",
          "Do not touch Render production settings, Clerk, Cloudflare, DNS, billing, auth or security, user roles, the production database, migrations, secrets, the main branch, real OnlyFans, or real OnlyMonster without owner approval.",
          "Any bot or workflow that sends messages, posts, scrapes, logs in, deletes, or touches an external platform must have dry-run mode first.",
          "Before pushing, run the safety check.",
          "Push your branch to GitHub.",
          "Open a pull request into main.",
          "If GitHub checks pass and no restricted files were touched, the work can be merged.",
          "Once merged into main, Render deploys the live Mission Control app.",
        ],
      },
    ],
  },
  {
    id: "github-branch-workflow",
    title: "GitHub Branch Workflow",
    category: "Workflow",
    description:
      "The safe-by-default workflow for moving from a feature idea to a merged PR. Never push unfinished experiments directly to main.",
    updated: LAST_UPDATED,
    blocks: [
      {
        type: "paragraph",
        text: "A branch is a safe workspace where you can build without touching the live app. Treat it as the unit of work.",
      },
      { type: "heading", text: "Workflow" },
      {
        type: "numbered",
        items: [
          "Pull the latest main.",
          "Create a new branch.",
          "Build your feature.",
          "Test locally.",
          "Run the safety check.",
          "Push your branch.",
          "Open a pull request.",
          "Wait for checks.",
          "Merge only when checks pass.",
        ],
      },
      { type: "heading", text: "Branch naming" },
      {
        type: "bullets",
        items: [
          "coo/name-of-project",
          "coo/fix-name",
          "coo/tool-name",
          "coo/bot-name",
          "coo/workflow-name",
        ],
      },
    ],
  },
  {
    id: "safety-rules",
    title: "Safety Rules",
    category: "Safety",
    description:
      "Which actions are safe to ship on a feature branch, which need review, and which are blocked without owner approval.",
    updated: LAST_UPDATED,
    blocks: [
      { type: "heading", text: "Safe to build on a branch" },
      {
        type: "bullets",
        items: [
          "UI pages",
          "Internal dashboards",
          "Tools in dry-run mode",
          "Bot drafts",
          "Workflow drafts",
          "Local tests",
          "Documentation",
          "SOPs",
          "Frontend improvements",
          "Non-sensitive backend routes",
        ],
      },
      { type: "heading", text: "Review needed" },
      {
        type: "bullets",
        items: [
          "Database migrations",
          "Auth changes",
          "Role changes",
          "Permissions",
          "External platform integrations",
          "Discord routing",
          "Telegram routing",
          "GitHub workflows",
          "Render config",
          "Deployment scripts",
        ],
      },
      { type: "heading", text: "Blocked without owner approval" },
      {
        type: "bullets",
        items: [
          "Secrets",
          "API keys",
          ".env files",
          "Billing",
          "Cloudflare",
          "Clerk",
          "DNS",
          "Production database destructive changes",
          "Deleting client data",
          "Real OnlyFans connection",
          "Real OnlyMonster connection",
          "Sending or posting externally without dry-run",
        ],
      },
    ],
  },
  {
    id: "bot-workflow-build-rules",
    title: "Bot and Workflow Build Rules",
    category: "Bots",
    description:
      "Every bot or workflow must start safe. Twelve required fields, and one hard rule about external platforms.",
    updated: LAST_UPDATED,
    blocks: [
      {
        type: "paragraph",
        text: "Bots and workflows must start safe. Every bot or workflow needs the twelve fields below. If it sends, posts, scrapes, logs in, deletes, or touches a platform, dry-run mode comes first.",
      },
      { type: "heading", text: "Twelve required fields" },
      {
        type: "numbered",
        items: [
          "Name",
          "Purpose",
          "Owner",
          "Project",
          "Inputs",
          "Outputs",
          "Dry-run mode",
          "Logs",
          "Error handling",
          "Clear safe vs unsafe actions",
          "Setup requirements",
          "Test instructions",
        ],
      },
      { type: "heading", text: "Hard rule" },
      {
        type: "paragraph",
        text: "No bot should post to Discord, Telegram, X, Reddit, OnlyFans, OnlyMonster, or any external platform unless that behavior is explicitly enabled and permission-gated.",
      },
    ],
  },
  {
    id: "render-deployment-rules",
    title: "Render Deployment Rules",
    category: "Deployment",
    description:
      "What COO/builders can and cannot do with the production Render deployment.",
    updated: LAST_UPDATED,
    blocks: [
      {
        type: "paragraph",
        text: "Render production deploys from main only. Production changes come through main after safety checks — never directly.",
      },
      { type: "heading", text: "Builders can" },
      {
        type: "bullets",
        items: [
          "View logs if permitted",
          "Test branches",
          "Build features",
          "Open PRs",
          "Fix bugs",
        ],
      },
      { type: "heading", text: "Builders should not" },
      {
        type: "bullets",
        items: [
          "Change production environment variables",
          "Delete services",
          "Change build commands",
          "Change start commands",
          "Change production database settings",
          "Manually redeploy random branches to production",
        ],
      },
    ],
  },
  {
    id: "emergency-rules",
    title: "Emergency Rules",
    category: "Emergency",
    description:
      "Ten steps the second something breaks. The first three are all variants of: stop pushing.",
    updated: LAST_UPDATED,
    blocks: [
      {
        type: "paragraph",
        text: "If something breaks, the priority is to stop, diagnose, and make the smallest safe fix. Do not panic-deploy.",
      },
      { type: "heading", text: "Ten steps" },
      {
        type: "numbered",
        items: [
          "Stop working.",
          "Do not push to main.",
          "Do not deploy.",
          "Do not change env vars.",
          "Save the error message.",
          "Run a read-only diagnosis.",
          "Ask Claude to identify the exact file and cause.",
          "Fix only the broken thing.",
          "Test locally.",
          "Push only after safety checks pass.",
        ],
      },
    ],
  },
];

// ── Claude prompt library ───────────────────────────────────────────────────

export interface Prompt {
  id: string;
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
    id: "start-development-safely",
    title: "Start Mission Control Development Safely",
    whenToUse: "At the start of any new feature or fix.",
    description:
      "Pulls main, creates a branch, inspects the repo, and waits for your plan before changing code.",
    updated: LAST_UPDATED,
    preview:
      "You are working inside the Mission Control / Digidle OS repo.\nDo not work directly on main. Do not touch secrets.",
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
    id: "import-existing-code",
    title: "Import Existing Code Into Mission Control",
    whenToUse:
      "When the COO already built a Python script, HTML file, tool, bot, or automation outside Mission Control and needs to move it into the repo safely.",
    description:
      "Eleven-step safe import flow — branch, folder, audit, README, dry-run recommendation. The biggest prompt in the library.",
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
Do not send messages, post, scrape, log in, delete, or touch external platforms unless dry run mode is added first.

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
Add dry run mode if the code touches any external service.

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
    id: "build-safe-bot-or-tool",
    title: "Build a Safe Bot or Tool",
    whenToUse:
      "When you want to add a new bot or tool with dry-run + logs + setup, without touching external services.",
    description:
      "Forces dry-run-first, no live sends, clear setup, and test instructions before the assistant changes code.",
    updated: LAST_UPDATED,
    preview:
      "You are building a bot/tool inside Mission Control / Digidle OS.\nBuild this as safe by default.",
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
    id: "run-safety-check",
    title: "Run Safety Check Before Pushing",
    whenToUse: "Right before pushing your branch to GitHub.",
    description:
      "Audits the branch for secrets, auth/security drift, and external-platform code before you push.",
    updated: LAST_UPDATED,
    preview:
      "Before pushing this Mission Control branch, run a safety review.\nDo not deploy. Do not push to main. Do not print secrets.",
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
    id: "open-pr-summary",
    title: "Open Pull Request Summary",
    whenToUse: "Right before opening a pull request into main.",
    description:
      "Produces a clean PR summary covering what changed, how to test, and the safety posture.",
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
