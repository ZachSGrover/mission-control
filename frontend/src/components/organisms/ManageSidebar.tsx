"use client";

import { useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  Eye,
  EyeOff,
  Pencil,
  Plus,
  RotateCcw,
  Trash2,
  X,
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
  addCategory,
  addItem,
  deleteCategory,
  deleteItem,
  isCoreCategory,
  isCoreItem,
  moveCategory,
  moveItem,
  moveItemToCategory,
  renameCategory,
  renameItem,
  resetLayout,
  setItemHidden,
  type SidebarCategoryDef,
  type SidebarItemDef,
  type SidebarLayout,
} from "@/lib/sidebar-store";

// ── Inline editable label ────────────────────────────────────────────────────

function InlineEditLabel({
  value,
  onCommit,
  className,
}: {
  value: string;
  onCommit: (next: string) => void;
  className?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);

  if (!editing) {
    return (
      <div className="flex items-center gap-1.5 group min-w-0">
        <span className={`truncate ${className ?? ""}`}>{value}</span>
        <button
          type="button"
          className="opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
          onClick={() => { setDraft(value); setEditing(true); }}
          title="Rename"
          style={{ color: "var(--text-quiet)" }}
        >
          <Pencil className="h-3 w-3" />
        </button>
      </div>
    );
  }

  return (
    <input
      autoFocus
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => { onCommit(draft); setEditing(false); }}
      onKeyDown={(e) => {
        if (e.key === "Enter") { onCommit(draft); setEditing(false); }
        if (e.key === "Escape") { setEditing(false); }
      }}
      className={`rounded px-1.5 py-0.5 text-sm outline-none ${className ?? ""}`}
      style={{
        background: "var(--surface-2, var(--surface))",
        border: "1px solid var(--border)",
        color: "var(--text)",
      }}
    />
  );
}

// ── Item row ─────────────────────────────────────────────────────────────────

