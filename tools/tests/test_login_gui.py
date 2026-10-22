"""Display-free tests for tools/login-gui.py: theme contrast (WCAG AA 4.5:1),
CLI flags, importability without a display, and English-only interface text."""
import importlib.util
import os
import re
import unittest

GUI = os.path.join(os.path.dirname(__file__), '..', 'login-gui.py')


def load_gui():
    spec = importlib.util.spec_from_file_location('login_gui', GUI)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def luminance(hex_color):
    """Relative luminance of a #rrggbb color (WCAG definition)."""
    rgb = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
           for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(fg, bg):
    lighter, darker = sorted([luminance(fg), luminance(bg)], reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


class LoginGuiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gui = load_gui()

    def test_text_pairs_meet_aa_contrast(self):
        t = self.gui.THEME
        pairs = [(t['foreground'], t['background']),
                 (t['muted'], t['background']),
                 (t['foreground'], t['card']),
                 (t['on_accent'], t['accent']),
                 (t['destructive'], t['background'])]
        for fg, bg in pairs:
            self.assertGreaterEqual(
                ratio(fg, bg), 4.5, f'{fg} on {bg}')

    def test_parse_args_flags(self):
        args = self.gui.parse_args(['--api-base', 'http://x',
                                    '--game-port', '8018'])
        self.assertEqual(args.api_base, 'http://x')
        self.assertEqual(args.game_port, '8018')
        self.assertIsNone(args.movie_base)

    def test_interface_text_is_english_only(self):
        with open(GUI, encoding='utf-8') as f:
            source = f.read()
        self.assertIsNone(re.search(r'[\u4e00-\u9fff]', source))


if __name__ == '__main__':
    unittest.main()
