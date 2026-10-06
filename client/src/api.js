// Thin client for the legacy PHP backend, reached through the Vite dev
// proxy (`/api/*` -> Apache on :80). Same-origin from the browser's view,
// so the PHP session cookie is sent automatically.
//
// Backend contract (see TonNgoKhong/server/ESSamp/wwwroot/):
// - POST AjaxRequest/AccountHandler.php {Action:'Login', uName, uPas}
//   -> 200 + text containing '登陆成功' on success (session cookie set),
//      text '用户名或者密码错误…' on failure.
// - POST AjaxRequest/AccountHandler.php {Action:'Register', uName, uPas, sCode}
//   -> text containing '注册成功' on success. sCode is the captcha from
//      configuration/VerifyCode.php (lowercased, stored in $_SESSION).
// - GET gamesession.php -> JSON game-socket token (requires login session).

const BASE = '/api';

async function postForm(path, fields) {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams(fields),
  });
  return { status: res.status, text: await res.text() };
}

export function captchaUrl() {
  return `${BASE}/configuration/VerifyCode.php?r=${Date.now()}`;
}

export async function loginAccount(uName, uPas) {
  const { text } = await postForm('/AjaxRequest/AccountHandler.php', {
    Action: 'Login',
    uName,
    uPas,
  });
  if (text.includes('登陆成功')) return { ok: true, message: text.trim() };
  return { ok: false, message: stripTags(text) || '登录失败，请重试' };
}

export async function registerAccount(uName, uPas, sCode) {
  const { text } = await postForm('/AjaxRequest/AccountHandler.php', {
    Action: 'Register',
    uName,
    uPas,
    sCode,
  });
  if (text.includes('注册成功')) return { ok: true, message: text.trim() };
  return { ok: false, message: stripTags(text) || '注册失败，请重试' };
}

// Game-socket login token (uid/t/sign/seid/sport/ip/pid), same values the
// Flash client received as flashvars from Gamelogin.php.
export async function fetchGameSession() {
  const res = await fetch(`${BASE}/gamesession.php`);
  if (res.status === 401) throw new Error('登录会话已失效，请重新登录');
  const body = await res.text();
  let data;
  try {
    data = JSON.parse(body);
  } catch {
    throw new Error('后端返回异常（确认 Apache + MySQL 已启动）');
  }
  if (!data.ok) throw new Error(data.error || '获取游戏会话失败');
  return data;
}

function stripTags(html) {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/<[^>]*>/g, '')
    .trim();
}
