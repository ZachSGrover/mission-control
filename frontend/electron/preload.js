'use strict'

// Electron preload script runs as Node CommonJS — require() is required here.
/* eslint-disable @typescript-eslint/no-require-imports */

// Preload script — runs in the renderer process (the web page)
// with access to both the DOM and a limited set of Node.js APIs.
//
// This is the secure bridge between the Electron shell and the web app.
// Right now it does nothing — this file exists as the correct place to
// add system integrations later (e.g. reading OpenClaw logs, system tray).
//
// Rules:
//   - Never expose require() or Node APIs directly to the page
//   - Use contextBridge.exposeInMainWorld() for anything the app needs

const { contextBridge } = require('electron')

contextBridge.exposeInMainWorld('electron', {
  // Expose app version so the UI can show it if needed
  platform: process.platform,
})
