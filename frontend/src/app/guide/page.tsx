"use client";

export const dynamic = "force-dynamic";

import type { ReactNode } from "react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";

// Plain-English owner-facing map of the product. Intentionally stays one long
// scroll — easy to Ctrl-F, easy to point at from other pages.

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className="space-y-3 scroll-mt-24">
      <h2 className="text-base font-semibold" style={{ color: "var(--text)" }}>
        {title}
      </h2>
      <div className="space-y-2 text-sm leading-relaxed" style={{ color: "var(--text-muted)" }}>
        {children}
      </div>
    </section>
  );
}

function Code({ children }: { children: ReactNode }) {
  return (
    <code
      className="rounded px-1.5 py-0.5 font-mono text-[12px]"
      style={{ background: "var(--surface-strong)", color: "var(--text)" }}
    >
      {children}
    </code>
  );
}

export default function GuidePage() {
  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel message="Sign in to access Digidle OS" forceRedirectUrl="/guide" />
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <main className="flex-1 overflow-y-auto" style={{ background: "var(--bg)" }}>
          <div className="max-w-3xl mx-auto px-6 py-8 space-y-10">

            {/* Header */}
            <div>
              <h1 className="text-xl font-semibold" style={{ color: "var(--text)" }}>Guide</h1>
              <p className="mt-1 text-sm" style={{ color: "var(--text-muted)" }}>
                What every section does, how to use Digidle OS to run multiple things at once, and how upcoming features will plug in.
              </p>
            </div>

            {/* Quick jump table of contents */}
            <nav
              className="rounded-xl p-4 grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1.5 text-xs"
              style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}
            >
              {[
                ["#claw", "Clawdius"],
                ["#projects", "Projects"],
                ["#memory", "Memory"],
                ["#calendar", "Calendar"],
                ["#boards", "Boards"],
                ["#agents", "Agents"],
                ["#control", "Control"],
                ["#workflows", "Workflows"],
                ["#skills", "Skills"],
                ["#logs", "Logs"],
                ["#save", "Save"],
                ["#settings", "Settings"],
                ["#users", "Users"],
                ["#integrations", "Integrations"],
                ["#multitasking", "Multitasking"],
                ["#obsidian", "Obsidian Setup"],
                ["#voice", "Voice Mode"],
                ["#branding", "Branding / Logo"],
              ].map(([href, label]) => (
                <a
                  key={href}
                  href={href}
                  className="hover:underline"
                  style={{ color: "var(--accent-strong)" }}
                >
                  {label}
                </a>
              ))}
            </nav>

            <Section id="claw" title="1. Clawdius">
              <p>
                Your main operator chat — the assistant you talk to. Clawdius is the one place
                you give instructions, ask questions, and get responses. Pick the engine in
                the chat header: <strong>Balanced</strong> for normal work, <strong>Deep</strong>
                {" "}for careful reasoning, <strong>Fast</strong> for quick replies.
              </p>
            </Section>

            <Section id="projects" title="2. Projects">
              <p>
                Your business and work areas. Examples: Digidle, Modern Sales Agency,
                Modern Athlete, Grover Art Projects. Projects organize memory, agents,
                boards, tasks, and workflows so Clawdius knows what context each thing belongs to.
              </p>
            </Section>

            <Section id="memory" title="3. Memory">
              <p>
                Long-term knowledge base. Right now it holds per-project context + an
                auto-generated journal of your conversations. It will eventually connect to
                your Obsidian vault so Clawdius can read your real notes, SOPs, and decisions.
                See <a href="#obsidian" className="underline" style={{ color: "var(--accent-strong)" }}>Obsidian Setup</a> for the plan.
              </p>
            </Section>

            <Section id="calendar" title="4. Calendar">
              <p>
                Meetings, launches, reminders, scheduled tasks, and agent run times.
                A single timeline of everything that&apos;s time-bound.
              </p>
            </Section>

            <Section id="boards" title="5. Boards">
              <p>
                Visual task boards — one per project or workstream. Use them for launches,
                content calendars, bugs, and operations. Agents can attach to boards to
                pick up tasks automatically.
              </p>
            </Section>

            <Section id="agents" title="6. Agents">
              <p>
                AI workers that perform a specific job. Planned examples: Content Agent,
                Hiring Agent, Reddit Agent, Sales Agent, Research Agent, SOP Agent.
                An agent needs a <em>Gateway</em> to actually do things outside the chat.
              </p>
              <p>
                <strong>What is a Gateway?</strong> It&apos;s the connection that lets an
                agent run real-world actions — call APIs, post to Discord, read files,
                execute scripts. Without a Gateway an agent can only think, not act.
                The local OpenClaw gateway is what Clawdius itself runs on.
              </p>
            </Section>

            <Section id="control" title="7. Control">
              <p>
                Live operations center. It shows active agents, connected devices (CLAW
                nodes that heartbeat in), running tasks, paused jobs, background workers,
                errors, and recent activity. Think of it as your &quot;what&apos;s running right now&quot;
                dashboard.
              </p>
            </Section>

            <Section id="workflows" title="8. Workflows">
              <p>
                Repeatable step-by-step automations. Examples:
              </p>
              <ul className="list-disc pl-5 space-y-0.5">
                <li>Daily AI news scan → summarize → post to Discord</li>
                <li>Reddit lead scrape → qualify → export sheet → draft outreach</li>
                <li>Instagram screenshot → generate replies → hand to chatter</li>
                <li>SOP request → draft → ask for approval → publish to Notion</li>
              </ul>
              <p>
                Today the page ships with three system workflows (Health Check, Deploy,
                Error Detect) plus custom workflows you can save yourself.
              </p>
            </Section>

            <Section id="skills" title="9. Skills">
              <p>
                Reusable abilities an agent can call — like tools in a toolbox.
                Examples: read a screenshot, draft a DM reply, search memory,
                summarize a doc, post to Discord, run a PhantomBuster job, open an
                AdsPower profile. Skills live on a Gateway; connect one and install
                skills onto it to make them available to your agents.
              </p>
            </Section>

            <Section id="logs" title="10. Logs">
              <p>
                History of what happened — agent runs, errors, actions, API events,
                background jobs. First place to look when something went wrong or you
                want proof of an automated run.
              </p>
            </Section>

            <Section id="save" title="11. Save">
              <p>
                The Save button in the sidebar commits and pushes recent changes in this
                repo to GitHub. Useful for snapshotting the state of the app before risky
                changes.
              </p>
            </Section>

            <Section id="settings" title="12. Settings">
              <p>
                App credentials and system behavior. Holds API keys
                (OpenAI / Claude / Gemini), GitHub credentials for Save, Telegram
                remote-control setup, and branding. All keys are encrypted server-side.
              </p>
            </Section>

            <Section id="users" title="13. Users">
              <p>
                Access control. Invite people by email, assign a role (Owner / Builder /
                Viewer), and manage who can sign in. Invited roles are held in the
                allowlist as <em>pending</em> until the person first signs in — the role
                is then applied automatically.
              </p>
            </Section>

            <Section id="integrations" title="14. Integrations">
              <p>
                External tools and services — Discord, Telegram, Obsidian, Notion, Google,
                AdsPower, PhantomBuster, OpenAI, Claude, and other APIs. Owner-only.
                Keys entered here are stored encrypted in the DB.
              </p>
            </Section>

            {/* ── Operational sections ───────────────────────────────────── */}

            <Section id="multitasking" title="How to multitask with Digidle OS">
              <ol className="list-decimal pl-5 space-y-1">
                <li>Use <strong>Clawdius</strong> for the main conversation — strategy, triage, thinking out loud.</li>
                <li>Use <strong>Agents</strong> for jobs that should run on their own schedule or on a trigger.</li>
                <li>Use <strong>Workflows</strong> for repeatable multi-step processes you trigger over and over.</li>
                <li>Use <strong>Boards</strong> to track progress of human + agent work.</li>
                <li>Use <strong>Control</strong> to see what&apos;s actively running right now.</li>
                <li>Use <strong>Logs</strong> when you need to debug what happened.</li>
                <li>Use <strong>Memory</strong> (and later Obsidian) so agents share the same business context you have.</li>
              </ol>
              <p>
                Rule of thumb: if you&apos;re telling Clawdius the same thing more than twice,
                it belongs in Memory. If you&apos;re doing the same multi-step thing more than
                twice, it belongs in a Workflow or Agent.
              </p>
            </Section>

            <Section id="obsidian" title="Obsidian Setup (planned)">
              <p>
                Today: Memory is local to Digidle OS (localStorage entries + journal).
                It does <strong>not</strong> read your Obsidian vault yet.
              </p>
              <p>Planned rollout — simplest-first:</p>
              <ol className="list-decimal pl-5 space-y-1">
                <li>Setting for your local Obsidian vault path (e.g. <Code>/Users/zachary/Documents/Zachs Brain/brain</Code>).</li>
                <li>Electron reads markdown files from that folder locally — never uploaded to a server.</li>
                <li>Memory page shows the vault&apos;s folder tree and notes.</li>
                <li>Search notes by title / content.</li>
                <li>Select a note and inject it into Clawdius&apos;s context for the next message.</li>
              </ol>
              <p>
                This uses local file-system reads under Electron only; there&apos;s no cloud
                sync of your vault. Your brain stays on your disk.
              </p>
            </Section>

            <Section id="voice" title="Voice Mode (planned)">
              <p>
                Goal: talk to Clawdius through your headset.
              </p>
              <p>
                Intended path: microphone input → speech-to-text → Clawdius &shy;→ text-to-speech → headset output.
              </p>
              <p>
                First shipping version will use the browser/Electron Web Speech API (no
                extra server, works offline for recognition on most macOS builds):
              </p>
              <ol className="list-decimal pl-5 space-y-1">
                <li>Microphone button in the Clawdius chat header.</li>
                <li>Hold or click → speech-to-text fills the input box.</li>
                <li>Release → Clawdius answers in text; optional &ldquo;speak reply&rdquo; toggle for TTS.</li>
              </ol>
              <p>
                Until the mic button is enabled the icon will stay greyed out so there are
                no fake controls.
              </p>
            </Section>

            <Section id="branding" title="Branding / Logo">
              <p>
                The sidebar logo reads from <Code>frontend/public/logo.png</Code>.
              </p>
              <p>To change it:</p>
              <ol className="list-decimal pl-5 space-y-1">
                <li>Replace <Code>frontend/public/logo.png</Code> with your own PNG (recommended 40×40, transparent background).</li>
                <li>If the Electron app is running, quit and reopen it — or reload the window (<Code>⌘R</Code>) to pick up the new file.</li>
              </ol>
              <p>
                The wordmark next to the logo uses the environment variable{" "}
                <Code>NEXT_PUBLIC_APP_NAME</Code>, defaulting to <em>Digidle OS</em>.
                Set that in your Vercel env (or <Code>frontend/.env.local</Code>) to
                change the product name without touching the logo.
              </p>
            </Section>

          </div>
        </main>
      </SignedIn>
    </DashboardShell>
  );
}
