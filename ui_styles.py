# -*- coding: utf-8 -*-
"""
Глобальная тема оформления: детский Flat Design на базе QSS.

Палитра -- пастельные тона (мятный, нежно-голубой, мягкий жёлтый, коралловый).
Шрифт задаётся крупным и хорошо читаемым, кнопки -- большие и понятные.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication


# ---------------------------------------------------------------------------
#  Палитра
# ---------------------------------------------------------------------------
class Palette:
    """Централизованный набор цветов приложения."""
    # Фоны
    BG_MINT = "#B8E6D9"          # мятный (основной фон)
    BG_BLUE = "#BFE3F2"          # нежно-голубой
    BG_YELLOW = "#FDF2C4"        # мягкий жёлтый
    BG_CORAL = "#FFD3C4"         # коралловый
    BG_CARD = "#FFFFFF"          # карточки

    # Акценты
    MINT = "#4FB286"
    BLUE = "#5BA8D6"
    YELLOW = "#F2C94C"
    CORAL = "#FF8A7A"
    PINK = "#F49AC2"
    PURPLE = "#B19CD9"

    # Текст
    TEXT_DARK = "#2D3A4B"
    TEXT_MUTED = "#6B7A8F"
    TEXT_LIGHT = "#FFFFFF"

    # Семантика
    SUCCESS = "#4FB286"
    ERROR = "#FF6B6B"
    GRADE_HIGH = "#E74C3C"       # красный для 4 и 5
    GRADE_MID = "#3498DB"        # синий для 3
    GRADE_LOW = "#3D4A5C"        # тёмно-серый для 1 и 2


# ---------------------------------------------------------------------------
#  Глобальная QSS-тема
# ---------------------------------------------------------------------------
QSS = f"""
* {{
    font-family: 'Comic Sans MS', 'Trebuchet MS', 'Segoe UI', 'DejaVu Sans', sans-serif;
}}

QWidget#CentralWidget {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {Palette.BG_MINT}, stop:0.5 {Palette.BG_BLUE}, stop:1 {Palette.BG_YELLOW});
}}

QLabel {{
    color: {Palette.TEXT_DARK};
    background: transparent;
}}
QLabel#TitleLabel {{
    color: {Palette.MINT};
    font-size: 38px;
    font-weight: 800;
    padding: 8px;
}}
QLabel#SubtitleLabel {{
    color: {Palette.TEXT_MUTED};
    font-size: 18px;
    font-weight: 600;
}}
QLabel#ProblemLabel {{
    color: {Palette.TEXT_DARK};
    font-size: 56px;
    font-weight: 800;
    padding: 10px;
}}
QLabel#CorrectAnswerLabel {{
    color: {Palette.TEXT_MUTED};
    font-size: 26px;
    font-weight: 700;
    padding: 4px;
}}
QLabel#BigFeedbackLabel {{
    font-size: 72px;
    font-weight: 900;
}}
QLabel#HintLabel {{
    color: {Palette.TEXT_MUTED};
    font-size: 14px;
    font-style: italic;
}}

/* Кнопки */
QPushButton {{
    background-color: {Palette.CORAL};
    color: white;
    border: none;
    border-radius: 22px;
    padding: 14px 28px;
    font-size: 20px;
    font-weight: 800;
    min-height: 24px;
}}
QPushButton:hover {{
    background-color: {Palette.PINK};
}}
QPushButton:pressed {{
    background-color: {Palette.YELLOW};
    padding-top: 16px;
    padding-bottom: 12px;
}}
QPushButton:disabled {{
    background-color: #C8D0D8;
    color: #FFFFFF;
}}
QPushButton#PrimaryButton {{
    background-color: {Palette.MINT};
    font-size: 24px;
    padding: 18px 40px;
}}
QPushButton#PrimaryButton:hover {{
    background-color: #3FA070;
}}
QPushButton#SecondaryButton {{
    background-color: {Palette.BLUE};
}}
QPushButton#SecondaryButton:hover {{
    background-color: #4A92B8;
}}
QPushButton#NextButton {{
    background-color: {Palette.YELLOW};
    color: {Palette.TEXT_DARK};
}}
QPushButton#NextButton:hover {{
    background-color: #E5B938;
}}
QPushButton#DangerButton {{
    background-color: {Palette.ERROR};
}}

