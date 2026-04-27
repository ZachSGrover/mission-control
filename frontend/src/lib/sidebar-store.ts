// Sidebar layout store — mc_sidebar_layout_v1
//
// Persists the user's customized sidebar structure: category order, item order,
// renames, hides, and any custom categories/items they've added. Falls back to
// a seed layout (matching the original hardcoded sidebar) if storage is empty
// or corrupt.
//
// Non-link UI (the Save action button, role-gated items) is handled at render
// time by the sidebar component, not stored here.

const KEY = "mc_sidebar_layout_v1";

// ── Icon registry ────────────────────────────────────────────────────────────
// iconKey is a string so the layout stays serializable. The sidebar component
// resolves these to lucide-react components.

export const SIDEBAR_ICON_KEYS = [
  "MessageSquare",
  "FolderOpen",
  "Brain",
  "CalendarDays",
  "Layout",
  "Bot",
  "Network",
  "GitBranch",
  "Wrench",
  "ClipboardList",
  "Activity",
  "BookOpen",
  "Settings",
  "Users",
  "Plug",
  "Circle",
  "Star",
  "Pin",
  "Hash",
  "Folder",
  "CloudUpload",
] as const;
export type SidebarIconKey = (typeof SIDEBAR_ICON_KEYS)[number];

function isIconKey(v: unknown): v is SidebarIconKey {
  return typeof v === "string" && (SIDEBAR_ICON_KEYS as readonly string[]).includes(v);
}

// ── Active-match mode ────────────────────────────────────────────────────────

export const ACTIVE_MODES = ["exact", "startsWith"] as const;
export type ActiveMode = (typeof ACTIVE_MODES)[number];

// ── Item kind ────────────────────────────────────────────────────────────────
// "link"   — renders as a Next.js <Link> to href
// "action" — renders as a special button component keyed by actionKey
//            (e.g. actionKey "git-save" → Save-to-GitHub button)

export const ITEM_KINDS = ["link", "action"] as const;
export type ItemKind = (typeof ITEM_KINDS)[number];

export const ACTION_KEYS = ["git-save"] as const;
export type ActionKey = (typeof ACTION_KEYS)[number];

// ── Types ────────────────────────────────────────────────────────────────────

export interface SidebarItemDef {
  id: string;
  label: string;
  href: string;
  iconKey: SidebarIconKey;
  order: number;
  hidden: boolean;
  custom: boolean;
  activeMode: ActiveMode;
  kind: ItemKind;
  /** For `kind: "action"` only — identifies which action component to render. */
  actionKey?: ActionKey;
  /** For Settings, excludes paths like /settings/users from counting as active. */
  excludePrefixes?: string[];
  /** Role gating — only rendered if user has this role. */
  requireRole?: "owner";
  createdAt: string;
  updatedAt: string;
}

export interface SidebarCategoryDef {
  id: string;
  label: string;
  order: number;
  collapsed: boolean;
  custom: boolean;
  items: SidebarItemDef[];
  createdAt: string;
  updatedAt: string;
}

export interface SidebarLayout {
  version: 1;
  categories: SidebarCategoryDef[];
}

// ── Seed (mirrors the original hardcoded sidebar) ────────────────────────────

const SEED_DATE = "2026-04-24T00:00:00.000Z";

function item(
  id: string,
  label: string,
  href: string,
  iconKey: SidebarIconKey,
  order: number,
  opts: Partial<SidebarItemDef> = {},
): SidebarItemDef {
  return {
    id,
    label,
    href,
    iconKey,
    order,
    hidden: false,
    custom: false,
    activeMode: opts.activeMode ?? "startsWith",
    kind: opts.kind ?? "link",
    actionKey: opts.actionKey,
    excludePrefixes: opts.excludePrefixes,
    requireRole: opts.requireRole,
    createdAt: SEED_DATE,
    updatedAt: SEED_DATE,
  };
}

