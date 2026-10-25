/** Local asset cache over the Cache Storage API.

Entries are keyed by versioned URL, so a manifest bump naturally
revalidates. Falls back to network when Cache Storage is unavailable
(private mode, non-secure contexts); failures are reported, never
hidden, so missing art stays visible as a defect.
*/
import type { AssetEntry } from './manifest';

const CACHE_NAME = 'everenfell-assets-v1';

export class AssetCache {
  private memory = new Map<string, Response>();

  async load(entry: AssetEntry): Promise<Response> {
    const cached = this.memory.get(entry.url);
    if (cached) return cached.clone();
    if ('caches' in window) {
      try {
        const store = await window.caches.open(CACHE_NAME);
        const hit = await store.match(entry.url);
        if (hit) {
          this.memory.set(entry.url, hit.clone());
          return hit;
        }
        const res = await fetch(entry.url);
        if (!res.ok) {
          throw new Error(`asset ${entry.id} http ${res.status}`);
        }
        await store.put(entry.url, res.clone());
        this.memory.set(entry.url, res.clone());
        return res;
      } catch (err) {
        if (err instanceof Error && err.message.startsWith(`asset ${entry.id}`)) {
          throw err;
        }
        // Cache Storage unavailable: fall through to network.
      }
    }
    const res = await fetch(entry.url);
    if (!res.ok) {
      throw new Error(`asset ${entry.id} http ${res.status}`);
    }
    return res;
  }

  clearMemory(): void {
    this.memory.clear();
  }
}