/* Карточки */
QFrame#Card {{
    background-color: {Palette.BG_CARD};
    border-radius: 24px;
}}
QFrame#ProblemCard {{
    background-color: {Palette.BG_CARD};
    border-radius: 30px;
    border: 3px solid {Palette.BG_CORAL};
}}

/* Поля ввода */
QLineEdit {{
    background-color: white;
    border: 3px solid {Palette.BLUE};
    border-radius: 16px;
    padding: 12px 18px;
    font-size: 22px;
    color: {Palette.TEXT_DARK};
    selection-background-color: {Palette.YELLOW};
}}
QLineEdit:focus {{
    border: 3px solid {Palette.CORAL};
}}
QSpinBox, QComboBox {{
    background-color: white;
    border: 3px solid {Palette.BLUE};
    border-radius: 16px;
    padding: 10px 16px;
    font-size: 20px;
    color: {Palette.TEXT_DARK};
    min-height: 28px;
}}
QComboBox:focus {{
    border: 3px solid {Palette.CORAL};
}}
QComboBox::drop-down {{
    border: none;
    width: 36px;
}}
QComboBox QAbstractItemView {{
    background-color: white;
    border: 2px solid {Palette.BLUE};
    border-radius: 12px;
    selection-background-color: {Palette.BG_MINT};
    selection-color: {Palette.TEXT_DARK};
    font-size: 18px;
    padding: 6px;
    outline: none;
}}
QComboBox:editable {{
    background-color: white;
}}
QComboBox QLineEdit {{
    border: none;
    background: transparent;
    padding: 4px 8px;
    font-size: 22px;
    color: {Palette.TEXT_DARK};
}}

/* Радиокнопки выбора персонажа */
QRadioButton {{
    font-size: 18px;
    font-weight: 700;
    color: {Palette.TEXT_DARK};
    spacing: 8px;
    background: transparent;
}}
QRadioButton::indicator {{
    width: 22px;
    height: 22px;
    border-radius: 11px;
    border: 3px solid {Palette.BLUE};
    background: white;
}}
QRadioButton::indicator:checked {{
    background: {Palette.CORAL};
    border: 3px solid {Palette.CORAL};
}}

/* Области прокрутки -- прозрачные, без рамок (защита от искажений) */
QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}

/* Группы: рамки заметные -- насыщенный коралл толщиной 3px */
QGroupBox {{
    background-color: rgba(255, 255, 255, 225);
    border: 3px solid {Palette.CORAL};
    border-radius: 18px;
    margin-top: 18px;
    padding: 16px;
    font-size: 18px;
    font-weight: 700;
    color: {Palette.TEXT_DARK};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 20px;
    padding: 0 8px;
}}

/* Диалоги статистики */
QDialog {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {Palette.BG_MINT}, stop:1 {Palette.BG_BLUE});
}}
QTableWidget {{
    background-color: white;
    border: 2px solid {Palette.BG_CORAL};
    border-radius: 16px;
    gridline-color: {Palette.BG_MINT};
    font-size: 16px;
    color: {Palette.TEXT_DARK};
}}
QHeaderView::section {{
    background-color: {Palette.BG_MINT};
    color: {Palette.TEXT_DARK};
    font-weight: 800;
    font-size: 16px;
    padding: 8px;
    border: none;
}}
QTextBrowser, QTextEdit {{
    background-color: rgba(255,255,255,220);
    border: 2px solid {Palette.BG_CORAL};
    border-radius: 16px;
    font-size: 16px;
    color: {Palette.TEXT_DARK};
    padding: 8px;
}}

/* Полосы прокрутки -- мягкие, без резких граней */
QScrollBar:vertical {{
    background: transparent;
    width: 14px;
    margin: 4px;
}}
QScrollBar::handle:vertical {{
    background: {Palette.BG_CORAL};
    border-radius: 6px;
    min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""


def apply_theme(app: QApplication) -> None:
    """Применяет QSS-тему и базовый шрифт к приложению."""
    app.setStyleSheet(QSS)
    font = QFont("Comic Sans MS", 12)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)
    # Светлая палитра для согласованного вида системных виджетов.
    pal = app.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor(Palette.BG_MINT))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(Palette.TEXT_DARK))
    pal.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.Text, QColor(Palette.TEXT_DARK))
    app.setPalette(pal)