const SEED_LAYOUT: SidebarLayout = {
  version: 1,
  categories: [
    {
      id: "chat", label: "Chat", order: 0, collapsed: false, custom: false,
      createdAt: SEED_DATE, updatedAt: SEED_DATE,
      items: [
        item("claw", "Chat", "/chat", "MessageSquare", 0, { activeMode: "exact" }),
      ],
    },
    {
      id: "memory", label: "Memory", order: 1, collapsed: false, custom: false,
      createdAt: SEED_DATE, updatedAt: SEED_DATE,
      items: [
        item("projects", "Projects", "/projects", "FolderOpen", 0),
        item("memory", "Memory", "/memory", "Brain", 1, { activeMode: "exact" }),
        item("calendar", "Calendar", "/calendar", "CalendarDays", 2),
      ],
    },
    {
      id: "automation", label: "Automation", order: 2, collapsed: false, custom: false,
      createdAt: SEED_DATE, updatedAt: SEED_DATE,
      items: [
        item("boards", "Boards", "/boards", "Layout", 0),
        item("agents", "Agents", "/agents", "Bot", 1),
        item("control", "Control", "/control", "Network", 2),
        item("workflows", "Workflows", "/workflows", "GitBranch", 3),
        item("skills", "Skills", "/skills", "Wrench", 4),
        item("runbooks", "Runbooks", "/runbooks", "ClipboardList", 5),
        item("logs", "Logs", "/activity", "Activity", 6),
      ],
    },
    {
      id: "system", label: "System", order: 3, collapsed: false, custom: false,
      createdAt: SEED_DATE, updatedAt: SEED_DATE,
      items: [
        item("save", "Save", "#save", "CloudUpload", 0, {
          kind: "action",
          actionKey: "git-save",
          activeMode: "exact",
        }),
        item("guide", "Guide", "/guide", "BookOpen", 1),
        item("settings", "Settings", "/settings", "Settings", 2, {
          excludePrefixes: ["/settings/users", "/settings/integrations"],
        }),
        item("users", "Users", "/settings/users", "Users", 3, { requireRole: "owner" }),
        item("integrations", "Integrations", "/settings/integrations", "Plug", 4, { requireRole: "owner" }),
      ],
    },
  ],
};

// One-shot label migrations for core items renamed in past releases.
// `from` lists every historical seed default; only those exact strings are
// rewritten, so any user-customized rename (e.g. "Main") is left alone.
const LABEL_MIGRATIONS: Record<string, { from: string[]; to: string }> = {
  claw: { from: ["Claw", "Clawdius"], to: "Chat" },
};

// IDs of items/categories that must always survive (hide allowed, delete not).
const CORE_CATEGORY_IDS = new Set(["chat", "memory", "automation", "system"]);
const CORE_ITEM_IDS = new Set([
  "claw", "projects", "memory", "calendar",
  "boards", "agents", "control", "workflows", "skills", "runbooks", "logs",
  "save", "guide", "settings", "users", "integrations",
]);

export function isCoreCategory(id: string): boolean {
  return CORE_CATEGORY_IDS.has(id);
}
export function isCoreItem(id: string): boolean {
  return CORE_ITEM_IDS.has(id);
}

// ── Validation / migration ───────────────────────────────────────────────────

function asBool(v: unknown, fallback: boolean): boolean {
  return typeof v === "boolean" ? v : fallback;
}

function migrateItem(raw: unknown, fallbackOrder: number): SidebarItemDef | null {
  if (typeof raw !== "object" || raw === null) return null;
  const o = raw as Record<string, unknown>;
  if (typeof o.id !== "string" || typeof o.label !== "string" || typeof o.href !== "string") {
    return null;
  }
  return {
    id: o.id,
    label: o.label,
    href: o.href,
    iconKey: isIconKey(o.iconKey) ? o.iconKey : "Circle",
    order: typeof o.order === "number" ? o.order : fallbackOrder,
    hidden: asBool(o.hidden, false),
    custom: asBool(o.custom, false),
    activeMode: o.activeMode === "exact" ? "exact" : "startsWith",
    kind: o.kind === "action" ? "action" : "link",
    actionKey: o.actionKey === "git-save" ? "git-save" : undefined,
    excludePrefixes: Array.isArray(o.excludePrefixes)
      ? o.excludePrefixes.filter((v): v is string => typeof v === "string")
      : undefined,
    requireRole: o.requireRole === "owner" ? "owner" : undefined,
    createdAt: typeof o.createdAt === "string" ? o.createdAt : SEED_DATE,
    updatedAt: typeof o.updatedAt === "string" ? o.updatedAt : SEED_DATE,
  };
}

