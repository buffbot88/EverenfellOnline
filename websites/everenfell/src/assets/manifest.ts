/** Versioned asset manifest (mirrors the legacy resource manifests).

Legacy orientation: res/data/{locale}_config.xml maps resource names to
files under assets/{locale}/ with a {0} version slot, and hash.dat
carries per-file hashes. The browser manifest keeps the same idea in
JSON: entries carry a version and sha256 so the loader can cache by
content and revalidate on version bumps.

Rights: only independently original or rights-cleared files may ship
under websites/everenfell/public/assets. See
Server-v1/docs/everenfell-asset-ledger.md.
*/

export interface AssetEntry {
  /** Stable resource id (e.g. "bagUI", "map/2/tiles"). */
  id: string;
  /** Content-addressed URL served with immutable caching. */
  url: string;
  /** Manifest version slot (cache-buster, like the legacy {0}). */
  version: string;
  /** sha256 of the file bytes; empty when unverified. */
  sha256: string;
  kind: 'image' | 'audio' | 'data' | 'atlas';
}

export interface AssetManifest {
  version: string;
  entries: AssetEntry[];
}

export async function fetchManifest(url: string): Promise<AssetManifest> {
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) {
    throw new Error(`manifest fetch failed (http ${res.status})`);
  }
  const doc = (await res.json()) as AssetManifest;
  if (!Array.isArray(doc.entries)) {
    throw new Error('manifest has no entries array');
  }
  return doc;
}

/** Placeholder art keeps the renderer testable before recovered or
 *  replacement assets land. Each kind gets a distinct tint so missing
 *  art is obvious instead of silently wrong.
 */
export function placeholderColor(kind: AssetEntry['kind']): number {
  switch (kind) {
    case 'image':
      return 0x2e8b8b;
    case 'audio':
      return 0x8b5e2e;
    case 'atlas':
      return 0x5e2e8b;
    case 'data':
    default:
      return 0x4a5a6a;
  }
}
