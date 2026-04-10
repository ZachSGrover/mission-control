'use strict'

const { app, BrowserWindow, shell } = require('electron')
const path = require('path')
const { spawn } = require('child_process')
const http = require('http')
const net = require('net')
const fs = require('fs')

let mainWindow
let nextProcess
let openclawProcess
let backendProcess

const NEXT_PORT = 3000
const NEXT_URL = `http://localhost:${NEXT_PORT}`
const OPENCLAW_PORT = 18789
const OPENCLAW_BIN = '/Users/zachary/.openclaw/bin/openclaw'
const OPENCLAW_LOG = '/tmp/mission-control-openclaw.log'

const BACKEND_PORT = 8000
const BACKEND_HEALTHZ = `http://localhost:${BACKEND_PORT}/healthz`
const BACKEND_DIR = '/Users/zachary/mission-control/backend'
const BACKEND_BIN = '/Users/zachary/mission-control/backend/.venv/bin/uvicorn'
const BACKEND_LOG = '/tmp/mission-control-backend.log'

const FRONTEND_DIR = path.join(__dirname, '..')
const BUILD_ID_FILE = path.join(FRONTEND_DIR, '.next', 'BUILD_ID')

// The Next.js CLI script (used directly — more reliable than the shell wrapper)
const NEXT_SCRIPT = path.join(FRONTEND_DIR, 'node_modules', 'next', 'dist', 'bin', 'next')

// Find Node.js to run Next.js. In a packaged .app, the shell PATH is not
// available, so we need an explicit path to a node binary.
function findNodeBin() {
  const candidates = [
    '/Users/zachary/.openclaw/tools/node/bin/node', // OpenClaw bundled — always present
    '/usr/local/bin/node',                           // Homebrew (Intel Mac)
    '/opt/homebrew/bin/node',                        // Homebrew (Apple Silicon)
    '/usr/bin/node',
  ]
  for (const c of candidates) {
    if (fs.existsSync(c)) return c
  }
  // Last resort: use Electron's own Node.js runtime
  return process.execPath
}

// ─── Utilities ───────────────────────────────────────────────────────────────

function isTcpPortInUse(port) {
  return new Promise((resolve) => {
    const sock = new net.Socket()
    sock.setTimeout(800)
    sock.on('connect', () => { sock.destroy(); resolve(true) })
    sock.on('error', () => { sock.destroy(); resolve(false) })
    sock.on('timeout', () => { sock.destroy(); resolve(false) })
    sock.connect(port, '127.0.0.1')
  })
}

function waitForHttp(url, timeout = 60000) {
  return new Promise((resolve, reject) => {
    const start = Date.now()
    const check = () => {
      const req = http.get(url, () => { resolve() })
      req.on('error', () => {
        if (Date.now() - start > timeout) {
          reject(new Error(`${url} did not respond within ${timeout / 1000}s`))
          return
        }
        setTimeout(check, 500)
      })
      req.setTimeout(1000, () => { req.destroy(); setTimeout(check, 500) })
    }
    check()
  })
}

// Like waitForHttp but requires an HTTP 200 status (used for /healthz probes)
function waitForHttpOk(url, timeout = 60000) {
  return new Promise((resolve, reject) => {
    const start = Date.now()
    const check = () => {
      const req = http.get(url, (res) => {
        res.resume() // drain body
        if (res.statusCode === 200) { resolve(); return }
        if (Date.now() - start > timeout) {
          reject(new Error(`${url} returned ${res.statusCode} after ${timeout / 1000}s`))
          return
        }
        setTimeout(check, 500)
      })
      req.on('error', () => {
        if (Date.now() - start > timeout) {
          reject(new Error(`${url} did not respond within ${timeout / 1000}s`))
          return
        }
        setTimeout(check, 500)
      })
      req.setTimeout(1500, () => { req.destroy(); setTimeout(check, 500) })
    }
    check()
  })
}

function waitForTcp(port, timeout = 30000) {
  return new Promise((resolve, reject) => {
    const start = Date.now()
    const check = async () => {
      const open = await isTcpPortInUse(port)
      if (open) { resolve(); return }
      if (Date.now() - start > timeout) {
        reject(new Error(`Port ${port} did not open within ${timeout / 1000}s`))
        return
      }
      setTimeout(check, 500)
    }
    check()
  })
}

// ─── Build check ─────────────────────────────────────────────────────────────

// Returns true if a production build exists and is ready for `next start`
function productionBuildExists() {
  return fs.existsSync(BUILD_ID_FILE)
}

// Run `next build` and wait for it to finish (used on first launch if no build)
function runNextBuild() {
  return new Promise((resolve, reject) => {
    console.log('[electron] No production build found — running next build...')
    console.log('[electron] This takes ~30s and only happens once.')

    const proc = spawn(findNodeBin(), [NEXT_SCRIPT, 'build'], {
      cwd: FRONTEND_DIR,
      env: { ...process.env, NEXT_TELEMETRY_DISABLED: '1' },
      stdio: 'pipe',
    })

    proc.stdout.on('data', (d) => process.stdout.write(`[build] ${d}`))
    proc.stderr.on('data', (d) => process.stderr.write(`[build] ${d}`))
    proc.on('exit', (code) => {
      if (code === 0) resolve()
      else reject(new Error(`next build exited with code ${code}`))
    })
  })
}

// ─── Python backend (uvicorn) ────────────────────────────────────────────────