function migrateCategory(raw: unknown, fallbackOrder: number): SidebarCategoryDef | null {
  if (typeof raw !== "object" || raw === null) return null;
  const o = raw as Record<string, unknown>;
  if (typeof o.id !== "string" || typeof o.label !== "string") return null;
  const rawItems = Array.isArray(o.items) ? o.items : [];
  const items: SidebarItemDef[] = [];
  for (let i = 0; i < rawItems.length; i++) {
    const m = migrateItem(rawItems[i], i);
    if (m) items.push(m);
  }
  return {
    id: o.id,
    label: o.label,
    order: typeof o.order === "number" ? o.order : fallbackOrder,
    collapsed: asBool(o.collapsed, false),
    custom: asBool(o.custom, false),
    items,
    createdAt: typeof o.createdAt === "string" ? o.createdAt : SEED_DATE,
    updatedAt: typeof o.updatedAt === "string" ? o.updatedAt : SEED_DATE,
  };
}

function migrateLayout(raw: unknown): SidebarLayout | null {
  if (typeof raw !== "object" || raw === null) return null;
  const o = raw as Record<string, unknown>;
  const rawCats = Array.isArray(o.categories) ? o.categories : null;
  if (!rawCats) return null;
  const categories: SidebarCategoryDef[] = [];
  for (let i = 0; i < rawCats.length; i++) {
    const m = migrateCategory(rawCats[i], i);
    if (m) categories.push(m);
  }
  if (categories.length === 0) return null;
  return { version: 1, categories };
}

/**
 * Merge a migrated stored layout with the seed so any newly-added core
 * categories/items (e.g. Runbooks after an upgrade) appear automatically,
 * without clobbering user reorders/renames/hides.
 */
function mergeWithSeed(stored: SidebarLayout): SidebarLayout {
  const seedById = new Map<string, SidebarCategoryDef>();
  for (const c of SEED_LAYOUT.categories) seedById.set(c.id, c);

  const storedById = new Map<string, SidebarCategoryDef>();
  for (const c of stored.categories) storedById.set(c.id, c);

  // Global set of item IDs present anywhere in stored layout — used to
  // prevent re-adding a seed item that the user relocated to another category.
  const globalItemIds = new Set<string>();
  for (const c of stored.categories) {
    for (const it of c.items) globalItemIds.add(it.id);
  }

  const merged: SidebarCategoryDef[] = [];

  // Keep user-ordered existing categories first, then append any seed
  // categories not yet present.
  for (const c of stored.categories) {
    const seed = seedById.get(c.id);
    if (seed) {
      const itemById = new Map<string, SidebarItemDef>();
      for (const it of c.items) itemById.set(it.id, it);
      const mergedItems: SidebarItemDef[] = [];
      // Keep stored items in their user order
      for (const it of c.items) {
        const seedItem = seed.items.find((s) => s.id === it.id);
        if (seedItem) {
          // Core item: force href, requireRole, kind, actionKey to seed values
          // (prevent breakage); keep user's label / order / hidden / iconKey.
          const migration = LABEL_MIGRATIONS[it.id];
          const migratedLabel =
            migration && migration.from.includes(it.label) ? migration.to : it.label;
          mergedItems.push({
            ...it,
            label: migratedLabel,
            href: seedItem.href,
            requireRole: seedItem.requireRole,
            activeMode: seedItem.activeMode,
            excludePrefixes: seedItem.excludePrefixes,
            kind: seedItem.kind,
            actionKey: seedItem.actionKey,
            iconKey: isIconKey(it.iconKey) ? it.iconKey : seedItem.iconKey,
            custom: false,
          });
        } else {
          mergedItems.push(it);
        }
      }
      // Insert any missing seed items at their seed-relative position —
      // so upgrades feel natural (e.g. a newly-seeded Save lands at the
      // top of System, not the bottom). Skip if the user already relocated
      // the item to another category.
      for (let si = 0; si < seed.items.length; si++) {
        const s = seed.items[si];
        if (itemById.has(s.id)) continue;
        if (globalItemIds.has(s.id)) continue;
        let insertAt = mergedItems.length;
        for (let sj = si + 1; sj < seed.items.length; sj++) {
          const nextId = seed.items[sj].id;
          const pos = mergedItems.findIndex((it) => it.id === nextId);
          if (pos !== -1) { insertAt = pos; break; }
        }
        mergedItems.splice(insertAt, 0, s);
        itemById.set(s.id, s);
        globalItemIds.add(s.id);
      }
      merged.push({ ...c, label: c.label, items: mergedItems, custom: false });
    } else {
      merged.push(c);
    }
  }
  for (const s of SEED_LAYOUT.categories) {
    if (!storedById.has(s.id)) merged.push(s);
  }
  return { version: 1, categories: normalizeOrders(merged) };
}

