"""Login window: sign in with username and password, then start the Flash projector.

Usage: login-gui.py [--api-base URL] [--movie-base URL] [--game-port PORT]
The password is sent only to the login endpoint; it is never stored or logged.
"""
import argparse
import importlib.util
import os
import threading
import tkinter as tk
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "projector_client", os.path.join(ROOT, "tools", "projector-client.py"))
pc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pc)


def parse_args(argv):
    ap = argparse.ArgumentParser(description="Sign in and launch the Flash projector.")
    ap.add_argument("--api-base")
    ap.add_argument("--movie-base")
    ap.add_argument("--game-port")
    return ap.parse_args(argv)


class LoginWindow:
    def __init__(self, root, args):
        self.root = root
        self.args = args
        root.title("MonkeyKingOnline Login")
        root.resizable(False, False)
        frame = tk.Frame(root, padx=16, pady=16)
        frame.pack()
        tk.Label(frame, text="Username").grid(row=0, column=0, sticky="w")
        self.user = tk.Entry(frame, width=28)
        self.user.grid(row=0, column=1, pady=4)
        tk.Label(frame, text="Password").grid(row=1, column=0, sticky="w")
        self.password = tk.Entry(frame, width=28, show="*")
        self.password.grid(row=1, column=1, pady=4)
        self.button = tk.Button(frame, text="Login", width=12, command=self.on_login)
        self.button.grid(row=2, column=1, sticky="e", pady=(8, 0))
        self.status = tk.Label(frame, text="", fg="#a00", wraplength=300, justify="left")
        self.status.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.user.focus_set()
        root.bind("<Return>", lambda _e: self.on_login())

    def on_login(self):
        user = self.user.get().strip()
        password = self.password.get()
        if not user or not password:
            self.status.config(text="Enter a username and password.")
            return
        self.button.config(state="disabled")
        self.status.config(text="Signing in...", fg="#333")
        threading.Thread(target=self.sign_in, args=(user, password), daemon=True).start()

    def sign_in(self, user, password):
        try:
            url = pc.build_movie_url(user, password, self.args.api_base,
                                     self.args.movie_base, argv=self._game_port_argv())
        except SystemExit as exc:
            self.root.after(0, self.fail, str(exc))
            return
        except (urllib.error.URLError, OSError) as exc:
            self.root.after(0, self.fail, f"Cannot reach the server: {exc.reason if hasattr(exc, 'reason') else exc}")
            return
        self.root.after(0, self.launched, url)

    def _game_port_argv(self):
        return ["login-gui"] + (["--game-port", self.args.game_port] if self.args.game_port else [])

    def fail(self, message):
        self.status.config(text=message or "Login failed.", fg="#a00")
        self.password.delete(0, tk.END)
        self.button.config(state="normal")
        self.password.focus_set()

    def launched(self, url):
        pc.launch_projector(url)
        self.status.config(text="Client started.", fg="#060")
        self.button.config(state="normal")


def main(argv=None):
    args = parse_args(argv)
    root = tk.Tk()
    LoginWindow(root, args)
    root.mainloop()


if __name__ == "__main__":
    main()
