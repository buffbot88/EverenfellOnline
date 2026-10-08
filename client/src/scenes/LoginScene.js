import Phaser from 'phaser';
import {
  loginAccount,
  registerAccount,
  fetchGameSession,
  captchaUrl,
} from '../api.js';

// Login / register via DOM overlay (real inputs), then fetch the game-socket
// token and show the server panel. Entering the actual game world is the next
// milestone (see ../net/GameSocket.js).
export default class LoginScene extends Phaser.Scene {
  constructor() {
    super('login');
    this.mode = 'login'; // 'login' | 'register'
  }

  create() {
    this.add
      .text(480, 560, 'HTML5 client · milestone 1: account login', {
        fontSize: '13px',
        color: '#5a6390',
      })
      .setOrigin(0.5);
    this.renderOverlay();
  }

  overlayRoot() {
    return document.getElementById('game');
  }

  clearOverlay() {
    this.overlayRoot()
      .querySelectorAll('.auth-overlay')
      .forEach((el) => el.remove());
  }

  renderOverlay() {
    this.clearOverlay();
    const root = this.overlayRoot();
    const wrap = document.createElement('div');
    wrap.className = 'auth-overlay';
    wrap.innerHTML =
      this.mode === 'login' ? this.loginHtml() : this.registerHtml();
    root.appendChild(wrap);

    const err = wrap.querySelector('.auth-error');
    const say = (msg) => {
      if (err) err.textContent = msg;
    };

    if (this.mode === 'login') {
      const btn = wrap.querySelector('#auth-go');
      const user = wrap.querySelector('#auth-user');
      const pass = wrap.querySelector('#auth-pass');
      wrap.querySelector('#auth-swap').onclick = () => {
        this.mode = 'register';
        this.renderOverlay();
      };
      btn.onclick = async () => {
        btn.disabled = true;
        say('');
        try {
          const res = await loginAccount(user.value.trim(), pass.value);
          if (!res.ok) {
            say(res.message);
            return;
          }
          await this.onLoggedIn();
        } catch (e) {
          say(`无法连接后端：${e.message}`);
        } finally {
          btn.disabled = false;
        }
      };
    } else {
      const btn = wrap.querySelector('#auth-go');
      const img = wrap.querySelector('#auth-captcha');
      img.onclick = () => {
        img.src = captchaUrl();
      };
      wrap.querySelector('#auth-swap').onclick = () => {
        this.mode = 'login';
        this.renderOverlay();
      };
      btn.onclick = async () => {
        btn.disabled = true;
        say('');
        try {
          const res = await registerAccount(
            wrap.querySelector('#auth-user').value.trim(),
            wrap.querySelector('#auth-pass').value,
            wrap.querySelector('#auth-code').value.trim(),
          );
          const ok = wrap.querySelector('.auth-ok');
          if (!res.ok) {
            say(res.message);
            img.src = captchaUrl();
            return;
          }
          if (ok) ok.textContent = res.message;
          await this.onLoggedIn();
        } catch (e) {
          say(`无法连接后端：${e.message}`);
        } finally {
          btn.disabled = false;
        }
      };
    }
  }

  loginHtml() {
    return `<div class="auth-card">
      <h1>登 录</h1>
      <p class="sub">使用游戏账号登录（账号仅限英文与数字）</p>
      <label for="auth-user">账号</label>
      <input id="auth-user" type="text" autocomplete="username" />
      <label for="auth-pass">密码</label>
      <input id="auth-pass" type="password" autocomplete="current-password" />
      <button id="auth-go">登 录</button>
      <button id="auth-swap" class="secondary">没有账号？去注册</button>
      <div class="auth-error"></div>
    </div>`;
  }

  registerHtml() {
    return `<div class="auth-card">
      <h1>注 册</h1>
      <p class="sub">新账号将写入 caonima.account（与旧版官网互通）</p>
      <label for="auth-user">账号（英文/数字）</label>
      <input id="auth-user" type="text" autocomplete="username" />
      <label for="auth-pass">密码</label>
      <input id="auth-pass" type="password" autocomplete="new-password" />
      <label for="auth-code">验证码（点击图片刷新）</label>
      <div class="auth-row">
        <input id="auth-code" type="text" style="flex:1" />
        <img id="auth-captcha" src="${captchaUrl()}" alt="captcha" />
      </div>
      <button id="auth-go">注 册 并 登 录</button>
      <button id="auth-swap" class="secondary">已有账号？去登录</button>
      <div class="auth-error"></div>
      <div class="auth-ok"></div>
    </div>`;
  }

  async onLoggedIn() {
    const session = await fetchGameSession();
    this.clearOverlay();
    const root = this.overlayRoot();
    const wrap = document.createElement('div');
    wrap.className = 'auth-overlay';
    wrap.innerHTML = `<div class="auth-card session-card">
      <h1>欢迎，${escapeHtml(session.uid)}</h1>
      <p class="sub">登录成功 · 游戏会话已就绪</p>
      <code>${escapeHtml(
        `server  ${session.seid} (${session.ip}:${session.sport})\nuid     ${session.uid}\nt       ${session.t}\nsign    ${session.sign}`,
      )}</code>
      <button id="auth-enter">
        进 入 游 戏
      </button>
      <div class="auth-ok">正在进入游戏……（<span id="auth-count">2</span> 秒后自动跳转）</div>
    </div>`;
    root.appendChild(wrap);
    this.session = session;
    const go = () => {
      window.location.href = '/player.html';
    };
    wrap.querySelector('#auth-enter').onclick = go;
    // Auto-enter the Flash client; the mko_session cookie carries the login.
    let left = 2;
    const tick = () => {
      left -= 1;
      if (left <= 0) {
        go();
        return;
      }
      const el = wrap.querySelector('#auth-count');
      if (el) el.textContent = String(left);
      setTimeout(tick, 1000);
    };
    setTimeout(tick, 1000);
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[c]);
}
