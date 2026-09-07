# -*- coding: utf-8 -*-
"""
Персонажи-помощники, нарисованные кодом через QPainter.

Стиль -- анимационный (Disney/Pixar): мягкие градиенты, объёмные блики,
большие глянцевые глаза с двумя highlight-точками, плавные покачивания.

Два героя (рисуются по референсным изображениям заказчика):
    * фея "Динь" -- девочка-фейка с большими светлыми волосами, зелёным
      платьем из лепестков и полупрозрачными крыльями;
    * "Боевой Прайм" -- боевой робот: синий шлем с гребнем, красный торс
      со светящимся ядром, серебряные руки и пушка на руке.

Отрисовка вынесена в функции draw_fairy/draw_prime: их использует и
QPainter-виджет (анимация на CPU), и GPU-рендер gl_characters.py
(текстура для ModernGL). Все движения задаёт параметр t (время, сек).
"""
from __future__ import annotations

import math
import types

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import (QBrush, QColor, QLinearGradient, QPainter,
                            QPainterPath, QPen, QRadialGradient)
from PySide6.QtWidgets import QWidget

# Все фигуры рисуются в нормализованных координатах 240x240 и масштабируются
# под фактический размер виджета/текстуры.
_CANVAS = 240.0


# ---------------------------------------------------------------------------
#  Палитры персонажей
# ---------------------------------------------------------------------------
FAIRY = types.SimpleNamespace(
    SKIN=QColor("#FFE3C2"), SKIN_DARK=QColor("#F3C79E"),
    HAIR=QColor("#F5C842"), HAIR_DARK=QColor("#D89B23"),
    DRESS_LIGHT=QColor("#B7DD8B"), DRESS=QColor("#8BC34A"),
    DRESS_DARK=QColor("#6FA838"), IRIS=QColor("#3E9B4F"),
)

PRIME = types.SimpleNamespace(
    BLUE=QColor("#2B5FD9"), BLUE_DARK=QColor("#1E46B0"),
    BLUE_LIGHT=QColor("#4A7AEE"), RED=QColor("#E0393B"),
    RED_DARK=QColor("#C22628"), RED_LIGHT=QColor("#F05050"),
    SILVER=QColor("#DCE1E8"), SILVER_DARK=QColor("#AEB6C4"),
    STEEL=QColor("#8B94A3"),
)


# ---------------------------------------------------------------------------
#  Общие помощники рисования
# ---------------------------------------------------------------------------
def _lerp_color(c1: QColor, c2: QColor, t: float) -> QColor:
    """Линейная интерполяция двух цветов (для мягких переходов)."""
    r = int(c1.red() + (c2.red() - c1.red()) * t)
    g = int(c1.green() + (c2.green() - c1.green()) * t)
    b = int(c1.blue() + (c2.blue() - c1.blue()) * t)
    return QColor(r, g, b)


