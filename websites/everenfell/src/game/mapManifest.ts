/** Map 0 manifest: verified 408-tile layout (17x24, 256px cells, 4352x6144).
 *
 * Tiles come from src/assets/map0.json, generated from the local original
 * client. Positions are source-grounded; nothing is invented. Tile bytes
 * are served dev-only by the Vite plugin and never ship in dist/.
 */
import mapManifest from '../assets/map0.json';

export interface MapTile {
  id: string;
  row: number;
  col: number;
  x: number;
  y: number;
  width: number;
  height: number;
  url: string;
  sha256: string;
}

export const MAP_W = mapManifest.mapwidth as number;
export const MAP_H = mapManifest.mapheight as number;
export const MAP_NAME = mapManifest.name as string;
export const MAP_TILES = mapManifest.tiles as MapTile[];

export function tileKey(tile: MapTile): string {
  return `map0-${tile.id}`;
}

export function mapTileUrl(tile: MapTile): string {
  return `${import.meta.env.DEV ? '/assets/' : '/protected-assets/'}${tile.url}`;
}
