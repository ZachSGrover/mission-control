// Project definitions store — mc_projects_v1

const KEY = "mc_projects_v1";

export interface ProjectDef {
  id: string;
  name: string;
  description: string;
  status: "active" | "paused" | "archived";
  color: string; // tailwind color class segment, e.g. "emerald", "blue"
  area: string;
  createdAt: string;
  updatedAt: string;
}

// ── Seed data ─────────────────────────────────────────────────────────────────

const DEFAULT_PROJECTS: ProjectDef[] = [
  {
    id: "seed-digidle",
    name: "Digidle",
    description: "Core product — game development and growth.",
    status: "active",
    color: "emerald",
    area: "Product & Tech",
    createdAt: "2024-01-01T00:00:00.000Z",
    updatedAt: "2024-01-01T00:00:00.000Z",
  },
  {
    id: "seed-modern-sales-agency",
    name: "Modern Sales Agency",
    description: "B2B sales consulting and client pipeline management.",
    status: "active",
    color: "blue",
    area: "Sales",
    createdAt: "2024-01-01T00:00:00.000Z",
    updatedAt: "2024-01-01T00:00:00.000Z",
  },
  {
    id: "seed-modern-athlete",
    name: "Modern Athlete",
    description: "Health, fitness, and performance content and products.",
    status: "active",
    color: "orange",
    area: "Health & Fitness",
    createdAt: "2024-01-01T00:00:00.000Z",
    updatedAt: "2024-01-01T00:00:00.000Z",
  },
  {
    id: "seed-grover-art",
    name: "Grover Art Projects",
    description: "Creative projects, art direction, and visual work.",
    status: "active",
    color: "purple",
    area: "Creative",
    createdAt: "2024-01-01T00:00:00.000Z",
    updatedAt: "2024-01-01T00:00:00.000Z",
  },
  {
    id: "seed-general",
    name: "General",
    description: "Miscellaneous notes and tasks not tied to a specific project.",
    status: "active",
    color: "slate",
    area: "Misc",
    createdAt: "2024-01-01T00:00:00.000Z",
    updatedAt: "2024-01-01T00:00:00.000Z",
  },
];

// ── Validation ────────────────────────────────────────────────────────────────

function isValidProjectDef(p: unknown): p is ProjectDef {
  if (typeof p !== "object" || p === null) return false;
  const obj = p as Record<string, unknown>;
  return (
    typeof obj.id === "string" &&
    typeof obj.name === "string" &&
    typeof obj.description === "string" &&
    (obj.status === "active" || obj.status === "paused" || obj.status === "archived") &&
    typeof obj.color === "string" &&
    typeof obj.area === "string" &&
    typeof obj.createdAt === "string" &&
    typeof obj.updatedAt === "string"
  );
}

// ── CRUD ──────────────────────────────────────────────────────────────────────

export function loadProjects(): ProjectDef[] {
  if (typeof window === "undefined") return DEFAULT_PROJECTS;
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const parsed: unknown = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) {
        const valid = parsed.filter(isValidProjectDef);
        if (valid.length > 0) return valid;
      }
    }
  } catch {
    try { localStorage.removeItem(KEY); } catch { /* ignore */ }
  }
  // Seed defaults on first load
  try {
    localStorage.setItem(KEY, JSON.stringify(DEFAULT_PROJECTS));
  } catch { /* quota */ }
  return DEFAULT_PROJECTS;
}

export function saveProjects(projects: ProjectDef[]): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(KEY, JSON.stringify(projects.filter(isValidProjectDef)));
  } catch { /* quota */ }
}

export function createProject(
  name: string,
  description: string,
  area: string,
  status: ProjectDef["status"] = "active",
  color: string = "slate",
): ProjectDef {
  const now = new Date().toISOString();
  const project: ProjectDef = {
    id: crypto.randomUUID(),
    name: name.trim(),
    description: description.trim(),
    status,
    color,
    area: area.trim() || "General",
    createdAt: now,
    updatedAt: now,
  };
  const existing = loadProjects();
  saveProjects([...existing, project]);
  return project;
}

export function updateProject(id: string, patch: Partial<Omit<ProjectDef, "id" | "createdAt">>): ProjectDef | null {
  const projects = loadProjects();
  const idx = projects.findIndex((p) => p.id === id);
  if (idx === -1) return null;
  const updated: ProjectDef = {
    ...projects[idx],
    ...patch,
    id: projects[idx].id,
    createdAt: projects[idx].createdAt,
    updatedAt: new Date().toISOString(),
  };
  const next = [...projects];
  next[idx] = updated;
  saveProjects(next);
  return updated;
}

export function deleteProject(id: string): boolean {
  const projects = loadProjects();
  const next = projects.filter((p) => p.id !== id);
  if (next.length === projects.length) return false;
  saveProjects(next);
  return true;
}