function ItemRow({
  item,
  category,
  categories,
  onLayoutChange,
  canMoveUp,
  canMoveDown,
  layout,
}: {
  item: SidebarItemDef;
  category: SidebarCategoryDef;
  categories: SidebarCategoryDef[];
  layout: SidebarLayout;
  canMoveUp: boolean;
  canMoveDown: boolean;
  onLayoutChange: (next: SidebarLayout) => void;
}) {
  const coreItem = isCoreItem(item.id);
  const roleTag = item.requireRole ? ` (${item.requireRole})` : "";

  return (
    <div
      className="flex items-center gap-2 pl-4 pr-2 py-1.5 rounded-md"
      style={{
        background: item.hidden ? "transparent" : "var(--surface)",
        opacity: item.hidden ? 0.5 : 1,
      }}
    >
      {/* Move up/down */}
      <div className="flex flex-col shrink-0">
        <button
          type="button"
          className="disabled:opacity-30"
          disabled={!canMoveUp}
          onClick={() => onLayoutChange(moveItem(layout, category.id, item.id, -1))}
          title="Move up"
          style={{ color: "var(--text-quiet)" }}
        >
          <ArrowUp className="h-3 w-3" />
        </button>
        <button
          type="button"
          className="disabled:opacity-30"
          disabled={!canMoveDown}
          onClick={() => onLayoutChange(moveItem(layout, category.id, item.id, 1))}
          title="Move down"
          style={{ color: "var(--text-quiet)" }}
        >
          <ArrowDown className="h-3 w-3" />
        </button>
      </div>

      {/* Label */}
      <div className="flex-1 min-w-0">
        <InlineEditLabel
          value={item.label}
          onCommit={(next) => onLayoutChange(renameItem(layout, category.id, item.id, next))}
          className="text-sm"
        />
        <div className="flex items-center gap-2">
          <span className="text-[10px] truncate" style={{ color: "var(--text-quiet)" }}>
            {item.kind === "action" && item.actionKey === "git-save"
              ? `action · GitHub commit + push${roleTag}`
              : `${item.href}${roleTag}`}
          </span>
          {item.custom && (
            <span
              className="text-[9px] uppercase tracking-wider px-1 rounded"
              style={{ background: "var(--accent-soft)", color: "var(--accent-strong)" }}
            >
              custom
            </span>
          )}
          {item.kind === "action" && (
            <span
              className="text-[9px] uppercase tracking-wider px-1 rounded"
              style={{ background: "rgba(148, 163, 184, 0.15)", color: "var(--text-quiet)" }}
              title="Action — label, icon, position, and category are editable. Only the underlying function is locked."
            >
              action
            </span>
          )}
        </div>
      </div>

      {/* Move to category */}
      <select
        value={category.id}
        onChange={(e) => {
          const to = e.target.value;
          if (to !== category.id) {
            onLayoutChange(moveItemToCategory(layout, category.id, item.id, to));
          }
        }}
        className="text-xs rounded px-1.5 py-1 shrink-0"
        style={{
          background: "var(--surface-2, var(--surface))",
          border: "1px solid var(--border)",
          color: "var(--text-muted)",
        }}
        title="Move to category"
      >
        {categories.map((c) => (
          <option key={c.id} value={c.id}>{c.label}</option>
        ))}
      </select>

      {/* Hide/show */}
      <button
        type="button"
        onClick={() => onLayoutChange(setItemHidden(layout, category.id, item.id, !item.hidden))}
        title={item.hidden ? "Show" : "Hide"}
        className="shrink-0 rounded p-1"
        style={{ color: item.hidden ? "var(--text-quiet)" : "var(--accent-strong)" }}
      >
        {item.hidden ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
      </button>

      {/* Delete (custom only) */}
      {!coreItem && (
        <button
          type="button"
          onClick={() => {
            if (confirm(`Delete item "${item.label}"?`)) {
              onLayoutChange(deleteItem(layout, category.id, item.id));
            }
          }}
          title="Delete item"
          className="shrink-0 rounded p-1"
          style={{ color: "var(--text-quiet)" }}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}

// ── Category block ───────────────────────────────────────────────────────────

function CategoryBlock({
  category,
  categories,
  layout,
  onLayoutChange,
  canMoveUp,
  canMoveDown,
}: {
  category: SidebarCategoryDef;
  categories: SidebarCategoryDef[];
  layout: SidebarLayout;
  onLayoutChange: (next: SidebarLayout) => void;
  canMoveUp: boolean;
  canMoveDown: boolean;
}) {
  const coreCat = isCoreCategory(category.id);

  const handleAddItem = () => {
    const name = prompt("Item name?");
    if (!name || !name.trim()) return;
    const href = prompt(
      "Route/path? (optional — blank generates /custom/<slug>)",
      "",
    );
    onLayoutChange(addItem(layout, category.id, { label: name, href: href ?? undefined }));
  };

  return (
    <div
      className="rounded-lg border p-3 flex flex-col gap-2"
      style={{ background: "var(--surface)", borderColor: "var(--border)" }}
    >
      {/* Header */}
      <div className="flex items-center gap-2">
        <div className="flex flex-col shrink-0">
          <button
            type="button"
            disabled={!canMoveUp}
            onClick={() => onLayoutChange(moveCategory(layout, category.id, -1))}
            title="Move category up"
            className="disabled:opacity-30"
            style={{ color: "var(--text-quiet)" }}
          >
            <ArrowUp className="h-3 w-3" />
          </button>
          <button
            type="button"
            disabled={!canMoveDown}
            onClick={() => onLayoutChange(moveCategory(layout, category.id, 1))}
            title="Move category down"
            className="disabled:opacity-30"
            style={{ color: "var(--text-quiet)" }}
          >
            <ArrowDown className="h-3 w-3" />
          </button>
        </div>

        <div className="flex-1 min-w-0">
          <InlineEditLabel
            value={category.label}
            onCommit={(next) => onLayoutChange(renameCategory(layout, category.id, next))}
            className="text-sm font-semibold uppercase tracking-wider"
          />
          {category.custom && (
            <span
              className="text-[9px] uppercase tracking-wider px-1 rounded"
              style={{ background: "var(--accent-soft)", color: "var(--accent-strong)" }}
            >
              custom
            </span>
          )}
        </div>

        <Button size="sm" variant="ghost" onClick={handleAddItem} title="Add item">
          <Plus className="h-3.5 w-3.5 mr-1" />
          Add Item
        </Button>

        {!coreCat && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              if (confirm(`Delete category "${category.label}"? Items will be removed.`)) {
                onLayoutChange(deleteCategory(layout, category.id));
              }
            }}
            title="Delete category"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        )}
      </div>

      {/* Items */}
      <div className="flex flex-col gap-1">
        {category.items.length === 0 ? (
          <p className="text-xs italic pl-4" style={{ color: "var(--text-quiet)" }}>
            No items. Click Add Item.
          </p>
        ) : (
          category.items.map((it, idx) => (
            <ItemRow
              key={it.id}
              item={it}
              category={category}
              categories={categories}
              layout={layout}
              canMoveUp={idx > 0}
              canMoveDown={idx < category.items.length - 1}
              onLayoutChange={onLayoutChange}
            />
          ))
        )}
      </div>
    </div>
  );
}

// ── Panel ────────────────────────────────────────────────────────────────────

export function ManageSidebar({
  open,
  onOpenChange,
  layout,
  onLayoutChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  layout: SidebarLayout;
  onLayoutChange: (next: SidebarLayout) => void;
}) {
  const handleAddCategory = () => {
    const name = prompt("Category name?");
    if (!name || !name.trim()) return;
    onLayoutChange(addCategory(layout, name));
  };

  const handleReset = () => {
    if (confirm("Reset sidebar to default? Any custom categories and items will be removed.")) {
      onLayoutChange(resetLayout());
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center justify-between gap-4">
            <span>Manage Sidebar</span>
            <Button size="sm" variant="ghost" onClick={handleReset} title="Reset to default">
              <RotateCcw className="h-3.5 w-3.5 mr-1" />
              Reset to default
            </Button>
          </DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-3 max-h-[65vh] overflow-auto pr-1">
          {layout.categories.map((c, idx) => (
            <CategoryBlock
              key={c.id}
              category={c}
              categories={layout.categories}
              layout={layout}
              onLayoutChange={onLayoutChange}
              canMoveUp={idx > 0}
              canMoveDown={idx < layout.categories.length - 1}
            />
          ))}
        </div>

        <DialogFooter className="flex items-center justify-between w-full gap-2">
          <Button size="sm" variant="outline" onClick={handleAddCategory}>
            <Plus className="h-3.5 w-3.5 mr-1" />
            Add Category
          </Button>
          <Button size="sm" variant="ghost" onClick={() => onOpenChange(false)}>
            <X className="h-3.5 w-3.5 mr-1" />
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