function normalizeOrders(cats: SidebarCategoryDef[]): SidebarCategoryDef[] {
  return cats.map((c, ci) => ({
    ...c,
    order: ci,
    items: c.items.map((it, ii) => ({ ...it, order: ii })),
  }));
}

// ── CRUD ─────────────────────────────────────────────────────────────────────

/**
 * Always returns the seed layout — deterministic and safe to call during SSR
 * or as a `useState` initializer. Use this instead of `loadLayout()` for the
 * initial state, then swap to `loadLayout()` inside `useEffect` so server and
 * client first renders match.
 */
export function getServerLayout(): SidebarLayout {
  return SEED_LAYOUT;
}

export function loadLayout(): SidebarLayout {
  if (typeof window === "undefined") return SEED_LAYOUT;
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const parsed: unknown = JSON.parse(raw);
      const migrated = migrateLayout(parsed);
      if (migrated) {
        const merged = mergeWithSeed(migrated);
        try { localStorage.setItem(KEY, JSON.stringify(merged)); } catch { /* quota */ }
        return merged;
      }
    }
  } catch {
    try { localStorage.removeItem(KEY); } catch { /* ignore */ }
  }
  try { localStorage.setItem(KEY, JSON.stringify(SEED_LAYOUT)); } catch { /* quota */ }
  return SEED_LAYOUT;
}

export function saveLayout(layout: SidebarLayout): void {
  if (typeof window === "undefined") return;
  try { localStorage.setItem(KEY, JSON.stringify(normalizeLayout(layout))); } catch { /* quota */ }
}

export function resetLayout(): SidebarLayout {
  if (typeof window !== "undefined") {
    try { localStorage.setItem(KEY, JSON.stringify(SEED_LAYOUT)); } catch { /* quota */ }
  }
  return SEED_LAYOUT;
}

export function normalizeLayout(layout: SidebarLayout): SidebarLayout {
  return { version: 1, categories: normalizeOrders(layout.categories) };
}

// ── Category operations ──────────────────────────────────────────────────────

export function moveCategory(layout: SidebarLayout, id: string, dir: -1 | 1): SidebarLayout {
  const cats = [...layout.categories];
  const idx = cats.findIndex((c) => c.id === id);
  if (idx === -1) return layout;
  const to = idx + dir;
  if (to < 0 || to >= cats.length) return layout;
  [cats[idx], cats[to]] = [cats[to], cats[idx]];
  return normalizeLayout({ ...layout, categories: cats });
}

function slugify(input: string): string {
  return input
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48) || "custom";
}

export function addCategory(layout: SidebarLayout, label: string): SidebarLayout {
  const now = new Date().toISOString();
  const base = slugify(label);
  let id = `cat-${base}`;
  const existing = new Set(layout.categories.map((c) => c.id));
  let n = 1;
  while (existing.has(id)) { id = `cat-${base}-${n++}`; }
  const cat: SidebarCategoryDef = {
    id,
    label: label.trim() || "Untitled",
    order: layout.categories.length,
    collapsed: false,
    custom: true,
    items: [],
    createdAt: now,
    updatedAt: now,
  };
  return normalizeLayout({ ...layout, categories: [...layout.categories, cat] });
}

