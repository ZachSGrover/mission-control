/**
 * Module-level cache for provider status (openai/gemini configured check).
 * Lives outside React so it survives tab switches without re-fetching.
 * TTL: 5 minutes — safe for "is API key configured?" which rarely changes.
 */

const CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes

interface CacheEntry {
  configured: boolean;
  fetchedAt: number;
}

const _cache: Record<string, CacheEntry> = {};

export function getCachedStatus(provider: string): boolean | null {
  const entry = _cache[provider];
  if (!entry) return null;
  if (Date.now() - entry.fetchedAt > CACHE_TTL_MS) {
    delete _cache[provider];
    return null;
  }
  return entry.configured;
}

export function setCachedStatus(provider: string, configured: boolean): void {
  _cache[provider] = { configured, fetchedAt: Date.now() };
}

export function invalidateStatus(provider: string): void {
  delete _cache[provider];
}
