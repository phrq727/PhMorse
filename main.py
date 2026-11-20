#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Morse Keyboard — ввод текста азбукой Морзе (ENG / RUS / 123 / !@#).

  Установка:  pip install PySide6
  Запуск:     python morse_keyboard.py
  Иконки:     assets/icon.png и assets/icon.ico рядом с этим файлом
"""
import sys, os, json, time, math, wave, tempfile, random
from pathlib import Path

# ============================ ДАННЫЕ ============================
EN = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.", "G": "--.",
    "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..", "M": "--", "N": "-.",
    "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.", "S": "...", "T": "-", "U": "..-",
    "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--", "Z": "--..",
}
RU = {
    "А": ".-", "Б": "-...", "В": ".--", "Г": "--.", "Д": "-..", "Е": ".", "Ж": "...-",
    "З": "--..", "И": "..", "Й": ".---", "К": "-.-", "Л": ".-..", "М": "--", "Н": "-.",
    "О": "---", "П": ".--.", "Р": ".-.", "С": "...", "Т": "-", "У": "..-", "Ф": "..-.",
    "Х": "....", "Ц": "-.-.", "Ч": "---.", "Ш": "----", "Щ": "--.-", "Ы": "-.--",
    "Ь": "-..-", "Э": "..-..", "Ю": "..--", "Я": ".-.-",
}
# Цифры и знаки: распознаются при вводе (в дереве их нет)
EXTRA = {
    "1": ".----", "2": "..---", "3": "...--", "4": "....-", "5": ".....",
    "6": "-....", "7": "--...", "8": "---..", "9": "----.", "0": "-----",
    ".": ".-.-.-", ",": "--..--", "?": "..--..", "!": "-.-.--", "-": "-....-",
    "/": "-..-.", "(": "-.--.", ")": "-.--.-", ":": "---...", ";": "-.-.-.",
    "=": "-...-", "+": ".-.-.", '"': ".-..-.", "'": ".----.", "@": ".--.-.",
    "&": ".-...", "_": "..--.-",
}
NUM = {d: EXTRA[d] for d in "1234567890"}
SYM = {ch: EXTRA[ch] for ch in ".,?!-/():;=+\"'@&_"}
LANGS = {"EN": EN, "RU": RU, "NUM": NUM, "SYM": SYM}
# Совмещённые деревья: буквы + цифры + символы в одном дереве (переключается только язык букв)
LANGS["ALL_EN"] = {**EN, **NUM, **SYM}
LANGS["ALL_RU"] = {**RU, **NUM, **SYM}
EXTRA_CODES = set(NUM.values()) | set(SYM.values())


def eff_lang(st):
    """Какое дерево реально показываем: с учётом кнопки совмещения."""
    return "ALL_" + st["lang"] if st["combo"] and st["lang"] in ("EN", "RU") else st["lang"]


def tree_codes(name):
    """Какие узлы рисуем в дереве. Для цифр добавляем безымянные промежуточные узлы."""
    d = LANGS[name]
    if name in ("EN", "RU"):
        return set(d.values())
    out = set()
    for code in d.values():
        for i in range(1, len(code) + 1):
            out.add(code[:i])
    return out


def build_layout(codes):
    """Раскладка дерева на сетке в стиле брелока: точки уходят вправо, тире — влево,
    а вторая ветка спускается вниз. Возвращает {код: (колонка, ряд)}."""
    codes = set(codes)
    occ = {(0, 0): ""}

    def place(code, c, r, side, occ):
        if (c, r) in occ:
            return None
        cells = {(c, r): code}
        loc = dict(occ)
        loc[(c, r)] = code
        h, d = (".", "-") if side > 0 else ("-", ".")
        hc, dc = code + h, code + d
        if hc in codes:
            sub = place(hc, c + side, r, side, loc)
            if sub is None and dc not in codes:      # горизонталь занята -> уходим вниз
                sub = place_down(code, hc, c, r, side, loc)
            if sub is None:
                return None
            cells.update(sub)
            loc.update(sub)
        if dc in codes:
            sub = place_down(code, dc, c, r, side, loc)
            if sub is None:
                return None
            cells.update(sub)
        return cells

    def place_down(code, child, c, r, side, loc):
        for rr in range(r + 1, r + 24):
            edge = {(c, k): "#" for k in range(r + 1, rr)}
            if any(k in loc for k in edge):
                return None
            trial = dict(loc)
            trial.update(edge)
            sub = place(child, c, rr, side, trial)
            if sub is not None:
                out = dict(edge)
                out.update(sub)
                return out
        return None

    for side in (1, -1):
        h, d = (".", "-") if side > 0 else ("-", ".")
        chain, code, c = [], h, side
        while code in codes:
            occ[(c, 0)] = code
            chain.append((code, c))
            code, c = code + h, c + side
        for code, c in reversed(chain):          # от дальних к ближним
            if code + d in codes:
                res = place_down(code, code + d, c, 0, side, occ)
                if res is None:
                    raise RuntimeError("layout failed for " + code)
                occ.update(res)
    return {v: k for k, v in occ.items() if v != "#"}


def make_layout(name):
    pos = build_layout(tree_codes(name))
    if name == "SYM" or name.startswith("ALL_"):     # глубокие деревья — кладём набок
        pos = {code: (r, -cc) for code, (cc, r) in pos.items()}     # точки — вверх, тире — вниз
    return pos


# ============================ ИНТЕРФЕЙС (Qt) ============================
from PySide6.QtCore import (Qt, QTimer, QRectF, QPointF, QObject, Signal, QUrl,
                            QVariantAnimation, QEasingCurve, QEvent)
from PySide6.QtGui import (QPainter, QColor, QFont, QFontMetricsF, QPen, QBrush, QLinearGradient,
                           QRadialGradient, QPainterPath, QGuiApplication, QIcon, QImage)
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QDialog,
                               QLabel, QSlider, QScrollArea, QFrame)
try:
    from PySide6.QtMultimedia import QSoundEffect
    HAVE_SOUND = True
except Exception:
    HAVE_SOUND = False

# ---------- палитра / темы ----------
# Все цвета интерфейса живут здесь. apply_theme() кладёт выбранную палитру в глобальные
# имена (BG0, TXT, ACC ...), поэтому смена темы действует на весь код сразу.
THEMES = {
    "dark": dict(
        BG0="#0A0812", BG1="#130E24", WIN_TOP="#120D22",
        SURF="#15112A", SURF2="#1C1636",
        BORDER="#2B2447", BORDER_HI="#6A52C4",
        TXT="#EDE9FE", MID="#BDB4E0", DIM="#7C7499",
        ACC="#8B5CF6", ACC_D="#6D28D9", ACC_L="#A78BFA", ACC_XL="#C4B5FD",
        DASH="#E879F9", ERR="#FB7185", GREEN="#86EFAC",
        CARD_A="#1B1534", CARD_B="#130F26", LINE="#2A2347", HOLD="#5A5280",
        TREE_A="#191232", TREE_B="#0E0A1D",
        NODE="#1D1836", NODE_EDGE="#3A3160", EDGE="#2D2650", LET_EXTRA="#8FB4F5",
        KEY_A="#1D1738", KEY_DOWN="#221A42", KEY_B="#140F28",
        FAINT="#6B6390", HINT="#5F5886", BTN_ON="#FFFFFF", TOG_OFF="#2A2347",
        TRACK="#231D3D", TRACK_OFF="#1A1630", FILL_OFF="#3A3358",
        KNOB="#F5F3FF", KNOB_OFF="#5A5278", LBL_OFF="#4A4366",
        SB="#2F2756", SB_HI="#4A3C85", GLOW1=70, GLOW2=42,
    ),
    "light": dict(
        BG0="#EBE6F8", BG1="#F6F3FD", WIN_TOP="#F6F3FD",
        SURF="#FFFFFF", SURF2="#F1ECFB",
        BORDER="#D8CFF0", BORDER_HI="#8B6FE0",
        TXT="#211A3D", MID="#4E4573", DIM="#8077A3",
        ACC="#8B5CF6", ACC_D="#6D28D9", ACC_L="#7C4DEB", ACC_XL="#6D28D9",
        DASH="#C026D3", ERR="#E11D48", GREEN="#16A34A",
        CARD_A="#FFFFFF", CARD_B="#F7F3FF", LINE="#E3DCF5", HOLD="#A89FC8",
        TREE_A="#FFFFFF", TREE_B="#EFEAFB",
        NODE="#ECE6FA", NODE_EDGE="#BDB0E4", EDGE="#CDC3EC", LET_EXTRA="#3568D4",
        KEY_A="#FFFFFF", KEY_DOWN="#F0E9FF", KEY_B="#F1ECFB",
        FAINT="#A59CC4", HINT="#8A81AB", BTN_ON="#4C1D95", TOG_OFF="#D5CCEC",
        TRACK="#DCD4F2", TRACK_OFF="#ECE8F7", FILL_OFF="#C9C0E4",
        KNOB="#FFFFFF", KNOB_OFF="#B9B0D6", LBL_OFF="#B3AACF",
        SB="#CFC6EA", SB_HI="#B4A7E0", GLOW1=38, GLOW2=24,
    ),
}
THEME = {"name": "dark"}
globals().update(THEMES["dark"])


def tooltip_qss():
    return (f"QToolTip {{ background: {CARD_A}; color: {TXT}; border: 1px solid {BORDER}; "
            f"padding: 4px 8px; }}")


def hint_qss():
    return f"color:{HINT}; font-size:11px; background:transparent;"


def apply_theme(name):
    """Переключает палитру (dark / light) во всём приложении."""
    name = name if name in THEMES else "dark"
    THEME["name"] = name
    globals().update(THEMES[name])
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(tooltip_qss())

UI_FONTS = ["Segoe UI Variable Display", "Segoe UI", "Inter", "SF Pro Display", "Helvetica Neue", "Arial"]
W_NORMAL, W_MED, W_SEMI = QFont.Weight.Normal, QFont.Weight.Medium, QFont.Weight.DemiBold
AL_C = Qt.AlignmentFlag.AlignCenter
AL_L = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
AL_R = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
NOPEN = Qt.PenStyle.NoPen
NOBRUSH = Qt.BrushStyle.NoBrush
AA = QPainter.RenderHint.Antialiasing


def col(h, a=255):
    c = QColor(h)
    c.setAlpha(a)
    return c


def mix(a, b, t):
    a, b = QColor(a), QColor(b)
    t = max(0.0, min(1.0, t))
    return QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t), int(a.alpha() + (b.alpha() - a.alpha()) * t))


def font(px, weight=W_NORMAL, spacing=0.0):
    f = QFont()
    f.setFamilies(UI_FONTS)
    f.setPixelSize(int(px))
    f.setWeight(weight)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


def fit_tail(text, fm, maxw):
    text = text[-400:]
    if fm.horizontalAdvance(text) <= maxw:
        return text
    while text and fm.horizontalAdvance("…" + text) > maxw:
        text = text[1:]
    return "…" + text


def style_titlebar(widget):
    """Шапка окна в Windows 10/11 под текущую тему (тёмная / светлая)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        dwm = ctypes.windll.dwmapi
        dark = ctypes.c_int(1 if THEME["name"] == "dark" else 0)
        for attr in (20, 19):
            if dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(dark), 4) == 0:
                break
        c = QColor(WIN_TOP)
        cap = ctypes.c_int((c.blue() << 16) | (c.green() << 8) | c.red())    # цвет заголовка (Win11), BGR
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(cap), 4)
        # NOMOVE | NOSIZE | NOZORDER | NOACTIVATE | FRAMECHANGED — чтобы рамка перерисовалась сразу
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0004 | 0x0010 | 0x0020)
    except Exception:
        pass


# ---------- настройки ----------
DEFAULTS = dict(
    lang="EN", dot_dash_ms=220, letter_gap_ms=800, auto_space=True, word_gap_ms=2000,
    sound=True, freq=700, volume=35, key="ctrl", dual_map="ctrl_dash", space_dbl_ms=350,
    uppercase=True, show_letters=True, on_top=False, ui_lang="en", combo=False, theme="dark",
)
K_CTRL, K_ALT, K_SPACE = int(Qt.Key.Key_Control), int(Qt.Key.Key_Alt), int(Qt.Key.Key_Space)
KEYS = {
    "enter": ("Enter", {int(Qt.Key.Key_Return), int(Qt.Key.Key_Enter)}),
    "ctrl": ("Ctrl", {K_CTRL}),
    "alt": ("Alt", {K_ALT}),
    "ctrlalt": ("Ctrl + Alt", {K_CTRL, K_ALT}),
}
RES_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))      # ресурсы (и в .exe тоже)
APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def app_icon():
    for name in ("icon.png", "icon.ico"):
        p = RES_DIR / "assets" / name
        if p.exists():
            ic = QIcon(str(p))
            if not ic.isNull():
                return ic
    return QIcon()