def draw_glossy_eye(p: QPainter, cx: float, cy: float, rx: float, ry: float,
                    iris: QColor, blink: bool, look: float = 0.0) -> None:
    """Большой глянцевый глаз в стиле Pixar (две точки-блика)."""
    if blink:
        p.setPen(QPen(QColor("#8A6A48"), 2.5, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(int(cx - rx), int(cy - ry * 0.4), int(rx * 2), int(ry * 0.9),
                  20 * 16, 140 * 16)
        return
    sclera = QRadialGradient(cx, cy - ry * 0.25, rx * 1.6)
    sclera.setColorAt(0.0, QColor("#FFFFFF"))
    sclera.setColorAt(1.0, QColor("#E8EDF2"))
    p.setBrush(QBrush(sclera))
    p.setPen(QPen(QColor("#B9C4CC"), 1.5))
    p.drawEllipse(int(cx - rx), int(cy - ry), int(rx * 2), int(ry * 2))
    ix = cx + look * rx * 0.35
    iris_grad = QRadialGradient(ix, cy - ry * 0.2, rx * 1.1)
    iris_grad.setColorAt(0.0, _lerp_color(iris, QColor("#FFFFFF"), 0.45))
    iris_grad.setColorAt(0.75, iris)
    iris_grad.setColorAt(1.0, _lerp_color(iris, QColor("#000000"), 0.45))
    p.setBrush(QBrush(iris_grad))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(int(ix - rx * 0.62), int(cy - ry * 0.62),
                  int(rx * 1.24), int(ry * 1.24))
    p.setBrush(QColor("#1E1E28"))
    p.drawEllipse(int(ix - rx * 0.3), int(cy - ry * 0.3),
                  int(rx * 0.6), int(ry * 0.6))
    p.setBrush(QColor(255, 255, 255, 235))
    p.drawEllipse(int(ix - rx * 0.38), int(cy - ry * 0.62),
                  int(rx * 0.42), int(ry * 0.42))
    p.drawEllipse(int(ix + rx * 0.12), int(cy + ry * 0.18),
                  int(rx * 0.2), int(ry * 0.2))


def draw_robot_eye(p: QPainter, cx: float, cy: float, w: float, h: float,
                   intensity: float) -> None:
    """Светящийся глаз робота (циановое свечение с яркостью 0..1)."""
    p.setBrush(QColor("#232B36"))
    p.setPen(QPen(QColor("#141A22"), 1.5))
    p.drawRoundedRect(int(cx - w / 2), int(cy - h / 2), int(w), int(h), 4, 4)
    glow = QRadialGradient(cx, cy, w)
    glow.setColorAt(0.0, QColor(210, 250, 255, int(255 * intensity)))
    glow.setColorAt(0.45, QColor(90, 220, 250, int(230 * intensity)))
    glow.setColorAt(1.0, QColor(40, 150, 220, 0))
    p.setBrush(QBrush(glow))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(int(cx - w / 2), int(cy - h / 2), int(w), int(h))
    core = QColor(235, 253, 255)
    core.setAlpha(int(235 * intensity))
    p.setBrush(core)
    p.drawEllipse(int(cx - w * 0.18), int(cy - h * 0.22),
                  int(w * 0.36), int(h * 0.44))


def _draw_soft_shadow(p: QPainter, cx: float, cy: float, rx: float,
                      squish: float = 0.16) -> None:
    """Мягкая тень-эллипс под персонажем."""
    grad = QRadialGradient(cx, cy, rx)
    grad.setColorAt(0.0, QColor(60, 60, 90, 70))
    grad.setColorAt(1.0, QColor(60, 60, 90, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(grad))
    p.drawEllipse(int(cx - rx), int(cy - rx * squish),
                  int(rx * 2), int(rx * squish * 2))


def _petal_hem(p: QPainter, cx: float, y: float, half_w: float, depth: float,
               petals: int, top: QColor, bottom: QColor) -> None:
    """Ряд лепестков юбки (зубчатый край, как листья)."""
    grad = QLinearGradient(0, y - 6, 0, y + depth)
    grad.setColorAt(0.0, top)
    grad.setColorAt(1.0, bottom)
    path = QPainterPath()
    path.moveTo(cx - half_w, y - 10)
    path.lineTo(cx + half_w, y - 10)
    step = (2 * half_w) / petals
    for i in range(petals):
        x1 = cx + half_w - i * step
        x0 = x1 - step
        path.quadTo((x0 + x1) / 2, y + depth, x0, y)
    path.closeSubpath()
    p.setBrush(QBrush(grad))
    p.setPen(QPen(_lerp_color(bottom, QColor("#000000"), 0.25), 2))
    p.drawPath(path)


# ---------------------------------------------------------------------------
#  Фея "Динь" (по референсу)
# ---------------------------------------------------------------------------
def draw_fairy(p: QPainter, t: float = 0.6, blink: bool = False,
               look: float = 0.0) -> None:
    """Рисует фею в нормализованных координатах 240x240.

    t -- время анимации (парение, взмахи крыльев, наклон головы).
    """
    S = FAIRY
    bounce = math.sin(t * 2.1) * 6.0
    wing = math.sin(t * 9.5)
    tilt = math.sin(t * 1.6) * 3.0
    pulse = 0.5 + 0.5 * math.sin(t * 4.0)

    p.translate(0, bounce)
    _draw_soft_shadow(p, 120, 232 - bounce, 44)

    # --- Крылья (за телом) ----------------------------------------
    for side in (-1, 1):
        p.save()
        p.translate(120 + side * 6, 146)
        p.rotate(side * wing * 16)
        for (dx, dy, rx, ry, rot) in (
                (side * -8, -16, 36, 24, -24 * side),
                (side * -6, 12, 25, 16, 16 * side)):
            grad = QRadialGradient(dx, dy, rx * 1.3)
            grad.setColorAt(0.0, QColor(205, 245, 255, 170))
            grad.setColorAt(0.65, QColor(180, 232, 252, 95))
            grad.setColorAt(1.0, QColor(180, 232, 252, 8))
            p.setBrush(QBrush(grad))
            p.setPen(QPen(QColor(255, 255, 255, 170), 1.8))
            p.save()
            p.translate(dx, dy)
            p.rotate(rot)
            p.drawEllipse(int(-rx), int(-ry), int(rx * 2), int(ry * 2))
            p.setPen(QPen(QColor(255, 255, 255, 120), 1.2))
            p.drawLine(0, 0, int(-rx * 0.55), int(ry * 0.3))
            p.drawLine(0, 0, int(-rx * 0.35), int(-ry * 0.45))
            p.restore()
        p.restore()

    # --- Ноги и листики-туфельки ------------------------------------
    p.setPen(QPen(S.SKIN, 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(112, 188, 110, 222)
    p.drawLine(128, 188, 132, 222)
    for fx, fw in ((104, 13), (126, 13)):
        p.setBrush(S.DRESS)
        p.setPen(QPen(S.DRESS_DARK, 1.5))
        p.drawEllipse(fx, 218, fw, 9)

    # --- Платье из лепестков ----------------------------------------
    bodice = QPainterPath()
    bodice.moveTo(120 - 13, 128)
    bodice.lineTo(120 + 13, 128)
    bodice.lineTo(120 + 17, 156)
    bodice.lineTo(120 - 17, 156)
    bodice.closeSubpath()
    grad = QLinearGradient(120, 128, 120, 156)
    grad.setColorAt(0.0, S.DRESS_LIGHT)
    grad.setColorAt(1.0, S.DRESS)
    p.setBrush(QBrush(grad))
    p.setPen(QPen(S.DRESS_DARK, 2))
    p.drawPath(bodice)
    _petal_hem(p, 120, 158, 32, 16, 4, QColor("#CDE8A5"), S.DRESS_LIGHT)
    _petal_hem(p, 120, 170, 40, 17, 5, S.DRESS_LIGHT, S.DRESS)
    _petal_hem(p, 120, 182, 47, 18, 5, S.DRESS, S.DRESS_DARK)
    # Прожилки на лепестках.
    p.setPen(QPen(QColor(111, 168, 56, 140), 1.2))
    for vx in (98, 120, 142):
        p.drawLine(vx, 160, vx - 2, 172)

    # --- Руки --------------------------------------------------------
    p.setPen(QPen(S.SKIN, 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(108, 140, 88, 156)
    wand_arm = math.sin(t * 2.4) * 6.0
    p.drawLine(132, 140, 152, 124 + wand_arm)

    # --- Голова ------------------------------------------------------
    p.save()
    p.translate(120, 122)
    p.rotate(tilt)
    p.translate(-120, -122)
    hair_grad = QRadialGradient(120, 92, 44)
    hair_grad.setColorAt(0.0, _lerp_color(S.HAIR, QColor("#FFFFFF"), 0.4))
    hair_grad.setColorAt(1.0, S.HAIR_DARK)
    hair_brush = QBrush(hair_grad)

    p.setPen(QPen(S.HAIR_DARK, 2))
    p.setBrush(hair_brush)
    p.drawEllipse(120 - 38, 84, 76, 74)

    face = QRadialGradient(120, 104, 34)
    face.setColorAt(0.0, QColor("#FFF0DC"))
    face.setColorAt(1.0, S.SKIN_DARK)
    p.setBrush(QBrush(face))
    p.setPen(QPen(S.SKIN_DARK, 1.6))
    p.drawEllipse(120 - 30, 94, 60, 62)

    p.setBrush(hair_brush)
    p.setPen(QPen(S.HAIR_DARK, 1.8))
    for sx in (88, 144):
        lock = QPainterPath()
        lock.moveTo(sx, 102)
        lock.quadTo(sx - 8, 124, sx + 2, 136)
        lock.quadTo(sx + 10, 120, sx + 10, 102)
        lock.closeSubpath()
        p.drawPath(lock)

    bangs = QPainterPath()
    bangs.moveTo(120 - 31, 110)
    bangs.quadTo(120, 72, 120 + 31, 110)
    bangs.quadTo(120 + 14, 92, 120 + 6, 104)
    bangs.quadTo(120 - 2, 88, 120 - 12, 102)
    bangs.quadTo(120 - 20, 92, 120 - 31, 110)
    bangs.closeSubpath()
    p.setBrush(hair_brush)
    p.setPen(QPen(S.HAIR_DARK, 1.8))
    p.drawPath(bangs)
    # Блики-пряди на волосах.
    p.setPen(QPen(QColor(255, 250, 210, 150), 2.6, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    p.drawArc(100, 84, 40, 22, 150 * 16, 70 * 16)
    p.setPen(QPen(QColor(255, 250, 210, 110), 2.0))
    p.drawArc(132, 90, 18, 26, 120 * 16, 70 * 16)

    p.setPen(QPen(QColor("#C08A2E"), 2.2, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    p.drawArc(int(106 - 9), int(110 - 9), 18, 10, 190 * 16, 140 * 16)
    p.drawArc(int(134 - 9), int(110 - 9), 18, 10, 190 * 16, 140 * 16)

    draw_glossy_eye(p, 106, 122, 9, 11, S.IRIS, blink, look)
    draw_glossy_eye(p, 134, 122, 9, 11, S.IRIS, blink, look)

    for sx in (97, 143):
        blush = QRadialGradient(sx, 136, 9)
        blush.setColorAt(0.0, QColor(255, 138, 128, 150))
        blush.setColorAt(1.0, QColor(255, 138, 128, 0))
        p.setBrush(QBrush(blush))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(sx - 9, 127, 18, 12)

    p.setPen(QPen(QColor("#B5533C"), 2.2, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    p.setBrush(QColor("#E2765C"))
    mouth = QPainterPath()
    mouth.moveTo(111, 140)
    mouth.quadTo(120, 151, 129, 140)
    mouth.quadTo(120, 146, 111, 140)
    mouth.closeSubpath()
    p.drawPath(mouth)
    p.restore()

    # --- Волшебная палочка со звездой --------------------------------
    p.setPen(QPen(QColor("#A9743E"), 3.4, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    p.drawLine(152, 124 + wand_arm, 176, 84)
    glow_r = 17 + pulse * 11
    glow = QRadialGradient(176, 76, glow_r)
    glow.setColorAt(0.0, QColor(255, 240, 150, 225))
    glow.setColorAt(0.55, QColor(255, 220, 110, 120))
    glow.setColorAt(1.0, QColor(255, 220, 110, 0))
    p.setBrush(QBrush(glow))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(int(176 - glow_r), int(76 - glow_r),
                  int(glow_r * 2), int(glow_r * 2))
    star = QPainterPath()
    for i in range(10):
        angle = math.pi / 2 + t * 0.8 + i * math.pi / 5
        radius = (10 + pulse * 3) if i % 2 == 0 else (10 + pulse * 3) * 0.45
        x = 176 + radius * math.cos(angle)
        y = 76 - radius * math.sin(angle)
        if i == 0:
            star.moveTo(x, y)
        else:
            star.lineTo(x, y)
    star.closeSubpath()
    p.setBrush(QColor("#FFD54F"))
    p.setPen(QPen(QColor("#E5A83B"), 1.6))
    p.drawPath(star)

    # --- Мерцающие искры вокруг ---------------------------------------
    for i in range(5):
        ang = t * 1.4 + i * math.pi * 2 / 5
        sx = 120 + math.cos(ang) * 90
        sy = 120 + math.sin(ang) * 76
        tw = 0.5 + 0.5 * math.sin(t * 5 + i * 1.7)
        r = 2.6 + tw * 2.4
        alpha = int(120 + tw * 135)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 235, 140, alpha))
        p.drawEllipse(int(sx - r), int(sy - r), int(r * 2), int(r * 2))


# ---------------------------------------------------------------------------
#  "Боевой Прайм" (по референсу)
# ---------------------------------------------------------------------------
def draw_prime(p: QPainter, t: float = 0.6, blink: bool = False,
               look: float = 0.0) -> None:
    """Рисует Боевого Прайма в нормализованных координатах 240x240.

    t -- время анимации (покачивание, поворот головы, пульс огней).
    """
    S = PRIME
    bob = math.sin(t * 2.2) * 3.0
    tilt = math.sin(t * 1.7) * 2.5
    flex = math.sin(t * 3.2)
    glow = 0.55 + 0.45 * math.sin(t * 3.4)

    p.translate(0, bob)
    _draw_soft_shadow(p, 120, 233 - bob, 62)

    # --- Реактивные двигатели на спине --------------------------------
    for tx in (84, 152):
        grad = QLinearGradient(tx, 110, tx + 16, 150)
        grad.setColorAt(0.0, S.SILVER)
        grad.setColorAt(1.0, S.SILVER_DARK)
        p.setBrush(QBrush(grad))
        p.setPen(QPen(S.STEEL, 2))
        p.drawRoundedRect(int(tx), 112, 14, 40, 5, 5)
        p.setBrush(QColor("#3A4250"))
        p.drawRoundedRect(int(tx + 1), 148, 12, 8, 3, 3)
        g = QColor(90, 200, 250)
        g.setAlpha(int(120 * glow))
        p.setBrush(g)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(int(tx + 2), 152, 10, 5)
        # Заклёпки.
        p.setBrush(QColor("#6E7686"))
        p.drawEllipse(int(tx + 5), 118, 4, 4)

    # --- Ноги ----------------------------------------------------------
    for lx in (94, 124):
        thigh = QLinearGradient(lx, 168, lx + 22, 196)
        thigh.setColorAt(0.0, S.BLUE_LIGHT)
        thigh.setColorAt(1.0, S.BLUE_DARK)
        p.setBrush(QBrush(thigh))
        p.setPen(QPen(QColor("#16337F"), 2))
        p.drawRoundedRect(int(lx), 168, 22, 28, 5, 5)
        p.setBrush(S.RED)
        p.setPen(QPen(S.RED_DARK, 1.5))
        p.drawRoundedRect(int(lx + 4), 172, 14, 8, 3, 3)
        p.setBrush(QColor("#39414E"))
        p.setPen(QPen(QColor("#222833"), 1.5))
        p.drawEllipse(int(lx + 5), 194, 12, 10)
        shin = QLinearGradient(lx + 2, 198, lx + 20, 224)
        shin.setColorAt(0.0, S.SILVER)
        shin.setColorAt(1.0, S.SILVER_DARK)
        p.setBrush(QBrush(shin))
        p.setPen(QPen(S.STEEL, 2))
        p.drawRoundedRect(int(lx + 1), 198, 20, 24, 4, 4)
        p.setBrush(QColor("#B7C0CC"))
        p.drawRoundedRect(int(lx - 4), 220, 30, 12, 5, 5)

    # --- Таз ------------------------------------------------------------
    pelvis = QLinearGradient(100, 152, 140, 176)
    pelvis.setColorAt(0.0, S.SILVER)
    pelvis.setColorAt(1.0, S.SILVER_DARK)
    p.setBrush(QBrush(pelvis))
    p.setPen(QPen(S.STEEL, 2))
    p.drawRoundedRect(98, 152, 44, 18, 5, 5)

    # --- Торс ------------------------------------------------------------
    chest = QLinearGradient(88, 104, 152, 162)
    chest.setColorAt(0.0, S.RED_LIGHT)
    chest.setColorAt(0.55, S.RED)
    chest.setColorAt(1.0, S.RED_DARK)
    p.setBrush(QBrush(chest))
    p.setPen(QPen(QColor("#96191B"), 2.4))
    p.drawRoundedRect(88, 104, 64, 54, 9, 9)
    p.setPen(QPen(QColor("#96191B"), 1.6))
    p.setBrush(QColor(255, 255, 255, 30))
    p.drawRoundedRect(94, 110, 22, 16, 4, 4)
    p.drawRoundedRect(124, 110, 22, 16, 4, 4)
    # Синие "окна" на грудных пластинах.
    p.setBrush(QColor(74, 122, 238, 160))
    p.setPen(QPen(QColor("#16337F"), 1.2))
    p.drawRoundedRect(97, 113, 16, 10, 2, 2)
    p.drawRoundedRect(127, 113, 16, 10, 2, 2)
    column = QLinearGradient(114, 108, 126, 158)
    column.setColorAt(0.0, QColor("#F2F5F9"))
    column.setColorAt(1.0, S.SILVER_DARK)
    p.setBrush(QBrush(column))
    p.setPen(QPen(S.STEEL, 1.8))
    p.drawRoundedRect(113, 108, 14, 48, 4, 4)
    core = QRadialGradient(120, 134, 12 + glow * 6)
    core.setColorAt(0.0, QColor(220, 250, 255, 235))
    core.setColorAt(0.4, QColor(90, 220, 250, int(200 * glow)))
    core.setColorAt(1.0, QColor(40, 150, 220, 0))
    p.setBrush(QBrush(core))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(120 - 16, 134 - 16, 32, 32)
    p.setBrush(QColor("#BDEFFF"))
    p.drawEllipse(117, 131, 7, 7)
    p.setBrush(S.SILVER)
    p.setPen(QPen(S.STEEL, 1.6))
    for i, ay in enumerate((164, 170)):
        p.drawRoundedRect(104 + (4 if i % 2 else 0), ay,
                          32 - (8 if i % 2 else 0), 5, 2, 2)

    # --- Плечи и руки (на правой руке -- пушка) ---------------------------
    for side in (-1, 1):
        ax = 70 if side == -1 else 150
        pauldron = QLinearGradient(ax, 100, ax + 24, 132)
        pauldron.setColorAt(0.0, S.BLUE_LIGHT)
        pauldron.setColorAt(1.0, S.BLUE_DARK)
        p.setBrush(QBrush(pauldron))
        p.setPen(QPen(QColor("#16337F"), 2.2))
        p.drawRoundedRect(int(ax), 100, 24, 30, 8, 8)
        p.setBrush(QColor(255, 255, 255, 40))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(int(ax + 3), 103, 12, 8, 3, 3)
        # Заклёпка на плече.
        p.setBrush(QColor("#F2F5F9"))
        p.drawEllipse(int(ax + 8), 120, 5, 5)
        upper = QLinearGradient(ax + 4, 130, ax + 18, 152)
        upper.setColorAt(0.0, S.SILVER)
        upper.setColorAt(1.0, S.SILVER_DARK)
        p.setBrush(QBrush(upper))
        p.setPen(QPen(S.STEEL, 1.8))
        p.drawRoundedRect(int(ax + 4), 130, 14, 22, 4, 4)
        p.setBrush(S.RED)
        p.setPen(QPen(S.RED_DARK, 1.5))
        p.drawEllipse(int(ax + 3), 150, 15, 10)
        p.save()
        p.translate(ax + 11, 160)
        p.rotate(side * flex * 6)
        fore = QLinearGradient(-8, 0, 8, 22)
        fore.setColorAt(0.0, QColor("#F2F5F9"))
        fore.setColorAt(1.0, S.SILVER_DARK)
        p.setBrush(QBrush(fore))
        p.setPen(QPen(S.STEEL, 1.8))
        p.drawRoundedRect(-9, 0, 18, 22, 4, 4)
        if side == 1:
            # Пушка, закреплённая на руке (боевой Прайм).
            barrel = QLinearGradient(-6, 22, 6, 46)
            barrel.setColorAt(0.0, S.SILVER)
            barrel.setColorAt(1.0, S.STEEL)
            p.setBrush(QBrush(barrel))
            p.setPen(QPen(QColor("#5B6470"), 1.8))
            p.drawRoundedRect(-6, 22, 12, 22, 4, 4)
            p.setBrush(QColor("#39414E"))
            p.drawRoundedRect(-4, 40, 8, 7, 2, 2)
            p.setBrush(QColor("#E0393B"))
            p.setPen(QPen(S.RED_DARK, 1.2))
            p.drawRoundedRect(-7, 24, 14, 4, 2, 2)
        else:
            fist = QLinearGradient(-10, 22, 10, 40)
            fist.setColorAt(0.0, S.SILVER)
            fist.setColorAt(1.0, QColor("#9AA3B2"))
            p.setBrush(QBrush(fist))
            p.setPen(QPen(QColor("#78818F"), 1.8))
            p.drawRoundedRect(-10, 22, 20, 18, 5, 5)
            p.setPen(QPen(QColor("#78818F"), 1.4))
            for kx in (-5, 0, 5):
                p.drawLine(kx, 25, kx, 31)
        p.restore()

    # --- Голова --------------------------------------------------------------
    p.save()
    p.translate(120, 86)
    p.rotate(tilt)
    p.translate(-120, -86)
    p.setBrush(S.STEEL)
    p.setPen(QPen(QColor("#6E7686"), 1.6))
    p.drawRect(114, 98, 12, 10)
    face = QLinearGradient(104, 70, 136, 100)
    face.setColorAt(0.0, QColor("#F2F5F9"))
    face.setColorAt(1.0, QColor("#C6CEDA"))
    p.setBrush(QBrush(face))
    p.setPen(QPen(QColor("#8B94A3"), 2))
    p.drawRoundedRect(106, 72, 28, 26, 6, 6)
    helmet = QPainterPath()
    helmet.moveTo(102, 100)
    helmet.lineTo(102, 78)
    helmet.quadTo(120, 58, 138, 78)
    helmet.lineTo(138, 100)
    helmet.lineTo(130, 100)
    helmet.lineTo(130, 82)
    helmet.quadTo(120, 74, 110, 82)
    helmet.lineTo(110, 100)
    helmet.closeSubpath()
    hgrad = QLinearGradient(102, 58, 138, 100)
    hgrad.setColorAt(0.0, S.BLUE_LIGHT)
    hgrad.setColorAt(1.0, S.BLUE_DARK)
    p.setBrush(QBrush(hgrad))
    p.setPen(QPen(QColor("#16337F"), 2.2))
    p.drawPath(helmet)
    crest = QPainterPath()
    crest.moveTo(116, 60)
    crest.quadTo(120, 48, 124, 60)
    crest.lineTo(126, 66)
    crest.lineTo(114, 66)
    crest.closeSubpath()
    cgrad = QLinearGradient(114, 48, 126, 66)
    cgrad.setColorAt(0.0, QColor("#F05050"))
    cgrad.setColorAt(1.0, S.RED_DARK)
    p.setBrush(QBrush(cgrad))
    p.setPen(QPen(QColor("#96191B"), 1.8))
    p.drawPath(crest)
    p.setBrush(QColor("#39414E"))
    p.setPen(QPen(QColor("#222833"), 1.5))
    for ex in (98, 136):
        p.drawRoundedRect(int(ex), 80, 8, 14, 3, 3)
    intensity = 0.25 if blink else glow
    draw_robot_eye(p, 114, 84, 10, 7, intensity)
    draw_robot_eye(p, 126, 84, 10, 7, intensity)
    p.setBrush(QColor("#B7C0CC"))
    p.setPen(QPen(QColor("#78818F"), 1.4))
    p.drawRoundedRect(113, 92, 14, 4, 2, 2)
    p.restore()


# ---------------------------------------------------------------------------
#  Виджеты персонажей (QPainter-рендер; GPU-вариант -- в gl_characters.py)
# ---------------------------------------------------------------------------
class CharacterWidget(QWidget):
    """Базовый виджет персонажа: таймер анимации + моргание."""

    def __init__(self, parent: QWidget | None = None, size: int = 200,
                 fps: int = 30):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.character_key = "fairy"
        self._t = 0.0
        self._dt = 1.0 / fps
        self._blink = False
        self._look = 0.0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(int(1000 * self._dt))

        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._do_blink)
        self._restart_blink_timer()

    def _restart_blink_timer(self) -> None:
        self._blink_timer.start(1700 + int(2400 * (id(self) % 97) / 97))

    def _do_blink(self) -> None:
        self._blink = True
        self.update()
        QTimer.singleShot(150, self._unblink)

    def _unblink(self) -> None:
        self._blink = False
        self.update()
        self._restart_blink_timer()

    def _tick(self) -> None:
        self._t += self._dt
        self._look = math.sin(self._t * 0.9) * 0.6
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        scale = self.width() / _CANVAS
        p.scale(scale, scale)
        self._draw_frame(p)

    def _draw_frame(self, p: QPainter) -> None:
        """Кадр персонажа (переопределяется подклассами)."""
        draw_fairy(p, self._t, self._blink, self._look)


class FairyWidget(CharacterWidget):
    """Фея Динь (QPainter-анимация)."""

    def __init__(self, parent=None, size: int = 200):
        super().__init__(parent, size)
        self.character_key = "fairy"

    def _draw_frame(self, p: QPainter) -> None:
        draw_fairy(p, self._t, self._blink, self._look)


class PrimeWidget(CharacterWidget):
    """Боевой Прайм (QPainter-анимация)."""

    def __init__(self, parent=None, size: int = 200):
        super().__init__(parent, size)
        self.character_key = "prime"

    def _draw_frame(self, p: QPainter) -> None:
        draw_prime(p, self._t, self._blink, self._look)


def make_character(name: str, parent: QWidget | None = None,
                   size: int = 200) -> CharacterWidget:
    """Создаёт QPainter-виджет персонажа по его имени ('fairy' или 'prime')."""
    name = (name or "").lower()
    if name in ("prime", "battle", "боевой", "прайм"):
        return PrimeWidget(parent, size)
    return FairyWidget(parent, size)  # по умолчанию -- фея


def draw_character_image(key: str, px: int = 512, t: float = 0.6) -> "QImage":
    """Рендерит персонажа в QImage высокого разрешения (для GPU-текстуры).

    QPainter здесь — только «пекарь» текстуры: сама анимация в приложении
    выполняется на GPU шейдерами (см. gl_characters.py).
    """
    from PySide6.QtGui import QImage
    # Non-premultiplied ARGB32: при конвертации в RGBA8888 альфа остаётся
    # прямой, как ожидает OpenGL-текстура.
    img = QImage(px, px, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.scale(px / _CANVAS, px / _CANVAS)
    if key == "prime":
        draw_prime(p, t, False, 0.0)
    else:
        draw_fairy(p, t, False, 0.0)
    p.end()
    return img


CHARACTER_NAMES = {
    "fairy": "Фея Динь",
    "prime": "Боевой Прайм",
}
