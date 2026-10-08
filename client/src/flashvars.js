// Fetch the game's flashvars from the PHP backend (gamesession.php).
// Falls back to a demo session so the loader/login UI can boot while the
// Apache+MySQL stack is offline. Mirrors Gamelogin.php exactly.
import { fetchGameSession } from "./api.js";

export async function getFlashVars() {
  try {
    const s = await fetchGameSession();
    return toFlashVars(s);
  } catch {
    // Demo fallback: lets Ruffle boot Main.swf without a backend.
    // The socket login will fail (no game server), but loader art,
    // asset decryption and the login screen all run for real.
    return toFlashVars({
      uid: "demo",
      t: String(Math.floor(Date.now() / 1000)),
      sign: "00000000000000000000000000000000",
      seid: "fu1304",
      sport: 8008,
      ip: "127.0.0.1",
      pid: "gmthai",
    });
  }
}

function toFlashVars(s) {
  const lcid =
    Date.now().valueOf().toString(16) + ((Math.random() * 1000) >> 0).toString(16);
  return {
    lcid,
    // URL-valued fields are escape()d exactly as Gamelogin.php does.
    pay: escape("http://127.0.0.1/"),
    cm: escape("http://127.0.0.1/"),
    uid: s.uid,
    pid: s.pid,
    t: String(s.t),
    seid: s.seid,
    sport: String(s.sport),
    ip: s.ip,
    who: "",
    sign: s.sign,
    cminfo: "null",
    bbsurl: escape("http://127.0.0.1/"),
    homeurl: escape("http://127.0.0.1/"),
    infourl: escape("http://127.0.0.1/"),
    shownav: escape("0"),
    bugurl: escape("http://127.0.0.1/"),
    suggesturl: escape("http://127.0.0.1/"),
    saveUrl: escape("http://127.0.0.1/"),
    pl: "null",
    client: "null",
    microClientURL: escape("http://127.0.0.1/"),
    gmpanel: "0",
    server: "null",
    gameid: "null",
  };
}
