"""Login window: sign in with username and password, then start the Flash projector.

Usage: login-gui.py [--api-base URL] [--movie-base URL] [--game-port PORT]
The password is sent only to the login endpoint; it is never stored or logged.
All interface text is English. Theme tokens come from the MKO Login design
system (skills/ui-ux-pro-max, gaming palette); see agents.json.
"""
import argparse
import importlib.util
import os
import threading
import tkinter as tk
from tkinter import ttk
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "projector_client", os.path.join(ROOT, "tools", "projector-client.py"))
pc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pc)

# MKO Login design system (dark gaming): text/background pairs must keep a
# contrast ratio of 4.5:1 or better (see tools/tests/test_login_gui.py).
THEME = {
    'background': '#0F0F23',
    'card': '#1E1C35',
    'foreground': '#E2E8F0',
    'muted': '#94A3B8',
    'accent': '#F43F5E',
    'on_accent': '#000000',
    'primary': '#7C3AED',
    'destructive': '#EF4444',
    'border': '#4C1D95',
}


def parse_args(argv):
    ap = argparse.ArgumentParser(description="Sign in and launch the Flash projector.")
    ap.add_argument("--api-base")
    ap.add_argument("--movie-base")
    ap.add_argument("--game-port")
    return ap.parse_args(argv)


def apply_theme(root):
    """Clam-based dark theme; visible focus rings on entries and buttons."""
    style = ttk.Style(root)
    style.theme_use('clam')
    t = THEME
    root.configure(bg=t['background'])
    style.configure('Card.TFrame', background=t['card'])
    style.configure('Title.TLabel', background=t['card'],
                    foreground=t['foreground'],
                    font=('Segoe UI', 14, 'bold'))
    style.configure('Subtitle.TLabel', background=t['card'],
                    foreground=t['muted'], font=('Segoe UI', 9))
    style.configure('TLabel', background=t['card'], foreground=t['muted'],
                    font=('Segoe UI', 9))
    style.configure('TEntry', fieldbackground=t['background'],
                    foreground=t['foreground'], insertcolor=t['foreground'],
                    bordercolor=t['border'], lightcolor=t['primary'],
                    darkcolor=t['background'], padding=6)
    style.map('TEntry', bordercolor=[('focus', t['primary'])])
    style.configure('Accent.TButton', background=t['accent'],
                    foreground=t['on_accent'], bordercolor=t['accent'],
                    lightcolor=t['accent'], darkcolor=t['accent'],
                    font=('Segoe UI', 10, 'bold'), padding=(10, 8))
    style.map('Accent.TButton',
              background=[('active', t['accent']), ('disabled', t['border'])],
              foreground=[('disabled', t['muted'])],
              bordercolor=[('focus', t['primary'])])
    return style


class LoginWindow:
    def __init__(self, root, args):
        self.root = root
        self.args = args
        root.title("MonkeyKingOnline Login")
        root.resizable(False, False)
        apply_theme(root)
        frame = ttk.Frame(root, style='Card.TFrame', padding=20)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text="MonkeyKingOnline",
                  style='Title.TLabel').grid(row=0, column=0, columnspan=2,
                                             sticky='w')
        ttk.Label(frame, text="Sign in to launch the desktop client",
                  style='Subtitle.TLabel').grid(row=1, column=0, columnspan=2,
                                                sticky='w', pady=(0, 12))
        ttk.Label(frame, text="Username").grid(row=2, column=0, columnspan=2,
                                               sticky='w')
        self.user = ttk.Entry(frame, width=30)
        self.user.grid(row=3, column=0, columnspan=2, sticky='ew', pady=(2, 8))
        ttk.Label(frame, text="Password").grid(row=4, column=0, columnspan=2,
                                               sticky='w')
        self.password = ttk.Entry(frame, width=30, show="*")
        self.password.grid(row=5, column=0, columnspan=2, sticky='ew',
                           pady=(2, 12))
        self.button = ttk.Button(frame, text="Login", style='Accent.TButton',
                                 command=self.on_login)
        self.button.grid(row=6, column=0, columnspan=2, sticky='ew')
        self.status = tk.Label(frame, text="", bg=THEME['card'],
                               fg=THEME['muted'], wraplength=280,
                               justify='left', font=('Segoe UI', 9))
        self.status.grid(row=7, column=0, columnspan=2, sticky='w',
                         pady=(10, 0))
        frame.columnconfigure(0, weight=1)
        self.user.focus_set()
        root.bind("<Return>", lambda _e: self.on_login())

    def on_login(self):
        user = self.user.get().strip()
        password = self.password.get()
        if not user or not password:
            self.status.config(text="Error: enter a username and password.",
                               fg=THEME['destructive'])
            return
        self.button.config(state='disabled', text="Signing in…")
        self.status.config(text="Signing in…", fg=THEME['muted'])
        self.root.config(cursor='watch')
        threading.Thread(target=self.sign_in, args=(user, password),
                         daemon=True).start()

    def sign_in(self, user, password):
        try:
            url = pc.build_movie_url(user, password, self.args.api_base,
                                     self.args.movie_base, argv=self._game_port_argv())
        except SystemExit as exc:
            self.root.after(0, self.fail, str(exc))
            return
        except (urllib.error.URLError, OSError) as exc:
            reason = getattr(exc, 'reason', exc)
            self.root.after(0, self.fail, f"Cannot reach the server: {reason}")
            return
        self.root.after(0, self.launched, url)

    def _game_port_argv(self):
        return ["login-gui"] + (["--game-port", self.args.game_port] if self.args.game_port else [])

    def fail(self, message):
        self.status.config(text=f"Error: {message or 'Login failed.'}",
                           fg=THEME['destructive'])
        self.password.delete(0, tk.END)
        self._idle()

    def launched(self, url):
        pc.launch_projector(url)
        self.status.config(text="Client started.", fg=THEME['foreground'])
        self._idle()

    def _idle(self):
        self.button.config(state='normal', text="Login")
        self.root.config(cursor='')
        self.password.focus_set()


def main(argv=None):
    args = parse_args(argv)
    root = tk.Tk()
    LoginWindow(root, args)
    root.mainloop()


if __name__ == "__main__":
    main()