function startBackend() {
  const logStream = fs.createWriteStream(BACKEND_LOG, { flags: 'a' })
  logStream.write(`\n--- Mission Control started backend at ${new Date().toISOString()} ---\n`)

  console.log('[electron] Starting Python backend (uvicorn)...')

  backendProcess = spawn(
    BACKEND_BIN,
    ['app.main:app', '--host', '127.0.0.1', '--port', String(BACKEND_PORT), '--no-access-log'],
    {
      cwd: BACKEND_DIR,
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
      stdio: ['ignore', 'pipe', 'pipe'],
      detached: false,
    }
  )

  backendProcess.stdout.on('data', (d) => {
    const line = d.toString()
    process.stdout.write(`[backend] ${line}`)
    logStream.write(line)
  })
  backendProcess.stderr.on('data', (d) => {
    const line = d.toString()
    process.stderr.write(`[backend] ${line}`)
    logStream.write(line)
  })
  backendProcess.on('exit', (code) => {
    console.log(`[electron] Backend exited with code ${code}`)
    backendProcess = null
  })
}

// ─── OpenClaw ────────────────────────────────────────────────────────────────

function startOpenClaw() {
  const logStream = fs.createWriteStream(OPENCLAW_LOG, { flags: 'a' })
  logStream.write(`\n--- Mission Control started OpenClaw at ${new Date().toISOString()} ---\n`)

  console.log('[electron] Starting OpenClaw gateway...')

  openclawProcess = spawn(OPENCLAW_BIN, ['gateway'], {
    cwd: process.env.HOME || '/Users/zachary',
    env: { ...process.env },
    stdio: ['ignore', 'pipe', 'pipe'],
    detached: false,
  })

  openclawProcess.stdout.on('data', (d) => {
    const line = d.toString()
    process.stdout.write(`[openclaw] ${line}`)
    logStream.write(line)
  })
  openclawProcess.stderr.on('data', (d) => {
    const line = d.toString()
    process.stderr.write(`[openclaw] ${line}`)
    logStream.write(line)
  })
  openclawProcess.on('exit', (code) => {
    console.log(`[electron] OpenClaw exited with code ${code}`)
    openclawProcess = null
  })
}

// ─── Next.js (production server) ─────────────────────────────────────────────

function startNext() {
  const nodeBin = findNodeBin()
  console.log('[electron] Starting Next.js production server...')
  console.log('[electron] Using node:', nodeBin)

  nextProcess = spawn(nodeBin, [NEXT_SCRIPT, 'start', '--port', String(NEXT_PORT)], {
    cwd: FRONTEND_DIR,
    env: { ...process.env, NEXT_TELEMETRY_DISABLED: '1' },
    stdio: 'pipe',
  })

  nextProcess.stdout.on('data', (d) => process.stdout.write(`[next] ${d}`))
  nextProcess.stderr.on('data', (d) => process.stderr.write(`[next] ${d}`))
  nextProcess.on('exit', (code) => {
    console.log(`[electron] Next.js exited with code ${code}`)
  })
}

// ─── Window ───────────────────────────────────────────────────────────────────

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 960,
    minHeight: 600,
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 16, y: 16 },
    backgroundColor: '#000000',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
    title: 'Mission Control',
    show: false,
  })

  mainWindow.loadURL(NEXT_URL)
  mainWindow.once('ready-to-show', () => { mainWindow.show() })

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  mainWindow.on('closed', () => { mainWindow = null })
}

// ─── App lifecycle ────────────────────────────────────────────────────────────

app.whenReady().then(async () => {
  // 1. Start OpenClaw if not already running
  const openclawRunning = await isTcpPortInUse(OPENCLAW_PORT)
  if (openclawRunning) {
    console.log('[electron] OpenClaw already running on port', OPENCLAW_PORT)
  } else {
    startOpenClaw()
    try {
      await waitForTcp(OPENCLAW_PORT)
      console.log('[electron] OpenClaw ready on port', OPENCLAW_PORT)
    } catch (err) {
      console.error('[electron] OpenClaw did not start in time:', err.message)
      // Non-fatal — Chat page will show "Connection error"
    }
  }

  // 2. Start Python backend if not already running
  const backendRunning = await isTcpPortInUse(BACKEND_PORT)
  if (backendRunning) {
    console.log('[electron] Backend already running on port', BACKEND_PORT)
  } else {
    startBackend()
    try {
      await waitForHttpOk(BACKEND_HEALTHZ, 60000)
      console.log('[electron] Backend ready at', BACKEND_HEALTHZ)
    } catch (err) {
      console.error('[electron] Backend did not start in time:', err.message)
      // Non-fatal — auth will show an error but app still opens
    }
  }

  // 3. Ensure a production build exists (runs once ever, ~30s)
  if (!productionBuildExists()) {
    try {
      await runNextBuild()
      console.log('[electron] Build complete')
    } catch (err) {
      console.error('[electron] Build failed:', err.message)
      app.quit()
      return
    }
  }

  // 4. Start Next.js production server if not already running
  const nextRunning = await isTcpPortInUse(NEXT_PORT)
  if (nextRunning) {
    console.log('[electron] Next.js already running on port', NEXT_PORT)
  } else {
    startNext()
    try {
      await waitForHttp(NEXT_URL)
      console.log('[electron] Next.js ready')
    } catch (err) {
      console.error('[electron] Next.js failed to start:', err.message)
      app.quit()
      return
    }
  }

  // 5. Open the window
  createWindow()
})

// ─── Cleanup ─────────────────────────────────────────────────────────────────

function shutdown() {
  if (nextProcess && !nextProcess.killed) {
    nextProcess.kill('SIGTERM')
    nextProcess = null
  }
  if (backendProcess && !backendProcess.killed) {
    backendProcess.kill('SIGTERM')
    backendProcess = null
  }
  // OpenClaw kept alive intentionally — serves Telegram + Discord independently
}

app.on('before-quit', shutdown)
app.on('will-quit', shutdown)
app.on('activate', () => { if (mainWindow === null) createWindow() })
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') { shutdown(); app.quit() }
})