# ---------- язык интерфейса ----------
I18N = {
    "en": {
        "brand_sub": "type text in Morse code",
        "tip_game": "Game", "tip_settings": "Settings",
        "tip_combo": "Letters + digits + symbols in one tree",
        "tip_letters": "Letters on the tree",
        "tip_clear": "Clear all", "tip_copy_img": "Copy as image",
        "card_text": "TEXT", "card_morse": "MORSE",
        "ph_text": "Text will appear here…", "ph_morse": "•—•  code will appear here",
        "copied": "Copied ✓",
        "dot": "dot", "dash": "dash", "ms": "ms", "hz": "Hz",
        "no_symbol": "no such symbol",
        "hint_short": "short press — dot   ·   long press — dash",
        "hint_dual": "Ctrl — {a}   ·   Alt — {b}",
        "hint_key": "{key}: short press — dot, long press — dash",
        "hint_space": "   ·   Space: commit the letter, or insert a space if there is none",
        "hint_keys2": "Backspace — delete   ·   Esc — cancel the letter, Esc twice — clear everything",
        "set_title": "Settings",
        "sec_lang": "LANGUAGE", "ui_lang": "App language", "ui_lang_sub": "Applied immediately",
        "sec_timing": "TIMING",
        "dot_dash": "Dot / dash threshold",
        "dot_dash_sub": "Normal mode: the boundary between a dot and a dash. Ctrl + Alt: dash tone length (a dot is 3× shorter)",
        "letter_gap": "Pause between letters", "letter_gap_sub": "How long to wait before a letter is considered finished",
        "auto_space": "Auto-space between words", "auto_space_sub": "Off — spaces only with the Space key",
        "word_gap": "Pause between words", "word_gap_sub": "Counted from the last key press",
        "sec_sound": "SOUND",
        "beep": "Beep on key press", "beep_sub": "The tone plays while the key is held",
        "freq": "Tone frequency", "volume": "Volume", "test_sound": "Test sound",
        "sec_input": "INPUT",
        "input_key": "Input key", "dual_mode": "Ctrl + Alt mode",
        "dual_a": "Ctrl dash · Alt dot", "dual_b": "Ctrl dot · Alt dash",
        "dual_sub": "Each key gives its own symbol; press length doesn't matter",
        "upper": "UPPERCASE letters", "upper_sub": "Off — type in lowercase",
        "sec_look": "APPEARANCE",
        "theme": "Theme", "theme_sub": "Applied immediately", "theme_dark": "Dark", "theme_light": "Light",
        "on_top": "Always on top", "on_top_sub": "Applied after closing settings",
        "btn_reset": "Defaults", "btn_done": "Done",
        "confirm_title": "Reset settings", "confirm_text": "Reset all settings to defaults?",
        "confirm_sub": "The interface and input languages will stay as they are.",
        "confirm_yes": "Reset", "confirm_no": "Cancel",
        "g_title": "GAME", "g_score": "Correct: {a}    Mistakes: {b}",
        "g_words": "Words", "g_phrases": "Phrases", "g_short": "Short", "g_long": "Long",
        "g_hints_on": "Hints: on", "g_hints_off": "Hints: off",
        "g_skip": "Skip", "g_exit": "Exit",
    },
    "ru": {
        "brand_sub": "ввод текста азбукой Морзе",
        "tip_game": "Игра", "tip_settings": "Настройки",
        "tip_combo": "Буквы + цифры + символы в одном дереве",
        "tip_letters": "Буквы на дереве",
        "tip_clear": "Очистить всё", "tip_copy_img": "Копировать как картинку",
        "card_text": "ТЕКСТ", "card_morse": "МОРЗЕ",
        "ph_text": "Текст появится здесь…", "ph_morse": "•—•  код появится здесь",
        "copied": "Скопировано ✓",
        "dot": "точка", "dash": "тире", "ms": "мс", "hz": "Гц",
        "no_symbol": "нет такого символа",
        "hint_short": "коротко — точка   ·   долго — тире",
        "hint_dual": "Ctrl — {a}   ·   Alt — {b}",
        "hint_key": "{key}: коротко — точка, долго — тире",
        "hint_space": "   ·   Пробел: применить букву, а если буквы нет — поставить пробел",
        "hint_keys2": "Backspace — стереть   ·   Esc — сбросить букву, Esc дважды — очистить всё",
        "set_title": "Настройки",
        "sec_lang": "ЯЗЫК", "ui_lang": "Язык приложения", "ui_lang_sub": "Применяется сразу",
        "sec_timing": "ТАЙМИНГИ",
        "dot_dash": "Порог «точка / тире»",
        "dot_dash_sub": "Обычный режим: граница между точкой и тире. Ctrl + Alt: длина звука тире (точка в 3 раза короче)",
        "letter_gap": "Пауза между буквами", "letter_gap_sub": "Через сколько буква считается законченной",
        "auto_space": "Автопробел между словами", "auto_space_sub": "Выкл — пробел только клавишей Пробел",
        "word_gap": "Пауза между словами", "word_gap_sub": "Отсчёт идёт от последнего нажатия",
        "sec_sound": "ЗВУК",
        "beep": "Писк при нажатии", "beep_sub": "Тон звучит, пока клавиша зажата",
        "freq": "Частота тона", "volume": "Громкость", "test_sound": "Проверить звук",
        "sec_input": "ВВОД",
        "input_key": "Клавиша ввода", "dual_mode": "Режим Ctrl + Alt",
        "dual_a": "Ctrl тире · Alt точка", "dual_b": "Ctrl точка · Alt тире",
        "dual_sub": "Каждая клавиша даёт свой символ, длительность не важна",
        "upper": "ЗАГЛАВНЫЕ буквы", "upper_sub": "Выкл — вводить строчными",
        "sec_look": "ВНЕШНИЙ ВИД",
        "theme": "Тема", "theme_sub": "Применяется сразу", "theme_dark": "Тёмная", "theme_light": "Светлая",
        "on_top": "Поверх всех окон", "on_top_sub": "Применится после закрытия настроек",
        "btn_reset": "По умолчанию", "btn_done": "Готово",
        "confirm_title": "Сброс настроек", "confirm_text": "Сбросить все настройки по умолчанию?",
        "confirm_sub": "Язык интерфейса и язык ввода не изменятся.",
        "confirm_yes": "Сбросить", "confirm_no": "Отмена",
        "g_title": "ИГРА", "g_score": "Верно: {a}    Ошибок: {b}",
        "g_words": "Слова", "g_phrases": "Фразы", "g_short": "Короткие", "g_long": "Длинные",
        "g_hints_on": "Подсказки: вкл", "g_hints_off": "Подсказки: выкл",
        "g_skip": "Пропуск", "g_exit": "Выход",
    },
}
UI = {"lang": "en"}


def tr(_name, /, **kw):
    s = I18N[UI["lang"]].get(_name) or I18N["en"].get(_name, _name)
    return s.format(**kw) if kw else s


def set_ui_lang(code):
    UI["lang"] = code if code in I18N else "en"


def key_hints(st):
    if st["key"] == "ctrlalt":
        a, b = (tr("dash"), tr("dot")) if st["dual_map"] == "ctrl_dash" else (tr("dot"), tr("dash"))
        return tr("hint_dual", a=a, b=b)
    return tr("hint_short")


