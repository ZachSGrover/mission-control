╔══════════════════════════════════════════════════════╗
║   WORKING BACKUP — v1   (07.05.2026)                 ║
╚══════════════════════════════════════════════════════╝

Status: FULLY WORKING — DMs sending confirmed

Files:
  dm_bot.py       — Main bot (Two-Pass architecture)
  server.py       — HTTP server (ThreadedHTTPServer, port 8765)
  xdashboard.html — Dashboard with live scan + send status
  scan_test.py    — Standalone scan test (no sending)

Key fixes included in this version:
  ✓ Two-Pass: Pass 1 scans full list (no navigation away)
              Pass 2 sends to collected URLs
  ✓ Selectors: JS querySelectorAll for chat links (Playwright
               locator doesn't work, X.com uses shadow-like DOM)
  ✓ Composer:  [data-testid*="composer"] — confirmed working
  ✓ Scroll:    Walks up DOM to find scrollable ancestor of chat links
  ✓ Load wait: Waits for [data-testid="dm-search-bar"] + networkidle
  ✓ Dashboard: Scan phase shows live count, scan_done banner,
               then progress bar for sending

To restore: copy these 4 files back to Monthly revenue/