export function renameCategory(layout: SidebarLayout, id: string, label: string): SidebarLayout {
  const now = new Date().toISOString();
  const cats = layout.categories.map((c) =>
    c.id === id ? { ...c, label: label.trim() || c.label, updatedAt: now } : c,
  );
  return normalizeLayout({ ...layout, categories: cats });
}

export function deleteCategory(layout: SidebarLayout, id: string): SidebarLayout {
  if (isCoreCategory(id)) return layout;
  return normalizeLayout({
    ...layout,
    categories: layout.categories.filter((c) => c.id !== id),
  });
}

// ── Item operations ──────────────────────────────────────────────────────────

function mapItemsOf(layout: SidebarLayout, catId: string, fn: (items: SidebarItemDef[]) => SidebarItemDef[]): SidebarLayout {
  const cats = layout.categories.map((c) => (c.id === catId ? { ...c, items: fn(c.items) } : c));
  return normalizeLayout({ ...layout, categories: cats });
}

export function moveItem(layout: SidebarLayout, catId: string, itemId: string, dir: -1 | 1): SidebarLayout {
  return mapItemsOf(layout, catId, (items) => {
    const next = [...items];
    const idx = next.findIndex((it) => it.id === itemId);
    if (idx === -1) return items;
    const to = idx + dir;
    if (to < 0 || to >= next.length) return items;
    [next[idx], next[to]] = [next[to], next[idx]];
    return next;
  });
}

export function moveItemToCategory(
  layout: SidebarLayout,
  fromCatId: string,
  itemId: string,
  toCatId: string,
): SidebarLayout {
  if (fromCatId === toCatId) return layout;
  const src = layout.categories.find((c) => c.id === fromCatId);
  if (!src) return layout;
  const item = src.items.find((i) => i.id === itemId);
  if (!item) return layout;
  const cats = layout.categories.map((c) => {
    if (c.id === fromCatId) return { ...c, items: c.items.filter((i) => i.id !== itemId) };
    if (c.id === toCatId) return { ...c, items: [...c.items, { ...item, updatedAt: new Date().toISOString() }] };
    return c;
  });
  return normalizeLayout({ ...layout, categories: cats });
}

export function renameItem(
  layout: SidebarLayout,
  catId: string,
  itemId: string,
  label: string,
): SidebarLayout {
  return mapItemsOf(layout, catId, (items) =>
    items.map((it) =>
      it.id === itemId ? { ...it, label: label.trim() || it.label, updatedAt: new Date().toISOString() } : it,
    ),
  );
}

export function setItemHidden(
  layout: SidebarLayout,
  catId: string,
  itemId: string,
  hidden: boolean,
): SidebarLayout {
  return mapItemsOf(layout, catId, (items) =>
    items.map((it) =>
      it.id === itemId ? { ...it, hidden, updatedAt: new Date().toISOString() } : it,
    ),
  );
}

export function deleteItem(
  layout: SidebarLayout,
  catId: string,
  itemId: string,
): SidebarLayout {
  if (isCoreItem(itemId)) return layout;
  return mapItemsOf(layout, catId, (items) => items.filter((it) => it.id !== itemId));
}

export function addItem(
  layout: SidebarLayout,
  catId: string,
  opts: { label: string; href?: string; iconKey?: SidebarIconKey },
): SidebarLayout {
  const now = new Date().toISOString();
  const label = opts.label.trim() || "Untitled";
  const base = slugify(label);
  let id = `item-${base}`;
  const existing = new Set(
    layout.categories.flatMap((c) => c.items.map((i) => i.id)),
  );
  let n = 1;
  while (existing.has(id)) { id = `item-${base}-${n++}`; }
  const href = (opts.href?.trim() || `/custom/${base}`);
  const newItem: SidebarItemDef = {
    id,
    label,
    href: href.startsWith("/") ? href : `/${href}`,
    iconKey: opts.iconKey ?? "Hash",
    order: Number.MAX_SAFE_INTEGER,
    hidden: false,
    custom: true,
    activeMode: "startsWith",
    kind: "link",
    createdAt: now,
    updatedAt: now,
  };
  return mapItemsOf(layout, catId, (items) => [...items, newItem]);
}