class Settings:
    path = APP_DIR / "morse_settings.json"          # рядом с .py или .exe

    def __init__(self):
        self.d = dict(DEFAULTS)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for k, v in data.items():
                if k in DEFAULTS and type(v) is type(DEFAULTS[k]):
                    self.d[k] = v
            if self.d["key"] not in KEYS:
                self.d["key"] = DEFAULTS["key"]
            if self.d["lang"] not in LANGS:
                self.d["lang"] = "EN"
            if self.d["combo"] and self.d["lang"] not in ("EN", "RU"):
                self.d["lang"] = "EN"
            if self.d["ui_lang"] not in ("en", "ru"):
                self.d["ui_lang"] = "en"
            if self.d["dual_map"] not in ("ctrl_dash", "alt_dash"):
                self.d["dual_map"] = "ctrl_dash"
            if self.d["theme"] not in THEMES:
                self.d["theme"] = "dark"
        except Exception:
            pass

    def __getitem__(self, k):
        return self.d[k]

    def __setitem__(self, k, v):
        self.d[k] = v

    def save(self):
        try:
            self.path.write_text(json.dumps(self.d, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def reset(self):
        keep = {k: self.d[k] for k in ("lang", "ui_lang", "combo")}   # язык ввода, интерфейса и режим дерева не сбрасываем
        self.d = dict(DEFAULTS)
        self.d.update(keep)


# ---------- звук ----------
class Tone:
    def __init__(self):
        self.ok = HAVE_SOUND
        self.enabled = True
        self.playing = False
        self.freq = None
        self.vol = 0.35
        self.fx = None
        if self.ok:
            try:
                self.fx = QSoundEffect()
                self.fx.setLoopCount(-2)          # бесконечно, пока зажата клавиша
            except Exception:
                self.ok = False

    @staticmethod
    def _make(freq):
        rate = 44100
        cycles = max(1, round(freq * 0.2))
        n = round(cycles * rate / freq)
        path = Path(tempfile.gettempdir()) / f"morse_kbd_tone_{freq}.wav"
        if not path.exists():
            frames = bytearray()
            for i in range(n):
                v = int(32767 * 0.8 * math.sin(2 * math.pi * cycles * i / n))
                frames += v.to_bytes(2, "little", signed=True)
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes(bytes(frames))
        return str(path)

    def configure(self, freq, volume, enabled):
        self.enabled = bool(enabled)
        self.vol = max(0.0, min(1.0, volume / 100.0))
        if not self.ok:
            return
        try:
            if freq != self.freq:
                self.freq = freq
                self.fx.setSource(QUrl.fromLocalFile(self._make(freq)))
            self.fx.setVolume(self.vol)
        except Exception:
            self.ok = False

    def start(self):
        if not (self.ok and self.enabled):
            return
        self.playing = True
        try:
            self.fx.setVolume(self.vol)
            if not self.fx.isPlaying():
                self.fx.play()
        except Exception:
            pass

    def stop(self):
        if not self.playing:
            return
        self.playing = False
        steps = (0.55, 0.25, 0.08, 0.0)

        def step(i=0):
            if self.playing:
                return
            try:
                if i >= len(steps):
                    self.fx.stop()
                    self.fx.setVolume(self.vol)
                    return
                self.fx.setVolume(self.vol * steps[i])
            except Exception:
                return
            QTimer.singleShot(4, lambda: step(i + 1))
        step()

    def beep(self, ms=220):
        self.start()
        QTimer.singleShot(ms, self.stop)


# ---------- логика ввода ----------
class Engine(QObject):
    changed = Signal()

    def __init__(self, st, tone):
        super().__init__()
        self.st, self.tone = st, tone
        self.seq = ""
        self.items = []                 # [(символ, код)], пробел -> (" ", "/")
        self.pressed = False
        self.forced, self.owner = None, None
        self.esc_t = -10.0
        self.t0 = 0.0
        self.flash_code, self.flash_t, self.err_t = None, -10.0, -10.0
        self.lt = QTimer(self)
        self.lt.setSingleShot(True)
        self.lt.timeout.connect(self.commit)
        self.wt = QTimer(self)
        self.wt.setSingleShot(True)
        self.wt.timeout.connect(self.word_space)
        self.tt = QTimer(self)
        self.tt.setSingleShot(True)
        self.tt.timeout.connect(self._tap_end)
        self.tap_sym, self.tap_t0, self.tap_dur, self.tap_until = "", 0.0, 1, 0.0
        self.space_t = -10.0
        self.set_lang(eff_lang(st))

    # --- служебное ---
    def set_lang(self, lang):
        self.lang = lang
        self.table = {code: ch for ch, code in LANGS[lang].items()}
        self.table.update({code: ch for ch, code in EXTRA.items()})
        self.seq = ""
        self.lt.stop()
        self.wt.stop()
        self.changed.emit()

    def fmt(self, ch):
        return ch.upper() if self.st["uppercase"] else ch.lower()

    def text_str(self):
        return "".join(ch for ch, _ in self.items)

    def hold_ms(self):
        return (time.perf_counter() - self.t0) * 1000.0 if self.pressed else 0.0

    def preview(self):
        if not self.seq:
            return ("none", "")
        ch = self.table.get(self.seq)
        if ch is not None:
            return ("ok", self.fmt(ch))
        if any(k.startswith(self.seq) for k in self.table):
            return ("partial", "")
        return ("bad", "")

    # --- ввод ---
    def cur_sym(self):
        if self.forced:
            return self.forced
        return "-" if self.hold_ms() >= self.st["dot_dash_ms"] else "."

    def press(self, forced=None, owner=None):
        if self.pressed:
            return
        self.lt.stop()
        self.wt.stop()
        self.pressed = True
        self.forced, self.owner = forced, owner
        self.t0 = time.perf_counter()
        self.tone.start()
        self.changed.emit()

    def release(self, owner=None):
        if not self.pressed or owner != self.owner:
            return
        sym = self.cur_sym()
        self.pressed = False
        self.tone.stop()
        if len(self.seq) >= 8:
            self.seq = ""
            self.err_t = time.perf_counter()
        else:
            self.seq += sym
            self.lt.start(int(self.st["letter_gap_ms"]))
        self.forced = None
        self.changed.emit()

    def abort(self):
        if self.pressed:
            self.pressed = False
            self.forced = None
            self.tone.stop()
            if self.seq:
                self.lt.start(int(self.st["letter_gap_ms"]))
            self.changed.emit()

    def tapping(self):
        return time.perf_counter() < self.tap_until

    def tap(self, sym):
        """Режим Ctrl + Alt: символ задаёт клавиша, звук фиксированной длины (от порога)."""
        self.lt.stop()
        self.wt.stop()
        thr = int(self.st["dot_dash_ms"])
        dur = thr if sym == "-" else max(50, thr // 3)
        now = time.perf_counter()
        if len(self.seq) >= 8:
            self.seq = ""
            self.err_t = now
        else:
            self.seq += sym
        self.tap_sym, self.tap_t0, self.tap_dur = sym, now, dur
        self.tap_until = now + dur / 1000.0
        self.tone.start()
        self.tt.start(dur)
        self.changed.emit()

    def _tap_end(self):
        self.tap_until = 0.0
        self.tone.stop()
        if self.seq:
            self.lt.start(int(self.st["letter_gap_ms"]))
        self.changed.emit()

    def space_press(self):
        """Есть набранная буква — Пробел её применяет; буквы нет — ставит пробел."""
        if self.pressed:
            return
        self.lt.stop()
        if self.seq:
            self.wt.stop()
            self.commit()
            self.wt.stop()                  # после ручного применения авто-пробел не нужен
        else:
            self.wt.stop()
            if self.items and self.items[-1][0] != " ":
                self.items.append((" ", "/"))
            self.changed.emit()

    def esc(self):
        now = time.perf_counter()
        if now - self.esc_t < 0.45:
            self.esc_t = -10.0
            self.clear_all()
        else:
            self.esc_t = now
            self.cancel()

    def commit(self):
        if not self.seq:
            return
        ch = self.table.get(self.seq)
        now = time.perf_counter()
        if ch is None:
            self.err_t = now
        else:
            self.items.append((self.fmt(ch), self.seq))
            self.flash_code, self.flash_t = self.seq, now
            if self.st["auto_space"]:
                self.wt.start(max(150, int(self.st["word_gap_ms"]) - int(self.st["letter_gap_ms"])))
        self.seq = ""
        self.changed.emit()

    def word_space(self):
        if self.items and self.items[-1][0] != " ":
            self.items.append((" ", "/"))
            self.changed.emit()

    def backspace(self):
        self.wt.stop()
        if self.seq:
            self.seq = self.seq[:-1]
            if self.seq:
                self.lt.start(int(self.st["letter_gap_ms"]))
            else:
                self.lt.stop()
        elif self.items:
            self.items.pop()
        self.changed.emit()

    def cancel(self):
        self.seq = ""
        self.lt.stop()
        self.changed.emit()

    def clear_all(self):
        self.items, self.seq = [], ""
        self.lt.stop()
        self.wt.stop()
        self.changed.emit()


# ---------- общие мини-виджеты ----------
def icon_sliders(p, r, color):
    pen = QPen(color, 1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    ys = [r.top() + 3, r.center().y(), r.bottom() - 3]
    xs = [r.left() + r.width() * 0.68, r.left() + r.width() * 0.32, r.left() + r.width() * 0.56]
    for y, kx in zip(ys, xs):
        p.setBrush(NOBRUSH)
        p.drawLine(QPointF(r.left() + 1, y), QPointF(r.right() - 1, y))
        p.setBrush(col(SURF))
        p.drawEllipse(QPointF(kx, y), 3.0, 3.0)


def icon_close(p, r, color):
    pen = QPen(color, 1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    m = 5.5
    p.drawLine(QPointF(r.left() + m, r.top() + m), QPointF(r.right() - m, r.bottom() - m))
    p.drawLine(QPointF(r.right() - m, r.top() + m), QPointF(r.left() + m, r.bottom() - m))


def icon_check(p, r, color):
    pen = QPen(color, 2.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.drawPolyline([QPointF(r.left() + 3, r.center().y()), QPointF(r.left() + 7.5, r.bottom() - 5),
                    QPointF(r.right() - 2.5, r.top() + 5)])


def icon_image(p, r, color):
    pen = QPen(color, 1.6)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(NOBRUSH)
    p.drawRoundedRect(QRectF(r.left() + 1, r.top() + 2.5, r.width() - 2, r.height() - 5), 3, 3)
    p.drawPolyline([QPointF(r.left() + 3, r.bottom() - 5), QPointF(r.left() + 8, r.center().y() + 0.5),
                    QPointF(r.left() + 11.5, r.bottom() - 7.5), QPointF(r.right() - 3, r.bottom() - 5)])
    p.setPen(NOPEN)
    p.setBrush(color)
    p.drawEllipse(QPointF(r.right() - 6, r.top() + 7), 1.6, 1.6)


def icon_gamepad(p, r, color):
    p.setPen(QPen(color, 1.6))
    p.setBrush(NOBRUSH)
    body = QRectF(r.left() - 1, r.top() + 3, r.width() + 2, r.height() - 6)
    p.drawRoundedRect(body, 6, 6)
    cx, cy = body.left() + 6.5, body.center().y()
    p.drawLine(QPointF(cx - 2.5, cy), QPointF(cx + 2.5, cy))
    p.drawLine(QPointF(cx, cy - 2.5), QPointF(cx, cy + 2.5))
    p.setPen(NOPEN)
    p.setBrush(color)
    p.drawEllipse(QPointF(body.right() - 8, cy - 1.8), 1.5, 1.5)
    p.drawEllipse(QPointF(body.right() - 4.8, cy + 1.6), 1.5, 1.5)


def icon_combo(p, r, color):
    """Три источника (буквы / цифры / символы) сливаются в одну линию."""
    pen = QPen(color, 1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(NOBRUSH)
    cy = r.center().y()
    jx = r.left() + 9.5
    for y in (r.top() + 3.0, cy, r.bottom() - 3.0):
        path = QPainterPath(QPointF(r.left() + 2.5, y))
        path.cubicTo(QPointF(r.left() + 7, y), QPointF(r.left() + 6, cy), QPointF(jx, cy))
        p.drawPath(path)
    p.drawLine(QPointF(jx, cy), QPointF(r.right() - 6, cy))
    p.setPen(NOPEN)
    p.setBrush(color)
    for y in (r.top() + 3.0, cy, r.bottom() - 3.0):
        p.drawEllipse(QPointF(r.left() + 2.5, y), 2.0, 2.0)
    p.drawRoundedRect(QRectF(r.right() - 7.5, cy - 2.2, 8.5, 4.4), 2.2, 2.2)


def icon_eye(p, r, color, slash=False):
    """Глаз: буквы на дереве видны. С чертой — скрыты."""
    pen = QPen(color, 1.7)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(NOBRUSH)
    cx, cy = r.center().x(), r.center().y()
    path = QPainterPath(QPointF(r.left() + 0.5, cy))
    path.quadTo(QPointF(cx, cy - 10.5), QPointF(r.right() - 0.5, cy))
    path.quadTo(QPointF(cx, cy + 10.5), QPointF(r.left() + 0.5, cy))
    p.drawPath(path)
    p.setPen(NOPEN)
    p.setBrush(color)
    p.drawEllipse(QPointF(cx, cy), 2.6, 2.6)
    if slash:
        p.setPen(pen)
        p.drawLine(QPointF(r.left() + 3.5, r.bottom() - 2.5), QPointF(r.right() - 3.5, r.top() + 2.5))


def icon_eye_off(p, r, color):
    icon_eye(p, r, color, slash=True)


class FlatButton(QWidget):
    clicked = Signal()

    def __init__(self, text="", icon=None, primary=False, px=12, size=38, parent=None, width=None):
        super().__init__(parent)
        self.text, self.icon, self.primary, self.px = text, icon, primary, px
        self.size_, self.bw, self.active = size, width, False
        self._hover = self._down = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._fit()

    def setText(self, t):
        self.text = t
        self._fit()
        self.update()

    def _fit(self):
        if not self.text:
            self.setFixedSize(self.bw or self.size_, self.size_)      # bw — ширина, если кнопка не квадратная
            return
        fm = QFontMetricsF(font(self.px, W_SEMI))
        w = fm.horizontalAdvance(self.text) + 32
        self.setFixedSize(int(max(w, 60)), 32)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = self._down = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._down = True
            self.update()

    def mouseReleaseEvent(self, e):
        was = self._down
        self._down = False
        self.update()
        if was and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(AA)
        if not self.isEnabled():
            p.setOpacity(0.35)
        r = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        rad = min(12.0, r.height() / 2)
        if self.primary:
            g = QLinearGradient(r.topLeft(), r.bottomLeft())
            g.setColorAt(0, col(ACC_L if self._hover else ACC))
            g.setColorAt(1, col(ACC_D))
            p.setBrush(g)
            p.setPen(NOPEN)
            fg = col("#FFFFFF")
        else:
            t = 0.3 if self._down else (0.16 if self._hover else 0.0)
            if self.active:
                t = max(t, 0.38)
            p.setBrush(mix(SURF, ACC, t))
            p.setPen(QPen(col(ACC_L if self.active else (BORDER_HI if self._hover else BORDER)), 1))
            fg = col(BTN_ON if self.active else (TXT if self._hover else MID))
        p.drawRoundedRect(r, rad, rad)
        if self.icon:
            self.icon(p, QRectF(r.center().x() - 9, r.center().y() - 9, 18, 18), fg)
        if self.text:
            p.setFont(font(self.px, W_SEMI))
            p.setPen(fg)
            p.drawText(r, AL_C, self.text)


class Segmented(QWidget):
    changed = Signal(str)

    def __init__(self, items, value, h=38, pad=30, parent=None, drag=False):
        super().__init__(parent)
        self.items, self.value, self.pad, self.h_ = items, value, pad, h
        self.drag = drag                    # можно ли «хватать» и таскать ползунок как на телефоне
        self._measure()
        self._pos = float(self._idx())
        self._dragging = False
        self._dtarget, self._grab, self._v, self._grow = self._pos, 0.0, 0.0, 0.0
        self._spring = QTimer(self)         # пружинка ползунка
        self._spring.setInterval(16)
        self._spring.timeout.connect(self._spring_tick)
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(220)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.valueChanged.connect(self._on)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.disabled = set()               # недоступные пункты (затемнены, не нажимаются)
        self._fade, self._fade_from = {}, {}
        self.fade_anim = QVariantAnimation(self)
        self.fade_anim.setDuration(220)
        self.fade_anim.setStartValue(0.0)
        self.fade_anim.setEndValue(1.0)
        self.fade_anim.valueChanged.connect(self._fade_step)

    def set_disabled(self, keys):
        keys = set(keys)
        self._fade_from = {k: self._fade.get(k, 0.0) for k, _ in self.items}
        self.disabled = keys
        self.fade_anim.stop()
        self.fade_anim.start()

    def _fade_step(self, t):
        for k, _ in self.items:
            a, b = self._fade_from.get(k, 0.0), (1.0 if k in self.disabled else 0.0)
            self._fade[k] = a + (b - a) * float(t)
        self.update()

    def _measure(self):
        fm = QFontMetricsF(font(13, W_SEMI))
        self.seg = max(fm.horizontalAdvance(t) for _, t in self.items) + self.pad
        self.setFixedSize(int(self.seg * len(self.items) + 8), self.h_)

    def set_items(self, items):
        """Меняет подписи (например, при смене языка), значение сохраняется."""
        self.items = items
        self._measure()
        self.update()

    def _idx(self):
        return [k for k, _ in self.items].index(self.value)

    def _on(self, v):
        self._pos = float(v)
        self.update()

    def set_value(self, v, animate=True):
        self.value = v
        self._spring.stop()
        self._dragging, self._v, self._grow = False, 0.0, 0.0
        if animate:
            self.anim.stop()
            self.anim.setStartValue(self._pos)
            self.anim.setEndValue(float(self._idx()))
            self.anim.start()
        else:
            self._pos = float(self._idx())
            self.update()

    # --- перетаскивание ---
    def _enabled_idx(self):
        return [i for i, (k, _) in enumerate(self.items) if k not in self.disabled]

    def _raw(self, e):
        return (e.position().x() - 4) / self.seg - 0.5          # центр ползунка под курсором

    def _drag_to(self, raw):
        en = self._enabled_idx()
        if not en:
            return
        self._dtarget = max(float(en[0]), min(float(en[-1]), raw))
        near = min(en, key=lambda i: abs(i - self._dtarget))     # ближайший доступный пункт
        key = self.items[near][0]
        if key != self.value:                                    # переключаем «на лету», не отпуская
            self.value = key
            self.changed.emit(key)

    def _spring_tick(self):
        d = self._dtarget - self._pos
        self._v = (self._v + d * 0.22) * 0.62                    # лёгкая пружина с небольшим «перелётом»
        self._pos += self._v
        n = len(self.items) - 1
        self._pos = max(-0.15, min(n + 0.15, self._pos))
        self._grow += ((1.0 if self._dragging else 0.0) - self._grow) * 0.3
        if (not self._dragging and abs(d) < 0.002 and abs(self._v) < 0.002
                and self._grow < 0.01):
            self._pos, self._v, self._grow = self._dtarget, 0.0, 0.0
            self._spring.stop()
        self.update()

    def mousePressEvent(self, e):
        if self.drag:
            if e.button() != Qt.MouseButton.LeftButton or not self._enabled_idx():
                return
            raw = self._raw(e)
            i = max(0, min(len(self.items) - 1, int((e.position().x() - 4) // self.seg)))
            if self.items[i][0] in self.disabled:
                return
            self.anim.stop()
            # если схватили сам ползунок — не даём ему «прыгнуть» под курсор
            self._grab = (self._pos - raw) if abs(self._pos - raw) < 0.5 else 0.0
            self._dragging = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self._drag_to(raw + self._grab)
            if not self._spring.isActive():
                self._spring.start()
            return
        i = int((e.position().x() - 4) // self.seg)
        i = max(0, min(len(self.items) - 1, i))
        key = self.items[i][0]
        if key in self.disabled:
            return
        if key != self.value:
            self.set_value(key)
            self.changed.emit(key)

    def mouseMoveEvent(self, e):
        if self.drag and self._dragging:
            self._drag_to(self._raw(e) + self._grab)

    def mouseReleaseEvent(self, e):
        if self.drag and self._dragging:
            self._dragging = False
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self._dtarget = float(self._idx())                  # отпустили — прилипаем к ближайшему пункту
            if not self._spring.isActive():
                self._spring.start()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(AA)
        if not self.isEnabled():
            p.setOpacity(0.35)
        r = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        p.setBrush(col(SURF))
        p.setPen(QPen(col(BORDER), 1))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        kh = self.height() - 8
        k = QRectF(4 + self._pos * self.seg, 4, self.seg, kh)
        gw = 2.5 * self._grow + min(0.22, abs(self._v) * 0.5) * self.seg * 0.5    # «схвачен» + растяжение при движении
        k.adjust(-gw, 0, gw, 0)
        g = QLinearGradient(k.topLeft(), k.bottomRight())
        g.setColorAt(0, col(ACC_L))
        g.setColorAt(1, col(ACC_D))
        p.setPen(NOPEN)
        p.setBrush(g)
        p.drawRoundedRect(k, kh / 2, kh / 2)
        p.setFont(font(13, W_SEMI))
        for i, (key, text) in enumerate(self.items):
            t = 1.0 - min(1.0, abs(i - self._pos))
            f = self._fade.get(key, 0.0)
            p.setPen(mix(mix(DIM, "#FFFFFF", t), SURF, 0.72 * f))
            p.drawText(QRectF(4 + i * self.seg, 4, self.seg, kh), AL_C, text)


class Toggle(QWidget):
    toggled = Signal(bool)

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.checked = checked
        self._pos = 1.0 if checked else 0.0
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(170)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.valueChanged.connect(self._on)
        self.setFixedSize(48, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _on(self, v):
        self._pos = float(v)
        self.update()

    def set_checked(self, c, animate=True):
        self.checked = bool(c)
        if animate:
            self.anim.stop()
            self.anim.setStartValue(self._pos)
            self.anim.setEndValue(1.0 if self.checked else 0.0)
            self.anim.start()
        else:
            self._pos = 1.0 if self.checked else 0.0
            self.update()

    def mousePressEvent(self, e):
        self.set_checked(not self.checked)
        self.toggled.emit(self.checked)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(AA)
        if not self.isEnabled():
            p.setOpacity(0.35)
        r = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        p.setBrush(mix(TOG_OFF, ACC, self._pos))
        p.setPen(QPen(mix(BORDER, ACC_L, self._pos), 1))
        p.drawRoundedRect(r, 13, 13)
        p.setPen(NOPEN)
        p.setBrush(mix(MID, "#FFFFFF", self._pos))
        p.drawEllipse(QRectF(4 + self._pos * 22, 4, 18, 18))


class Brand(QWidget):
    egg = Signal()                                  # пасхалка: 5 нажатий на значок
    ICON = QRectF(0, 3, 34, 34)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(190, 40)
        self._n, self._t = 0, 0.0                   # курсор и подсказок намеренно нет — значок выглядит обычной картинкой

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.ICON.contains(e.position()):
            now = time.perf_counter()
            self._n = self._n + 1 if now - self._t < 2.0 else 1       # серия: не дольше 2 с между нажатиями
            self._t = now
            if self._n >= 5:
                self._n = 0
                self.egg.emit()
        else:
            e.ignore()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(AA)
        g = QLinearGradient(0, 3, 34, 37)
        g.setColorAt(0, col(ACC_L))
        g.setColorAt(1, col(ACC_D))
        p.setPen(NOPEN)
        p.setBrush(g)
        p.drawRoundedRect(QRectF(0, 3, 34, 34), 11, 11)
        p.setBrush(col("#FFFFFF"))
        p.drawEllipse(QPointF(10, 20), 3.2, 3.2)
        p.drawRoundedRect(QRectF(16, 17, 12, 6), 3, 3)
        p.setFont(font(18, W_SEMI))
        p.setPen(col(TXT))
        p.drawText(QRectF(46, 1, 150, 22), AL_L, "PhMorse v1.0.3")
        p.setFont(font(11, W_NORMAL))
        p.setPen(col(DIM))
        p.drawText(QRectF(46, 22, 150, 16), AL_L, tr("brand_sub"))


# ---------- символы • и — ----------
def sym_width(seq, D, W, gap):
    return sum(D if s == "." else W for s in seq) + gap * max(0, len(seq) - 1)


def draw_syms(p, seq, x, cy, D, W, gap, alpha=255, last_alpha=None):
    p.setPen(NOPEN)
    for i, s in enumerate(seq):
        a = last_alpha if (last_alpha is not None and i == len(seq) - 1) else alpha
        if s == ".":
            p.setBrush(col(ACC_L, a))
            p.drawEllipse(QRectF(x, cy - D / 2, D, D))
            x += D + gap
        else:
            p.setBrush(col(DASH, a))
            p.drawRoundedRect(QRectF(x, cy - D / 2, W, D), D / 2, D / 2)
            x += W + gap
    return x


# ---------- карточка с двумя строками ----------
def morse_text(items):
    return " ".join("/" if ch == " " else code for ch, code in items)


class OutputCard(QWidget):
    D, W, GAP, LET, WORD = 7, 28, 5, 18, 16

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.hover = None
        self.toast = ("", 0.0)
        self.setFixedHeight(166)
        self.setMouseTracking(True)
        self.b_clear = FlatButton(icon=icon_close, size=26, parent=self)
        self.b_img = FlatButton(icon=icon_image, size=30, parent=self)
        self.retranslate()
        self.b_clear.clicked.connect(engine.clear_all)
        self.b_img.clicked.connect(self.copy_image)

    def retranslate(self):
        self.b_clear.setToolTip(tr("tip_clear"))
        self.b_img.setToolTip(tr("tip_copy_img"))
        self.update()

    def resizeEvent(self, e):
        self.b_clear.move(12, 10)
        self.b_img.move(self.width() - 16 - 30, self.height() - 12 - 30)

    # --- клики: текст и морзе копируются нажатием ---
    def _row_at(self, pos):
        if 38 <= pos.y() < 88:
            return "text"
        if 92 <= pos.y() < 162 and not self.b_img.geometry().contains(pos):
            return "morse"
        return None

    def mouseMoveEvent(self, e):
        row = self._row_at(e.position().toPoint())
        if row != self.hover:
            self.hover = row
            self.setCursor(Qt.CursorShape.PointingHandCursor if row else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, e):
        self.hover = None
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            row = self._row_at(e.position().toPoint())
            if row:
                self.copy_row(row)

    def _flash(self, what):
        self.toast = (what, time.perf_counter() + 1.3)
        self.update()
        QTimer.singleShot(1350, self.update)

    def copy_row(self, row):
        e = self.engine
        s = e.text_str() if row == "text" else morse_text(e.items)
        if s.strip():
            QApplication.clipboard().setText(s)
            self._flash(row)

    # --- картинка ---
    def content_width(self):
        e = self.engine
        tw = QFontMetricsF(font(28, W_SEMI)).horizontalAdvance(e.text_str())
        widths = [self.WORD if ch == " " else sym_width(code, self.D, self.W, self.GAP) for ch, code in e.items]
        return max(tw, sum(widths) + self.LET * max(0, len(widths) - 1))

    def render_image(self):
        margin, scale = 14, 2
        w = int(max(320, min(6000, self.content_width() + 58)))
        h = self.height()
        img = QImage((w + 2 * margin) * scale, (h + 2 * margin) * scale, QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(scale)
        img.fill(QColor(BG0))
        p = QPainter(img)
        p.setRenderHint(AA)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.translate(margin, margin)
        self.paint_card(p, w, h, shot=True)
        p.end()
        return img

    def copy_image(self):
        if not self.engine.items:
            return
        QApplication.clipboard().setImage(self.render_image())
        self.b_img.icon = icon_check
        self.b_img.update()

        def back():
            self.b_img.icon = icon_image
            self.b_img.update()
        QTimer.singleShot(1300, back)

    # --- рисование (одно и то же для окна и для картинки) ---
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(AA)
        self.paint_card(p, self.width(), self.height())

    def paint_card(self, p, w, h, shot=False):
        e = self.engine
        D, W, GAP, LET, WORD = self.D, self.W, self.GAP, self.LET, self.WORD
        r = QRectF(.5, .5, w - 1, h - 1)
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0, col(CARD_A))
        g.setColorAt(1, col(CARD_B))
        p.setBrush(g)
        p.setPen(QPen(col(BORDER), 1))
        p.drawRoundedRect(r, 22, 22)
        pad = 24
        lx = pad if shot else pad + 26
        now = time.perf_counter()
        if not shot and self.hover:
            hr = QRectF(10, 38, w - 20, 48) if self.hover == "text" else QRectF(10, 94, w - 20, 64)
            p.setPen(NOPEN)
            p.setBrush(col(ACC, 26))
            p.drawRoundedRect(hr, 14, 14)
        p.setFont(font(10, W_SEMI, 2.5))
        p.setPen(col(DIM))
        p.drawText(QPointF(lx, 30), tr("card_text"))
        p.drawText(QPointF(lx, 110), tr("card_morse"))
        p.setPen(QPen(col(LINE), 1))
        p.drawLine(QPointF(pad, 88), QPointF(w - pad, 88))

        # --- строка 1: буквы ---
        f_big = font(28, W_SEMI)
        fm = QFontMetricsF(f_big)
        state, ch = ("none", "") if shot else e.preview()
        committed = e.text_str()
        shown = ch if state == "ok" else ("?" if state == "bad" else "")
        prev_w = fm.horizontalAdvance(shown) if shown else 0.0
        y, x = 70, float(pad)
        if not committed and not shown:
            if not shot:
                p.setFont(font(17, W_NORMAL))
                p.setPen(col(HOLD))
                p.drawText(QPointF(pad, y - 4), tr("ph_text"))
        else:
            tail = committed if shot else fit_tail(committed, fm, w - 2 * pad - prev_w - 10)
            p.setFont(f_big)
            p.setPen(col(TXT))
            p.drawText(QPointF(x, y), tail)
            x += fm.horizontalAdvance(tail)
            if shown:
                c = ERR if state == "bad" else ACC_L
                p.setPen(col(c, 235))
                p.drawText(QPointF(x, y), shown)
                p.setPen(NOPEN)
                p.setBrush(col(c, 200))
                p.drawRoundedRect(QRectF(x, y + 6, prev_w, 2.5), 1.2, 1.2)
                x += prev_w

        # --- строка 2: морзянка ---
        cy = 138
        entries = [("w", None, False) if c == " " else ("c", code, False) for c, code in e.items]
        if e.seq and not shot:
            entries.append(("c", e.seq, True))
        if not entries:
            if not shot:
                p.setFont(font(15, W_NORMAL))
                p.setPen(col(HOLD))
                p.drawText(QPointF(pad, cy + 5), tr("ph_morse"))
        else:
            widths = [WORD if k == "w" else sym_width(c, D, W, GAP) for k, c, _ in entries]
            maxw = 1e9 if shot else w - 2 * pad - 24 - 44
            total, start = 0.0, len(entries)
            for i in range(len(entries) - 1, -1, -1):
                add = widths[i] + (LET if total else 0)
                if total + add > maxw:
                    break
                total += add
                start = i
            x = float(pad)
            if start > 0:
                p.setFont(font(16, W_MED))
                p.setPen(col(DIM))
                p.drawText(QPointF(x, cy + 6), "…")
                x += 24
            for i in range(start, len(entries)):
                k, c, pending = entries[i]
                if k == "w":
                    p.setPen(QPen(col(DIM), 1.6))
                    p.drawLine(QPointF(x + 4, cy + 8), QPointF(x + 11, cy - 8))
                else:
                    draw_syms(p, c, x, cy, D, W, GAP, alpha=255 if pending else 205)
                x += widths[i] + LET

        if not shot and self.toast[0] in ("text", "morse") and now < self.toast[1]:
            ty = 44 if self.toast[0] == "text" else 98
            trc = QRectF(w - pad - 112, ty, 112, 24)
            p.setPen(NOPEN)
            p.setBrush(col(ACC, 235))
            p.drawRoundedRect(trc, 12, 12)
            p.setFont(font(11, W_SEMI))
            p.setPen(col("#FFFFFF"))
            p.drawText(trc, AL_C, tr("copied"))


# ---------- дерево ----------
def _lerp(a, b, t):
    return a + (b - a) * t


def _smooth(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _ease(t):
    """InOutCubic — мягкий старт и мягкая остановка."""
    t = max(0.0, min(1.0, t))
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def with_alpha(c, a):
    c = QColor(c)
    c.setAlpha(int(max(0, min(255, c.alpha() * a))))
    return c


class TreeView(QWidget):
    ANIM_S = 0.65          # длительность анимации смены дерева, сек

    def __init__(self, engine, st, parent=None):
        super().__init__(parent)
        self.engine, self.st = engine, st
        self.glow, self.hot = {}, 0.0
        self.override_letters = None      # игра может принудительно скрыть/показать буквы
        self.pos, self.letters, self.extra = {}, {}, set()
        self._lang = None
        self._from = None                 # снимок сцены, из которой едем
        self._ghost = {}                  # свечение уходящих узлов
        self._t0 = None                   # время старта анимации
        self.setMinimumHeight(280)
        self.set_lang(engine.lang)

    def set_lang(self, lang):
        if lang == self._lang and self.pos:
            self.update()
            return
        old_scene = old_glow = None
        if self._lang is not None and self.isVisible() and self.width() > 50:
            old_scene = self._scene()[0]            # текущий кадр (даже если прошлая анимация не закончилась)
            old_glow = {**self._ghost, **self.glow}
        self._lang = lang
        self.letters = {code: ch for ch, code in LANGS[lang].items()}
        self.extra = EXTRA_CODES if lang.startswith("ALL_") else set()   # цифры/символы в совмещённом дереве
        self.pos = LAYOUTS[lang]
        cs = [c for c, _ in self.pos.values()]
        rs = [r for _, r in self.pos.values()]
        self.minc, self.minr = min(cs), min(rs)
        self.ncols, self.nrows = max(cs) - min(cs) + 1, max(rs) - min(rs) + 1
        if old_scene is not None:
            self._from, self._ghost = old_scene, old_glow
            self._t0 = time.perf_counter()
            self.glow = {c: g for c, g in self.glow.items() if c in self.pos}
        else:
            self._from, self._ghost, self._t0 = None, {}, None
            self.glow = {}
        self.update()

    def tick(self):
        e, now = self.engine, time.perf_counter()
        anim = self._t0 is not None
        if anim and now - self._t0 >= self.ANIM_S:
            self._t0, self._from, self._ghost = None, None, {}     # анимация закончилась (последний кадр рисуем ниже)
        path = []
        for i in range(len(e.seq) + 1):
            if e.seq[:i] in self.pos:
                path.append(e.seq[:i])
            else:
                break
        cur = path[-1] if path else ""
        tgt = {c: 0.42 for c in path}
        tgt[cur] = 1.0 if (e.seq or e.pressed) else 0.55
        if e.pressed:
            cand = cur + e.cur_sym()
            if cand in self.pos and len(cand) == len(e.seq) + 1:
                tgt[cand] = max(tgt.get(cand, 0), 0.6)
        hot = 0.0
        if e.flash_code in self.pos:
            hot = max(0.0, 1.0 - (now - e.flash_t) / 0.55)
            tgt[e.flash_code] = max(tgt.get(e.flash_code, 0), hot)
        dirty = (hot != self.hot) or hot > 0 or anim
        self.hot = hot
        for code in self.pos:
            t, g = tgt.get(code, 0.0), self.glow.get(code, 0.0)
            ng = g + (t - g) * 0.25
            if abs(t - ng) < 0.004:
                ng = t
            if ng != g:
                self.glow[code] = ng
                dirty = True
        if now - e.err_t < 0.45 or (now - e.err_t) < 0.5:
            dirty = True
        if dirty:
            self.update()

    def letters_visible(self):
        return self.st["show_letters"] if self.override_letters is None else self.override_letters

    def _grid(self):
        area = QRectF(self.rect()).adjusted(18, 54, -18, -20)
        pitch = min(area.width() / self.ncols, area.height() / self.nrows, 62.0)
        gw, gh = pitch * self.ncols, pitch * self.nrows
        return area.left() + (area.width() - gw) / 2, area.top() + (area.height() - gh) * 0.4, pitch

    # ---------- сцена: геометрия узлов в пикселях ----------
    def _target(self):
        """Где узлы текущего дерева должны стоять в покое: {код: x, y, w, h, a, lets}."""
        x0, y0, pitch = self._grid()
        pts = {code: QPointF(x0 + (c - self.minc + .5) * pitch, y0 + (rr - self.minr + .5) * pitch)
               for code, (c, rr) in self.pos.items()}
        L0, T0, R0 = pitch * 0.90, pitch * 0.58, pitch * 0.36
        out = {}
        for code, pt in pts.items():
            sc = 1.0 if (not code or code in self.letters) else 0.6    # безымянные узлы цифрового дерева
            L, T, R = L0 * sc, T0 * sc, R0 * sc
            if not code or code[-1] == ".":
                w = h = 2 * R
            else:
                par = pts[code[:-1]]
                w, h = (T, L) if abs(par.x() - pt.x()) < 1 else (L, T)     # пришли по вертикали / по горизонтали
            lets = []
            if code and code in self.letters:
                lets = [(self.letters[code], 1.0, LET_EXTRA if code in self.extra else MID)]
            out[code] = dict(x=pt.x(), y=pt.y(), w=w, h=h, a=1.0, lets=lets)
        return out, pitch

    def _scene(self):
        """Текущий кадр: (сцена, pitch, прогресс 0..1)."""
        T, pitch = self._target()
        if self._from is not None and self._t0 is not None:
            pr = (time.perf_counter() - self._t0) / self.ANIM_S
            if pr < 1.0:
                return self._blend(self._from, T, max(0.0, pr)), pitch, max(0.0, pr)
        return T, pitch, 1.0

    def _blend(self, F, T, pr):
        """Смешивает старую сцену F и новую T:
        общие узлы плавно едут, новые вырастают из родителя, ушедшие втягиваются в родителя;
        старые символы гаснут в первой половине, новые проявляются во второй."""
        e = _ease(pr)
        fo = _smooth(pr / 0.45)               # старые символы гаснут
        fi = _smooth((pr - 0.45) / 0.55)      # новые символы проявляются
        fa = _smooth(pr * 1.5)                # появление / исчезновение самих узлов
        out = {}

        def anc(code):                        # ближайший уже построенный предок
            code = code[:-1]
            while code and code not in out:
                code = code[:-1]
            return out[code]

        for code in sorted(T, key=len):
            t, f = T[code], F.get(code)
            if f is not None:
                same = ([(c, b) for c, _, b in f["lets"]] == [(c, b) for c, _, b in t["lets"]]
                        and all(al > 0.98 for _, al, _ in f["lets"]))
                lets = t["lets"] if same else (
                    [(c, al * (1 - fo), b) for c, al, b in f["lets"]] + [(c, fi, b) for c, _, b in t["lets"]])
                out[code] = dict(x=_lerp(f["x"], t["x"], e), y=_lerp(f["y"], t["y"], e),
                                 w=_lerp(f["w"], t["w"], e), h=_lerp(f["h"], t["h"], e),
                                 a=_lerp(f["a"], 1.0, e), lets=lets)
            else:
                s = anc(code) if code else t
                out[code] = dict(x=_lerp(s["x"], t["x"], e), y=_lerp(s["y"], t["y"], e),
                                 w=_lerp(t["w"] * 0.3, t["w"], e), h=_lerp(t["h"] * 0.3, t["h"], e),
                                 a=fa, lets=[(c, fi, b) for c, _, b in t["lets"]])
        for code in sorted((c for c in F if c not in T), key=len):
            f = F[code]
            s = anc(code)
            out[code] = dict(x=_lerp(f["x"], s["x"], e), y=_lerp(f["y"], s["y"], e),
                             w=_lerp(f["w"], f["w"] * 0.3, e), h=_lerp(f["h"], f["h"] * 0.3, e),
                             a=f["a"] * (1 - fa), lets=[(c, al * (1 - fo), b) for c, al, b in f["lets"]])
        return out

    def paintEvent(self, ev):
        e = self.engine
        p = QPainter(self)
        p.setRenderHint(AA)
        r = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        bg = QLinearGradient(r.topLeft(), r.bottomLeft())
        bg.setColorAt(0, col(TREE_A))
        bg.setColorAt(1, col(TREE_B))
        p.setBrush(bg)
        p.setPen(QPen(col(BORDER), 1))
        p.drawRoundedRect(r, 24, 24)

        p.setFont(font(11, W_SEMI, 4))
        p.setPen(col(ACC_L, 130))
        p.drawText(QRectF(26, 14, 220, 26), AL_L, "MORSE")
        p.drawText(QRectF(self.width() - 246, 14, 220, 26), AL_R, "CODE")

        scene, pitch, prog = self._scene()

        def glow_of(code):
            if code in self.pos:
                return self.glow.get(code, 0.0)
            return self._ghost.get(code, 0.0) * (1 - prog)      # уходящий узел — свечение затухает

        # рёбра
        for code, n in scene.items():
            if not code:
                continue
            par = scene.get(code[:-1])
            if par is None:
                continue
            a = min(n["a"], par["a"])
            if a < 0.01:
                continue
            pa, pt = QPointF(par["x"], par["y"]), QPointF(n["x"], n["y"])
            t = min(1.0, glow_of(code) * 1.5)
            if t > 0.04:
                pen = QPen(col(ACC, int(95 * t * a)), 8)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.drawLine(pa, pt)
            p.setPen(QPen(with_alpha(mix(EDGE, ACC_L, t), a), 1.8 + t))
            p.drawLine(pa, pt)

        # узлы
        f_let = font(max(9, int(pitch * 0.34)), W_SEMI)
        err = max(0.0, 1.0 - (time.perf_counter() - e.err_t) / 0.45)
        show_let = self.letters_visible()
        for code, n in scene.items():
            a = n["a"]
            if a < 0.01:
                continue
            pt = QPointF(n["x"], n["y"])
            g = glow_of(code)
            hot = self.hot if code == e.flash_code else 0.0
            w, h = max(1.0, n["w"]), max(1.0, n["h"])
            rect = QRectF(pt.x() - w / 2, pt.y() - h / 2, w, h)
            rad = min(w, h) / 2
            if g > 0.02:
                rg = QRadialGradient(pt, pitch * 1.0)
                rg.setColorAt(0.0, col(ACC if not hot else "#E9D5FF", int(150 * min(1, g) * a)))
                rg.setColorAt(0.45, col(ACC, int(55 * min(1, g) * a)))
                rg.setColorAt(1.0, col(ACC, 0))
                p.setPen(NOPEN)
                p.setBrush(rg)
                p.drawEllipse(pt, pitch * 1.0, pitch * 1.0)
            gg = min(1.0, g)
            fill = mix(NODE, "#7C3AED", gg)
            fill = mix(fill, "#E9D5FF", hot)
            if not code and err > 0:
                fill = mix(fill, ERR, err * 0.8)
            fill = with_alpha(fill, a)
            top = fill.lighter(118)
            top.setAlpha(fill.alpha())
            grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            grad.setColorAt(0, top)
            grad.setColorAt(1, fill)
            p.setBrush(grad)
            p.setPen(QPen(with_alpha(mix(NODE_EDGE, ACC_XL, gg), a), 1.4))
            p.drawRoundedRect(rect, rad, rad)
            if code and show_let and n["lets"]:
                p.setFont(f_let)
                lrect = QRectF(pt.x() - 40, pt.y() - 40, 80, 80)
                for ch, la, base in n["lets"]:
                    if la * a < 0.01:
                        continue
                    p.setPen(with_alpha(mix(base, "#FFFFFF", min(1.0, gg * 1.2)), la * a))
                    p.drawText(lrect, AL_C, ch)


# ---------- большая клавиша ----------
class KeyPad(QWidget):
    pressed = Signal()
    released = Signal()

    def __init__(self, engine, st, parent=None):
        super().__init__(parent)
        self.engine, self.st = engine, st
        self.setFixedHeight(128)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.pressed.emit()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.released.emit()

    def paintEvent(self, ev):
        e, st = self.engine, self.st
        p = QPainter(self)
        p.setRenderHint(AA)
        w, h = self.width(), self.height()
        tap = e.tapping() and not e.pressed
        down = e.pressed or tap
        hold = e.hold_ms()
        thr = max(1, st["dot_dash_ms"])
        if tap:
            sym = e.tap_sym
            frac = min(1.0, (time.perf_counter() - e.tap_t0) * 1000.0 / max(1, e.tap_dur))
        else:
            sym = e.cur_sym() if down else ""
            frac = min(1.0, hold / thr) if down else 1.0
        dash = sym == "-"
        r = QRectF(.5, .5, w - 1, h - 1)
        path = QPainterPath()
        path.addRoundedRect(r, 26, 26)
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0, col(KEY_DOWN if down else KEY_A))
        g.setColorAt(1, col(KEY_B))
        p.fillPath(path, QBrush(g))
        if down:
            p.save()
            p.setClipPath(path)
            if dash:
                p.fillRect(QRectF(0, 0, w, h), col(DASH, 58))
            else:
                fg = QLinearGradient(QPointF(0, 0), QPointF(max(1.0, w * frac), 0))
                fg.setColorAt(0, col(ACC, 25))
                fg.setColorAt(1, col(ACC, 120))
                p.fillRect(QRectF(0, 0, w * frac, h), QBrush(fg))
            p.restore()
        p.setBrush(NOBRUSH)
        p.setPen(QPen(col(DASH if dash else ACC_L) if down else col(BORDER), 1.6 if down else 1.0))
        p.drawPath(path)

        glyphs = e.seq + ("" if tap else sym)
        if glyphs:
            D, W, GAP = 14, 46, 10
            tw = sym_width(glyphs, D, W, GAP)
            pulse = 150 + int(90 * (0.5 + 0.5 * math.sin(time.perf_counter() * 12)))
            draw_syms(p, glyphs, w / 2 - tw / 2, h * 0.38, D, W, GAP, 255, pulse if (down and not tap) else None)
            state, ch = e.preview()
            p.setFont(font(15, W_SEMI))
            if down:
                p.setPen(col(DASH if dash else ACC_XL))
                txt = (tr("dash") if dash else tr("dot")) + ("" if tap else f"  ·  {int(hold)} {tr('ms')}")
            elif state == "ok":
                p.setPen(col(ACC_XL))
                txt = f"→  {ch}"
            elif state == "bad":
                p.setPen(col(ERR))
                txt = tr("no_symbol")
            else:
                p.setPen(col(DIM))
                txt = "…"
            p.drawText(QRectF(0, h * 0.60, w, 28), AL_C, txt)
        else:
            p.setFont(font(21, W_SEMI, 6))
            p.setPen(col(TXT))
            p.drawText(QRectF(0, h * 0.16, w, 38), AL_C, KEYS[st["key"]][0].upper())
            p.setFont(font(12, W_NORMAL))
            p.setPen(col(DIM))
            p.drawText(QRectF(0, h * 0.58, w, 24), AL_C, key_hints(st))


# ---------- окно настроек ----------
def dialog_qss():
    return f"""
QDialog {{ background: {BG1}; }}
QScrollArea {{ background: transparent; border: none; }}
QWidget#body {{ background: transparent; }}
QLabel {{ color: {TXT}; font-size: 13px; background: transparent; }}
QLabel#section {{ color: {ACC_L}; font-size: 11px; font-weight: 600; padding-top: 16px; padding-bottom: 2px; }}
QLabel#sub {{ color: {DIM}; font-size: 11px; }}
QLabel#val {{ color: {ACC_XL}; font-size: 12px; font-weight: 600; }}
QSlider::groove:horizontal {{ height: 6px; background: {TRACK}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {ACC_D}, stop:1 {ACC_L}); border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {KNOB}; border: 3px solid {ACC}; width: 12px; height: 12px; margin: -6px 0; border-radius: 9px; }}
QSlider::handle:horizontal:hover {{ border-color: {ACC_XL}; }}
QLabel:disabled, QLabel#sub:disabled, QLabel#val:disabled {{ color: {LBL_OFF}; }}
QSlider::groove:horizontal:disabled {{ background: {TRACK_OFF}; }}
QSlider::sub-page:horizontal:disabled {{ background: {FILL_OFF}; }}
QSlider::handle:horizontal:disabled {{ background: {KNOB_OFF}; border-color: {FILL_OFF}; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: {SB}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {SB_HI}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""


class NoWheelSlider(QSlider):
    """Ползунок, который не реагирует на колёсико (оно прокручивает окно настроек)."""
    def wheelEvent(self, e):
        e.ignore()


class ConfirmDialog(QDialog):
    """Небольшое тёмное окно «Вы уверены?». exec() == Accepted, если нажали подтверждение."""
    def __init__(self, title, text, sub, yes, no, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setStyleSheet(dialog_qss())
        self.setModal(True)
        self.setFixedWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(6)
        head = QLabel(text)
        head.setWordWrap(True)
        head.setStyleSheet("font-size:15px; font-weight:600;")
        lay.addWidget(head)
        if sub:
            s_ = QLabel(sub)
            s_.setObjectName("sub")
            s_.setWordWrap(True)
            lay.addWidget(s_)
        lay.addSpacing(16)
        row = QHBoxLayout()
        b_no = FlatButton(no)
        b_yes = FlatButton(yes, primary=True)
        b_no.clicked.connect(self.reject)
        b_yes.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(b_no)
        row.addSpacing(8)
        row.addWidget(b_yes)
        lay.addLayout(row)

    def showEvent(self, e):
        style_titlebar(self)
        super().showEvent(e)


class SettingsDialog(QDialog):
    def __init__(self, st, tone, on_change, parent=None):
        super().__init__(parent)
        self.st, self.tone, self.on_change = st, tone, on_change
        self.setups, self.rows = [], {}
        self.page = self.scroll = None
        self._theme = st["theme"]
        self.setStyleSheet(dialog_qss())
        self.resize(530, 780)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(0)
        self.build()

    def build(self):
        """Строит содержимое окна (и заново — при смене языка интерфейса)."""
        old, keep = self.page, 0
        if old is not None:
            keep = self.scroll.verticalScrollBar().value()
            self.root.removeWidget(old)
            old.hide()
            old.deleteLater()
        self.setups, self.rows = [], {}
        self.setWindowTitle(tr("set_title"))

        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("body")
        self.vl = QVBoxLayout(body)
        self.vl.setContentsMargins(28, 14, 28, 14)
        self.vl.setSpacing(2)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        self.section(tr("sec_lang"))
        self.lang_row()

        self.section(tr("sec_timing"))
        self.slider(tr("dot_dash"), "dot_dash_ms", 80, 600, 10, tr("ms"), tr("dot_dash_sub"))
        self.slider(tr("letter_gap"), "letter_gap_ms", 250, 2000, 50, tr("ms"), tr("letter_gap_sub"))
        self.toggle(tr("auto_space"), "auto_space", tr("auto_space_sub"))
        self.slider(tr("word_gap"), "word_gap_ms", 600, 5000, 100, tr("ms"), tr("word_gap_sub"))

        self.section(tr("sec_sound"))
        self.toggle(tr("beep"), "sound", tr("beep_sub"))
        self.slider(tr("freq"), "freq", 300, 1400, 20, tr("hz"))
        self.slider(tr("volume"), "volume", 0, 100, 5, "%")
        test = FlatButton(tr("test_sound"))
        test.clicked.connect(self.tone.beep)
        self.rows["test"] = test
        self.vl.addSpacing(6)
        self.vl.addWidget(test, 0, Qt.AlignmentFlag.AlignLeft)

        self.section(tr("sec_input"))
        self.segmented(tr("input_key"), "key", [(k, v[0]) for k, v in KEYS.items()])
        self.segmented(tr("dual_mode"), "dual_map",
                       [("ctrl_dash", tr("dual_a")), ("alt_dash", tr("dual_b"))],
                       tr("dual_sub"))
        self.toggle(tr("upper"), "uppercase", tr("upper_sub"))

        self.section(tr("sec_look"))
        self.segmented(tr("theme"), "theme", [("dark", tr("theme_dark")), ("light", tr("theme_light"))],
                       tr("theme_sub"))
        self.toggle(tr("on_top"), "on_top", tr("on_top_sub"))
        self.vl.addStretch(1)

        foot = QWidget()
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(28, 10, 28, 18)
        b_reset = FlatButton(tr("btn_reset"))
        b_done = FlatButton(tr("btn_done"), primary=True)
        b_reset.clicked.connect(self.confirm_reset)
        b_done.clicked.connect(self.accept)
        fl.addWidget(b_reset)
        fl.addStretch(1)
        fl.addWidget(b_done)
        outer.addWidget(foot)

        self.page, self.scroll = page, scroll
        self.root.addWidget(page, 1)
        page.show()
        self.refresh_enabled()
        if old is not None:
            sb = scroll.verticalScrollBar()
            QTimer.singleShot(0, lambda: sb.setValue(keep))

    def lang_row(self):
        """Язык интерфейса: применяется сразу, окно настроек перестраивается."""
        sg = Segmented([("en", "English"), ("ru", "Русский")], self.st["ui_lang"], h=36)

        def on(v):
            self.st["ui_lang"] = v
            self.changed()                              # -> главное окно переводится
            QTimer.singleShot(0, self.build)            # -> это окно строится заново
        sg.changed.connect(on)
        box = self._box("ui_lang")
        box.addLayout(self._head(tr("ui_lang"), tr("ui_lang_sub"), None))
        box.addWidget(sg, 0, Qt.AlignmentFlag.AlignLeft)

    def showEvent(self, e):
        style_titlebar(self)
        super().showEvent(e)

    # --- строительные блоки ---
    def section(self, title):
        lab = QLabel(title)
        lab.setObjectName("section")
        self.vl.addWidget(lab)

    def _head(self, title, sub, right):
        row = QHBoxLayout()
        col_ = QVBoxLayout()
        col_.setSpacing(1)
        col_.addWidget(QLabel(title))
        if sub:
            s = QLabel(sub)
            s.setObjectName("sub")
            s.setWordWrap(True)
            col_.addWidget(s)
        row.addLayout(col_, 1)
        if right is not None:
            row.addWidget(right, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    def _box(self, name):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.vl.addSpacing(8)
        self.vl.addWidget(w)
        self.rows[name] = w
        return lay

    def refresh_enabled(self):
        """Зависимые параметры серые и некликабельные, но значения сохраняются."""
        st, r = self.st, self.rows
        dual = st["key"] == "ctrlalt"
        r["word_gap_ms"].setEnabled(bool(st["auto_space"]))
        for k in ("freq", "volume", "test"):
            r[k].setEnabled(bool(st["sound"]))
        r["dual_map"].setEnabled(dual)

    def changed(self):
        self.st.save()
        self.refresh_enabled()
        self.on_change(False)                           # главное окно само применит тему
        if self.st["theme"] != self._theme:
            self._theme = self.st["theme"]
            self.retheme()

    def retheme(self):
        """Тема сменилась: перекрашиваем это окно, не перестраивая его (анимации переключателя не рвутся)."""
        self.setStyleSheet(dialog_qss())
        style_titlebar(self)
        for w in self.findChildren(QWidget):
            w.update()

    def slider(self, title, key, lo, hi, step, unit, sub=""):
        val = QLabel()
        val.setObjectName("val")
        sl = NoWheelSlider(Qt.Orientation.Horizontal)
        sl.setRange(lo // step, hi // step)
        sl.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        def show():
            val.setText(f"{self.st[key]} {unit}")

        def moved(v):
            self.st[key] = v * step
            show()
            self.changed()

        def setup():
            sl.blockSignals(True)
            sl.setValue(self.st[key] // step)
            sl.blockSignals(False)
            show()
        sl.valueChanged.connect(moved)
        self.setups.append(setup)
        setup()
        box = self._box(key)
        box.addLayout(self._head(title, sub, val))
        box.addWidget(sl)

    def toggle(self, title, key, sub=""):
        tg = Toggle(self.st[key])

        def on(v):
            self.st[key] = v
            self.changed()
        tg.toggled.connect(on)
        self.setups.append(lambda: tg.set_checked(self.st[key], animate=False))
        self._box(key).addLayout(self._head(title, sub, tg))

    def segmented(self, title, key, items, sub=""):
        sg = Segmented(items, self.st[key], h=36)

        def on(v):
            self.st[key] = v
            self.changed()
        sg.changed.connect(on)
        self.setups.append(lambda: sg.set_value(self.st[key], animate=False))
        box = self._box(key)
        box.addLayout(self._head(title, sub, None))
        box.addWidget(sg, 0, Qt.AlignmentFlag.AlignLeft)

    def confirm_reset(self):
        dlg = ConfirmDialog(tr("confirm_title"), tr("confirm_text"), tr("confirm_sub"),
                            tr("confirm_yes"), tr("confirm_no"), self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.reset()

    def reset(self):
        self.st.reset()
        for s in self.setups:
            s()
        self.changed()


# ---------- игра ----------
GAME_POOLS = {
    ("EN", 0): ["SOS", "HELLO", "WORLD", "MORSE", "CODE", "RADIO", "SIGNAL", "WAVE", "KEY", "DASH", "DOT",
                "PURPLE", "NIGHT", "STAR", "GAME", "LIGHT", "MOON", "SPACE", "TRAIN", "QUICK", "JAZZ", "FOX",
                "BRAVO", "ALPHA", "DELTA", "ZULU", "VICTORY", "PIANO", "GUITAR", "MUSIC"],
    ("EN", 1): ["HELLO WORLD", "SOS SOS SOS", "GOOD MORNING", "THE QUICK BROWN FOX", "MORSE CODE IS FUN",
                "SEE YOU SOON", "HOW ARE YOU", "STAY SAFE", "KEEP IT UP", "I LOVE MUSIC", "LET US PLAY",
                "NICE TO MEET YOU", "THANK YOU", "WELCOME BACK", "HAVE A NICE DAY"],
    ("RU", 0): ["ПРИВЕТ", "МИР", "МОРЗЕ", "КОД", "РАДИО", "СИГНАЛ", "ТОЧКА", "ТИРЕ", "ЗВЕЗДА", "НОЧЬ", "СВЕТ",
                "ЛУНА", "ИГРА", "ГИТАРА", "МУЗЫКА", "ПОБЕДА", "ДРУГ", "ВЕСНА", "ОГОНЬ", "ВОЛНА", "СОЛНЦЕ",
                "РЕКА", "ЛЕТО", "ЗИМА", "МАШИНА", "ПЕСНЯ", "БУКВА", "КЛЮЧ", "ЭХО", "ЮБКА", "ЯБЛОКО", "ШОКОЛАД"],
    ("RU", 1): ["ПРИВЕТ МИР", "ДОБРОЕ УТРО", "КАК ДЕЛА", "ДО ВСТРЕЧИ", "СПАСИБО БОЛЬШОЕ", "АЗБУКА МОРЗЕ",
                "ЭТО ПРОСТО", "ХОРОШЕГО ДНЯ", "Я ТЕБЯ ЛЮБЛЮ", "ЖИЗНЬ ПРЕКРАСНА", "МИР ТРУД МАЙ",
                "ТИШЕ ЕДЕШЬ ДАЛЬШЕ БУДЕШЬ"],
    ("NUM", 0): ["7", "42", "112", "911", "2026", "314", "100", "58", "365", "1999"],
    ("NUM", 1): ["3141592", "1234567890", "8005553535", "20260101", "987654321", "1000000", "24601", "5551234"],
    ("SYM", 0): ["?", "!", "?!", "...", ".,", "()", "+=", "@", "&", "_", "-", ":;", "/", "!!!", "???"],
    ("SYM", 1): ["1+1=2", "(2-1)", "!?!?", "3/4=.75", "12:30", "5-2=3", "@1_2", "(+)", '"5"', "9-5=4", "7&3"],
}
GAME_POOLS[("ALL_EN", 0)] = GAME_POOLS[("EN", 0)] + [
    "R2D2", "C3PO", "B52", "F16", "K9", "4K", "3D", "Q&A", "R&D", "WI-FI", "E-MAIL", "7UP", "A1", "H2O", "CO2"]
GAME_POOLS[("ALL_EN", 1)] = GAME_POOLS[("EN", 1)] + [
    "CALL 911", "ROOM 101", "AGENT 007", "DON'T PANIC!", "WHAT'S UP?", "1+1=2", "DIAL 112", "R2-D2",
    "AT 8:30 SHARP", "HELLO, WORLD!", "PAGE 3/4", "SOS 112"]
GAME_POOLS[("ALL_RU", 0)] = GAME_POOLS[("RU", 0)] + [
    "Т-34", "Ф-16", "3Д", "4К", "1С", "Н2О", "СО2", "ТОП-10", "АК-47", "МИР-2"]
GAME_POOLS[("ALL_RU", 1)] = GAME_POOLS[("RU", 1)] + [
    "ЗВОНИ 112", "КОМНАТА 101", "ПРИВЕТ, МИР!", "КАК ДЕЛА?", "ЧТО? ГДЕ? КОГДА?", "2+2=4", "ДОМ 12/3",
    "В 8:30 У ВОКЗАЛА", "ДА, ЭТО Я!"]


class GameBar(QWidget):
    exit_requested = Signal()

    def __init__(self, engine, tree, parent=None):
        super().__init__(parent)
        self.engine, self.tree = engine, tree
        self.active, self.hints, self.cat = False, True, 0
        self.target, self.score, self.miss = "", 0, 0
        self.ok_until = self.bad_until = 0.0
        self.busy = self.guard = self._was_flash = False
        self.setFixedHeight(124)
        self.seg_a = Segmented([("0", tr("g_words")), ("1", tr("g_phrases"))], "0", h=32, pad=18, parent=self)
        self.seg_b = Segmented([("0", tr("g_short")), ("1", tr("g_long"))], "0", h=32, pad=18, parent=self)
        self.b_hint = FlatButton(tr("g_hints_on"), parent=self)
        self.b_hint.active = True
        self.b_skip = FlatButton(tr("g_skip"), parent=self)
        self.b_exit = FlatButton(tr("g_exit"), parent=self)
        self.seg_a.changed.connect(self._cat)
        self.seg_b.changed.connect(self._cat)
        self.b_hint.clicked.connect(self.toggle_hints)
        self.b_skip.clicked.connect(self.new_target)
        self.b_exit.clicked.connect(self.exit_requested.emit)
        self.hide()

    def resizeEvent(self, e):
        self.place()

    def retranslate(self):
        self.seg_a.set_items([("0", tr("g_words")), ("1", tr("g_phrases"))])
        self.seg_b.set_items([("0", tr("g_short")), ("1", tr("g_long"))])
        self.b_hint.setText(tr("g_hints_on") if self.hints else tr("g_hints_off"))
        self.b_skip.setText(tr("g_skip"))
        self.b_exit.setText(tr("g_exit"))
        self.place()
        self.update()

    def place(self):
        w, y = self.width(), 80
        a = self.engine.lang in ("EN", "RU", "ALL_EN", "ALL_RU")
        self.seg_a.setVisible(a)
        self.seg_b.setVisible(not a)
        seg = self.seg_a if a else self.seg_b
        seg.move(22, y)
        self.b_hint.move(22 + seg.width() + 10, y)
        self.b_exit.move(w - 22 - self.b_exit.width(), y)
        self.b_skip.move(self.b_exit.x() - 8 - self.b_skip.width(), y)

    def _cat(self, key):
        self.cat = int(key)
        self.new_target()
        self.window().setFocus()

    def toggle_hints(self):
        self.hints = not self.hints
        self.b_hint.active = self.hints
        self.b_hint.setText(tr("g_hints_on") if self.hints else tr("g_hints_off"))
        self.place()
        self.tree.override_letters = self.hints
        self.tree.update()
        self.window().setFocus()

    def start(self):
        self.active = True
        self.score = self.miss = 0
        self.hints = False
        self.toggle_hints()                  # -> включит подсказки и обновит дерево
        self.show()
        self.place()
        self.new_target()

    def stop(self):
        self.active = False
        self.hide()
        self.tree.override_letters = None
        self.tree.update()

    def lang_changed(self):
        if self.active:
            self.place()
            self.new_target()

    def new_target(self):
        pool = GAME_POOLS[(self.engine.lang, self.cat)]
        self.target = random.choice([t for t in pool if t != self.target] or pool)
        self.busy = False
        self.engine.clear_all()
        self.update()
        self.window().setFocus()

    def on_change(self):
        if not self.active or self.busy or self.guard:
            return
        e, now = self.engine, time.perf_counter()
        typed, tgt = e.text_str().upper(), self.target.upper()
        if typed and typed == tgt:
            self.busy = True
            self.score += 1
            self.ok_until = now + 0.9
            QTimer.singleShot(900, self.new_target)
        elif not tgt.startswith(typed):
            self.miss += 1
            self.bad_until = now + 0.45
            e.err_t = now
            self.guard = True
            while e.items and not tgt.startswith(e.text_str().upper()):
                e.items.pop()
            e.changed.emit()
            self.guard = False
        self.update()

    def tick(self):
        now = time.perf_counter()
        flash = now < self.ok_until or now < self.bad_until
        if flash or self._was_flash:
            self.update()
        self._was_flash = flash

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(AA)
        w, h = self.width(), self.height()
        now = time.perf_counter()
        ok, bad = now < self.ok_until, now < self.bad_until
        r = QRectF(.5, .5, w - 1, h - 1)
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0, col(KEY_A))
        g.setColorAt(1, col(KEY_B))
        p.setBrush(g)
        p.setPen(QPen(col(GREEN if ok else (ERR if bad else BORDER_HI), 255 if (ok or bad) else 150), 1.4))
        p.drawRoundedRect(r, 22, 22)
        pad = 24
        p.setFont(font(10, W_SEMI, 2.5))
        p.setPen(col(ACC_L, 170))
        p.drawText(QPointF(pad, 28), tr("g_title"))
        p.setFont(font(12, W_MED))
        p.setPen(col(DIM))
        p.drawText(QRectF(w - 300 - pad, 12, 300, 22), AL_R, tr("g_score", a=self.score, b=self.miss))

        size = 30
        while size > 16 and QFontMetricsF(font(size, W_SEMI, 1.5)).horizontalAdvance(self.target) > w - 2 * pad:
            size -= 2
        f = font(size, W_SEMI, 1.5)
        fm = QFontMetricsF(f)
        n = len(self.target) if self.busy else len(self.engine.text_str())
        x = (w - fm.horizontalAdvance(self.target)) / 2
        y = 66
        p.setFont(f)
        for i, ch in enumerate(self.target):
            adv = fm.horizontalAdvance(ch)
            if i < n:
                c = col(GREEN if ok else ACC_XL)
            elif i == n:
                c = col(MID)
            else:
                c = col(FAINT)
            p.setPen(c)
            p.drawText(QPointF(x, y), ch)
            if i == n and not self.busy:
                p.setPen(NOPEN)
                p.setBrush(col(ACC))
                p.drawRoundedRect(QRectF(x, y + 7, max(adv, 8), 2.5), 1.2, 1.2)
            x += adv


# ---------- пасхалка ----------
class EggTyper(QObject):
    """Сама «выстукивает» 727 так же, как это делали бы руками: нажимает и отпускает клавишу ввода
    (звук, подсветка, дерево — всё как при обычном вводе). Темп задаёт порог «точка / тире»:
    точка = 1/3 порога, тире = порог (с запасом), пауза между знаками = точка."""
    CODES = ("--...", "..---", "--...")             # 7 2 7
    OWNER = "egg"

    def __init__(self, engine, st):
        super().__init__()
        self.engine, self.st = engine, st
        self.steps, self.running, self._fn = [], False, None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._fire)

    def _build(self):
        """Список шагов [(пауза_перед_мс, действие)]."""
        st, e = self.st, self.engine
        thr = int(st["dot_dash_ms"])
        u = max(50, thr // 3)                       # «единица» времени = длина точки
        dual = st["key"] == "ctrlalt"
        # паузы подрезаем, чтобы авто-конец буквы и авто-пробел не сработали раньше нас
        lg = int(st["letter_gap_ms"])
        to_commit = min(3 * u, max(80, lg - 60))
        after = 3 * u
        if st["auto_space"]:
            after = min(after, max(80, max(150, int(st["word_gap_ms"]) - lg) - 60))
        steps, wait = [], 300                       # короткая пауза перед первым нажатием
        for code in self.CODES:
            for sym in code:
                if dual:                            # Ctrl + Alt: длину звука задаёт сам движок
                    steps.append((wait, lambda s=sym: e.tap(s)))
                    wait = (thr if sym == "-" else u) + u
                else:                               # одна клавиша: держим столько, сколько нужно для точки / тире
                    steps.append((wait, lambda: e.press(owner=self.OWNER)))
                    steps.append((int(thr * 1.2) if sym == "-" else u, lambda: e.release(owner=self.OWNER)))
                    wait = u
            steps.append((wait - u + to_commit, self._commit))
            wait = after
        return steps

    def _commit(self):
        if self.engine.seq:
            self.engine.space_press()               # как нажатие Пробела: буква применяется

    def start(self):
        if self.running:
            return
        self.steps, self.running = self._build(), True
        self._schedule()

    def _schedule(self):
        if not self.steps:
            self.running = False
            return
        delay, self._fn = self.steps.pop(0)
        self.timer.start(delay)

    def _fire(self):
        fn, self._fn = self._fn, None
        if fn:
            fn()
        self._schedule()

    def cancel(self):
        if not self.running:
            return
        self.timer.stop()
        self.steps, self.running, self._fn = [], False, None
        self.engine.abort()


# ---------- главное окно ----------
class MainWindow(QWidget):
    GAME_EXTRA = 138
    BTN_W, BTN_GAP = 32, 3                          # кнопки справа от переключателя деревьев

    def __init__(self):
        super().__init__()
        self.st = Settings()
        set_ui_lang(self.st["ui_lang"])
        self._ui = self.st["ui_lang"]
        apply_theme(self.st["theme"])
        self._theme = self.st["theme"]
        self.tone = Tone()
        self.engine = Engine(self.st, self.tone)
        self.egg = EggTyper(self.engine, self.st)
        self.setWindowTitle("PhMorse")
        self._letters = self.st["lang"] if self.st["lang"] in ("EN", "RU") else "EN"
        self.min_h = 730
        self.setMinimumSize(580, self.min_h)
        avail = QGuiApplication.primaryScreen().availableGeometry().height()
        self.resize(600, max(self.min_h, min(900, avail - 60)))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._titled, self._grew = False, 0

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(14)
        head = QHBoxLayout()
        head.setSpacing(0)                          # расстояния между кнопками задаём вручную
        self.brand = Brand()
        head.addWidget(self.brand, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addStretch(1)
        self.lang = Segmented([("EN", "ENG"), ("RU", "RUS"), ("NUM", "123"), ("SYM", "!@#")],
                              self.st["lang"], pad=18, drag=True)
        head.addWidget(self.lang, 0, Qt.AlignmentFlag.AlignVCenter)
        self.lang.set_disabled(("NUM", "SYM") if self.st["combo"] else ())
        self.lang._fade_step(1.0)
        head.addSpacing(8)
        self.btn_combo = FlatButton(icon=icon_combo, width=self.BTN_W)
        self.btn_combo.setToolTip(tr("tip_combo"))
        self.btn_combo.active = bool(self.st["combo"])
        head.addWidget(self.btn_combo, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addSpacing(self.BTN_GAP)
        self.btn_letters = FlatButton(icon=icon_eye, width=self.BTN_W)
        self.btn_letters.setToolTip(tr("tip_letters"))
        head.addWidget(self.btn_letters, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addSpacing(self.BTN_GAP)
        self.btn_game = FlatButton(icon=icon_gamepad, width=self.BTN_W)
        self.btn_game.setToolTip(tr("tip_game"))
        head.addWidget(self.btn_game, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addSpacing(self.BTN_GAP)
        self.gear = FlatButton(icon=icon_sliders, width=self.BTN_W)
        self.gear.setToolTip(tr("tip_settings"))
        head.addWidget(self.gear, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(head)

        self.card = OutputCard(self.engine)
        self.tree = TreeView(self.engine, self.st)
        self.pad = KeyPad(self.engine, self.st)
        self.game = GameBar(self.engine, self.tree)
        root.addWidget(self.game)
        root.addWidget(self.card)
        root.addWidget(self.tree, 1)
        root.addWidget(self.pad)
        self.hint = QLabel()
        self.hint.setAlignment(AL_C)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(hint_qss())
        root.addWidget(self.hint)

        self.lang.changed.connect(self.set_lang)
        self.gear.clicked.connect(self.open_settings)
        self.btn_game.clicked.connect(self.toggle_game)
        self.btn_combo.clicked.connect(self.toggle_combo)
        self.btn_letters.clicked.connect(self.toggle_letters)
        self.brand.egg.connect(self._egg)
        self.game.exit_requested.connect(self.toggle_game)
        self.pad.pressed.connect(self._pad_press)
        self.pad.released.connect(self.engine.release)
        self.engine.changed.connect(self._refresh)

        self.tick = QTimer(self)
        self.tick.setInterval(16)
        self.tick.timeout.connect(self._tick)
        self.tick.start()
        self.apply_settings(True)

    # --- обновление ---
    def _refresh(self):
        self.card.update()
        self.pad.update()
        self.tree.update()
        self.game.on_change()

    def _tick(self):
        self.tree.tick()
        if self.engine.pressed or self.engine.tapping():
            self.pad.update()
        if self.game.active:
            self.game.tick()

    def _pad_press(self):
        if not self.egg.running:                    # пока пасхалка «печатает», ввод мышью не мешает
            self.engine.press()

    def _egg(self):
        if self.game.active or self.egg.running:
            return
        self.engine.abort()
        self.engine.cancel()                        # недонабранную букву сбрасываем, готовый текст остаётся
        self.egg.start()
        self.setFocus()

    def retheme(self):
        """Тема сменилась: перекрашиваем главное окно."""
        self.hint.setStyleSheet(hint_qss())
        style_titlebar(self)
        self.update()
        for w in self.findChildren(QWidget):
            w.update()

    def _sync_letters(self):
        on = bool(self.st["show_letters"])
        self.btn_letters.active = on
        self.btn_letters.icon = icon_eye if on else icon_eye_off
        self.btn_letters.update()
        self.tree.update()

    def toggle_letters(self):
        self.st["show_letters"] = not self.st["show_letters"]
        self.st.save()
        self._sync_letters()
        self.setFocus()

    def retranslate(self):
        self.btn_game.setToolTip(tr("tip_game"))
        self.btn_combo.setToolTip(tr("tip_combo"))
        self.btn_letters.setToolTip(tr("tip_letters"))
        self.gear.setToolTip(tr("tip_settings"))
        self.card.retranslate()
        self.game.retranslate()
        self.brand.update()

    def set_lang(self, lang):
        self.st["lang"] = lang
        if lang in ("EN", "RU"):
            self._letters = lang
        self.st.save()
        self._apply_tree()

    def _apply_tree(self):
        self.egg.cancel()
        key = eff_lang(self.st)
        self.engine.set_lang(key)
        self.tree.set_lang(key)
        self.game.lang_changed()
        self.setFocus()

    def toggle_combo(self):
        """Буквы + цифры + символы в одном дереве; в этом режиме меняется только язык букв."""
        self.engine.abort()
        on = not self.st["combo"]
        self.st["combo"] = on
        if on and self.st["lang"] not in ("EN", "RU"):
            self.st["lang"] = self._letters
            self.lang.set_value(self._letters)
        self.lang.set_disabled(("NUM", "SYM") if on else ())
        self.btn_combo.active = on
        self.btn_combo.update()
        self.st.save()
        self._apply_tree()

    def toggle_game(self):
        self.egg.cancel()
        self.engine.abort()
        if self.game.active:
            self.game.stop()
            self.btn_game.active = False
            self.btn_letters.setEnabled(True)
            self.setMinimumHeight(self.min_h)
            if self._grew:
                self.resize(self.width(), self.height() - self._grew)
                self._grew = 0
        else:
            self.engine.clear_all()
            need = self.min_h + self.GAME_EXTRA
            self.setMinimumHeight(need)
            self._grew = max(0, need - self.height())
            if self._grew:
                self.resize(self.width(), self.height() + self._grew)
            self.game.start()
            self.btn_game.active = True
            self.btn_letters.setEnabled(False)      # в игре буквами управляет её кнопка подсказок
        self.btn_game.update()
        self.setFocus()

    def apply_settings(self, with_flags):
        st = self.st
        if st["theme"] != self._theme:
            self._theme = st["theme"]
            apply_theme(self._theme)
            self.retheme()
        set_ui_lang(st["ui_lang"])
        if st["ui_lang"] != self._ui:
            self._ui = st["ui_lang"]
            self.retranslate()
        self.tone.configure(st["freq"], st["volume"], st["sound"])
        first = key_hints(st) if st["key"] == "ctrlalt" else tr("hint_key", key=KEYS[st["key"]][0])
        first += tr("hint_space")
        self.hint.setText(first + "\n" + tr("hint_keys2"))
        if with_flags:
            want = bool(st["on_top"])
            if bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) != want:
                self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, want)
                self.show()
        self._sync_letters()
        self._refresh()

    def open_settings(self):
        self.egg.cancel()
        self.engine.abort()
        dlg = SettingsDialog(self.st, self.tone, self.apply_settings, self)
        dlg.exec()
        self.st.save()
        self.apply_settings(True)
        self.activateWindow()
        self.setFocus()

    # --- события ---
    def showEvent(self, e):
        if not self._titled:
            self._titled = True
            scr = self.screen() or QGuiApplication.primaryScreen()
            fg = self.frameGeometry()
            fg.moveCenter(scr.availableGeometry().center())
            self.move(fg.topLeft())
            style_titlebar(self)
        super().showEvent(e)
        self.setFocus()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(AA)
        w, h = self.width(), self.height()
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, col(WIN_TOP))
        g.setColorAt(1, col(BG0))
        p.fillRect(self.rect(), QBrush(g))
        for cx, cy, rad, a in ((w * 0.88, -30, 460, GLOW1), (w * 0.05, h * 1.02, 420, GLOW2)):
            rg = QRadialGradient(QPointF(cx, cy), rad)
            rg.setColorAt(0, col(ACC, a))
            rg.setColorAt(1, col(ACC, 0))
            p.fillRect(self.rect(), QBrush(rg))

    def keyPressEvent(self, e):
        if e.isAutoRepeat():
            return
        k, st = int(e.key()), self.st
        mode = st["key"]
        if self.egg.running:                        # пасхалка печатает: ввод блокируем, Esc — прервать
            if k == int(Qt.Key.Key_Escape):
                self.egg.cancel()
            e.accept()
            return
        if mode == "ctrlalt" and k in (K_CTRL, K_ALT):
            dash_key = K_CTRL if st["dual_map"] == "ctrl_dash" else K_ALT
            self.engine.tap("-" if k == dash_key else ".")
            e.accept()
        elif mode != "ctrlalt" and k in KEYS[mode][1]:
            self.engine.press()
            e.accept()
        elif k == K_SPACE:
            self.engine.space_press()
        elif k == int(Qt.Key.Key_Backspace):
            self.engine.backspace()
        elif k == int(Qt.Key.Key_Escape):
            self.engine.esc()
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.isAutoRepeat():
            return
        k, mode = int(e.key()), self.st["key"]
        if self.egg.running:
            e.accept()
            return
        if mode == "ctrlalt" and k in (K_CTRL, K_ALT):
            e.accept()                      # длительность нажатия в этом режиме не важна
        elif mode != "ctrlalt" and k in KEYS[mode][1]:
            self.engine.release()
            e.accept()
        else:
            super().keyReleaseEvent(e)

    def changeEvent(self, e):
        if e.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            self.egg.cancel()
            self.engine.abort()
        super().changeEvent(e)

    def closeEvent(self, e):
        self.egg.cancel()
        self.tone.stop()
        self.st.save()
        super().closeEvent(e)


LAYOUTS = {name: make_layout(name) for name in LANGS}


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MorseKeyboard.App")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    ic = app_icon()
    if not ic.isNull():
        app.setWindowIcon(ic)
    app.setFont(font(13))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
