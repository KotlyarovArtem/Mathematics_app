# -*- coding: utf-8 -*-
"""
Анимированные виджеты обратной связи и оценки.

Содержит:
    * ``FeedbackWidget`` -- крупная яркая надпись "Верно!"/"Не правильно":
      для верного ответа -- радужный текст с вращающимися лучами и блёстками,
      для неверного -- мягкая ободряющая надпись с подтекстом надежды;
    * ``GradeBadge``     -- крупная цифра оценки сессии со свечением/тенью;
    * ``SparklesOverlay``-- яркое конфетти со звёздами и лентами.

Все эффекты реализованы через QVariantAnimation и QPainter
(требования 3.8, 3.12).
"""
from __future__ import annotations

import math
import random
from typing import List

from PySide6.QtCore import (QEasingCurve, QElapsedTimer, QPointF, QRectF,
                             QTimer, Qt, QVariantAnimation, Signal)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient,
                            QLinearGradient, QFont,
                            QFontMetrics, QPainter, QPainterPath, QPen,
                            QRadialGradient)
from PySide6.QtWidgets import QWidget

from ui_styles import Palette


# ---------------------------------------------------------------------------
#  Яркая анимированная обратная связь
# ---------------------------------------------------------------------------
class FeedbackWidget(QWidget):
    """Крупная анимированная надпись результата ответа.

    "Верно!"  -- радужный текст с вращающимися лучами солнца, блёстками
                 и пружинящим появлением (победное настроение).
    "Не правильно" -- мягкие тёплые тона, аккуратное появление и
                 ободряющий подтекст (грусть с надеждой).
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumHeight(170)
        self._state: int = 0          # 0 -- пусто, 1 -- верно, 2 -- неверно
        self._scale = 0.0
        self._spin = 0.0
        self._pop_anim: QVariantAnimation | None = None
        self._pulse_anim: QVariantAnimation | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)

    # ------------------------------------------------------------------
    def show_feedback(self, correct: bool) -> None:
        """Показывает надпись в зависимости от правильности ответа."""
        self._state = 1 if correct else 2
        self._scale = 0.0
        self._timer.start(33)

        # Пружинящее появление.
        pop = QVariantAnimation(self)
        pop.setDuration(560)
        pop.setEasingCurve(QEasingCurve.Type.OutBack)
        pop.setKeyValues([(0.0, 0.0), (1.0, 1.0)])
        pop.valueChanged.connect(self._set_scale)
        pop.start()
        self._pop_anim = pop

        # Для верного ответа -- дополнительная пульсация после появления.
        if correct:
            pulse = QVariantAnimation(self)
            pulse.setDuration(900)
            pulse.setLoopCount(3)
            pulse.setEasingCurve(QEasingCurve.Type.InOutSine)
            pulse.setKeyValues([(0.0, 1.0), (0.5, 1.07), (1.0, 1.0)])
            pulse.valueChanged.connect(self._set_scale)
            pulse.start()
            self._pulse_anim = pulse
        else:
            self._pulse_anim = None

    def clear(self) -> None:
        """Скрывает надпись."""
        self._state = 0
        self._timer.stop()
        self.update()

    # ------------------------------------------------------------------
    def _set_scale(self, value: float) -> None:
        self._scale = float(value)
        self.update()

    def _on_tick(self) -> None:
        self._spin += 0.9
        self.update()

    # ------------------------------------------------------------------
    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        if self._state == 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2

        if self._state == 1:
            self._paint_correct(p, cx, cy)
        else:
            self._paint_wrong(p, cx, cy)

    # ------------------------------------------------------------------
    def _paint_correct(self, p: QPainter, cx: float, cy: float) -> None:
        """Победная картинка: лучи, радужный текст, блёстки."""
        w = self.width()
        # Вращающиеся лучи солнца.
        ray_r = min(w, self.height()) * 0.52
        grad = QRadialGradient(cx, cy, ray_r)
        grad.setColorAt(0.0, QColor(255, 236, 130, 190))
        grad.setColorAt(0.6, QColor(255, 214, 100, 90))
        grad.setColorAt(1.0, QColor(255, 214, 100, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawEllipse(QPointF(cx, cy), ray_r, ray_r)
        p.save()
        p.translate(cx, cy)
        p.rotate(self._spin)
        for i in range(12):
            p.rotate(30.0)
            spoke = QPainterPath()
            spoke.moveTo(0, -14)
            spoke.lineTo(9, -ray_r * 0.92)
            spoke.lineTo(-9, -ray_r * 0.92)
            spoke.closeSubpath()
            p.setBrush(QColor(255, 213, 82, 110))
            p.drawPath(spoke)
        p.restore()

        # Радужный текст с белой обводкой и тенью.
        p.save()
        p.translate(cx, cy)
        p.scale(self._scale, self._scale)
        font = QFont("Comic Sans MS", 58, QFont.Weight.Black)
        p.setFont(font)
        rect = QRectF(-320, -55, 640, 110)
        # Тень.
        p.setPen(QColor(90, 60, 0, 90))
        p.drawText(rect.translated(4, 6), Qt.AlignmentFlag.AlignCenter, "Верно!")
        # Обводка.
        stroke = QPen(QColor("#FFFFFF"), 10, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(stroke)
        rainbow = QConicalGradient(0, 0, -self._spin * 0.02)
        rainbow.setColorAt(0.00, QColor("#FF5E5B"))
        rainbow.setColorAt(0.20, QColor("#FF9F45"))
        rainbow.setColorAt(0.40, QColor("#FFD54F"))
        rainbow.setColorAt(0.60, QColor("#66D97F"))
        rainbow.setColorAt(0.80, QColor("#5BA8D6"))
        rainbow.setColorAt(1.00, QColor("#B19CD9"))
        p.setBrush(QBrush(rainbow))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Верно!")
        p.restore()

        # Реплика персонажа под победной надписью.
        p.setFont(QFont("Comic Sans MS", 22, QFont.Weight.Black))
        p.setPen(QPen(Qt.PenStyle.NoPen))
        p.setBrush(QColor("#2D7A4F"))
        p.drawText(QRectF(0, cy + 34, w, 46), Qt.AlignmentFlag.AlignCenter,
                   "Ты молодец! Классно!")

        # Мерцающие звёздочки по углам.
        for i in range(6):
            ang = self._spin * 0.02 + i * math.pi / 3
            sx = cx + math.cos(ang) * (ray_r * 0.78)
            sy = cy + math.sin(ang) * (ray_r * 0.55)
            tw = 0.5 + 0.5 * math.sin(self._spin * 0.15 + i)
            self._star(p, sx, sy, 4 + tw * 5,
                       QColor(255, 240, 150, int(150 + tw * 105)))

    def _paint_wrong(self, p: QPainter, cx: float, cy: float) -> None:
        """Мягкая ободряющая картинка: тёплый текст и подтекст надежды."""
        w = self.width()
        # Лёгкое мягкое сияние.
        glow = QRadialGradient(cx, cy - 10, min(w, self.height()) * 0.5)
        glow.setColorAt(0.0, QColor(180, 200, 225, 90))
        glow.setColorAt(1.0, QColor(180, 200, 225, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPointF(cx, cy - 10), w * 0.5, self.height() * 0.5)

        p.save()
        p.translate(cx, cy)
        p.scale(self._scale, self._scale)
        # Основная надпись.
        font = QFont("Comic Sans MS", 46, QFont.Weight.Black)
        p.setFont(font)
        rect = QRectF(-320, -70, 640, 80)
        p.setPen(QColor(60, 60, 90, 80))
        p.drawText(rect.translated(3, 4), Qt.AlignmentFlag.AlignCenter,
                   "Не правильно")
        p.setPen(QPen(QColor("#FFFFFF"), 8, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(QColor("#6C86B8"))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Не правильно")
        # Ободряющий подтекст (грусть с надеждой).
        sub_font = QFont("Comic Sans MS", 21, QFont.Weight.Bold)
        p.setFont(sub_font)
        p.setPen(QPen(Qt.PenStyle.NoPen))
        p.setBrush(QColor("#4A6396"))
        p.drawText(QRectF(-320, 12, 640, 60), Qt.AlignmentFlag.AlignCenter,
                   "В следующий раз\nобязательно получится")
        p.restore()

        # Медленно поднимающиеся пузырьки-надежды.
        for i in range(5):
            ph = self._spin * 0.012 + i * 1.3
            bx = cx - 130 + i * 65 + math.sin(ph * 2) * 14
            by = cy + 60 - ((self._spin * 0.5 + i * 47) % 130)
            r = 5 + (i % 3) * 2.5
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(140, 170, 220, 130), 2))
            p.drawEllipse(QPointF(bx, by), r, r)

    @staticmethod
    def _star(p: QPainter, cx: float, cy: float, r: float, color: QColor) -> None:
        path = QPainterPath()
        for i in range(10):
            ang = math.pi / 2 + i * math.pi / 5
            rad = r if i % 2 == 0 else r * 0.45
            x = cx + rad * math.cos(ang)
            y = cy - rad * math.sin(ang)
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        path.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawPath(path)


# ---------------------------------------------------------------------------
#  Бейдж оценки сессии
# ---------------------------------------------------------------------------
class GradeBadge(QWidget):
    """Крупная цифра оценки сессии с эффектом свечения/тени.

    Стилистика по требованиям 3.12:
        * 4 и 5 -- крупный красный шрифт со свечением; для 5 -- золотой венок;
        * 3     -- крупный синий шрифт с объёмной тенью;
        * 1 и 2 -- строгий плоский тёмно-серый шрифт.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._grade: int | None = None
        self._scale = 0.0
        self._glow = 0.0
        self._spin = 0.0
        self._anim: QVariantAnimation | None = None
        self._glow_anim: QVariantAnimation | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self.setMinimumSize(260, 260)

    def set_grade(self, grade: int) -> None:
        """Устанавливает оценку и запускает анимацию появления."""
        self._grade = grade
        self._scale = 0.0
        self._glow = 0.0
        self._spin = 0.0
        self.update()
        self._timer.start(33)

        anim = QVariantAnimation(self)
        anim.setDuration(750)
        anim.setEasingCurve(QEasingCurve.Type.OutBack)
        anim.setKeyValues([(0.0, 0.0), (1.0, 1.0)])
        anim.valueChanged.connect(self._set_scale)
        anim.start()
        self._anim = anim

        # Пульсирующее свечение для высоких оценок.
        if grade in (4, 5):
            glow = QVariantAnimation(self)
            glow.setDuration(1200)
            glow.setLoopCount(-1)
            glow.setKeyValues([(0.0, 0.35), (0.5, 1.0), (1.0, 0.35)])
            glow.valueChanged.connect(self._set_glow)
            glow.start()
            self._glow_anim = glow
        else:
            self._glow_anim = None

    def _on_tick(self) -> None:
        self._spin += 1.0
        if self._grade not in (4, 5) and self._scale >= 1.0:
            self._timer.stop()
        self.update()

    def _set_scale(self, value: float) -> None:
        self._scale = float(value)
        self.update()

    def _set_glow(self, value: float) -> None:
        self._glow = float(value)
        self.update()

    def _grade_color(self) -> QColor:
        if self._grade in (4, 5):
            return QColor(Palette.GRADE_HIGH)
        if self._grade == 3:
            return QColor(Palette.GRADE_MID)
        return QColor(Palette.GRADE_LOW)

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        if self._grade is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        color = self._grade_color()

        # Лучи для оценок 4 и 5.
        if self._grade in (4, 5):
            glow_radius = 118 * self._glow + 44
            grad = QRadialGradient(cx, cy, glow_radius)
            light = QColor(color)
            light.setAlpha(int(120 * self._glow))
            grad.setColorAt(0.0, light)
            grad.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawEllipse(QPointF(cx, cy), glow_radius, glow_radius)
            # Вращающиеся золотые лучики за цифрой.
            p.save()
            p.translate(cx, cy)
            p.rotate(self._spin)
            for i in range(10):
                p.rotate(36.0)
                spoke = QPainterPath()
                spoke.moveTo(0, -70)
                spoke.lineTo(7, -116)
                spoke.lineTo(-7, -116)
                spoke.closeSubpath()
                p.setBrush(QColor(255, 213, 82, 90))
                p.drawPath(spoke)
            p.restore()

        # Золотой венок для оценки 5.
        if self._grade == 5:
            self._draw_wreath(p, cx, cy, 108 * max(self._scale, 0.01))

        # Цифра оценки.
        p.save()
        p.translate(cx, cy)
        p.scale(self._scale, self._scale)
        font = QFont("Comic Sans MS", 120, QFont.Weight.Black)
        p.setFont(font)
        # Объёмная тень.
        for dx, dy, a in [(5, 7, 70), (2, 3, 120)]:
            sc = QColor(0, 0, 0, a)
            p.setPen(sc)
            p.drawText(QRectF(-90 + dx, -90 + dy, 180, 180),
                       Qt.AlignmentFlag.AlignCenter, str(self._grade))
        # Основная цифра с белой обводкой.
        p.setPen(QPen(QColor("#FFFFFF"), 8, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(color)
        p.drawText(QRectF(-90, -90, 180, 180),
                   Qt.AlignmentFlag.AlignCenter, str(self._grade))
        p.restore()

    def _draw_wreath(self, p: QPainter, cx: float, cy: float, r: float) -> None:
        """Рисует декоративный золотой венок вокруг цифры (для оценки 5)."""
        p.save()
        p.setBrush(QColor(Palette.YELLOW))
        p.setPen(QPen(QColor("#E5B938"), 2))
        for sign in (-1, 1):
            for i in range(12):
                angle = math.radians(-60 + i * 10)
                x = cx + sign * (r * 0.9) * math.cos(angle)
                y = cy + r * 0.9 * math.sin(angle) - r * 0.05
                p.save()
                p.translate(x, y)
                p.rotate(math.degrees(angle))
                leaf = QPainterPath()
                leaf.moveTo(0, 0)
                leaf.cubicTo(8, -6, 14, 4, 0, 12)
                leaf.cubicTo(-14, 4, -8, -6, 0, 0)
                p.drawPath(leaf)
                p.restore()
        p.setBrush(QColor(Palette.CORAL))
        bow = QPainterPath()
        bow.moveTo(cx - 12, cy + r * 0.85)
        bow.cubicTo(cx - 20, cy + r * 0.7, cx - 20, cy + r * 1.0, cx, cy + r * 0.92)
        bow.cubicTo(cx + 20, cy + r * 1.0, cx + 20, cy + r * 0.7, cx + 12, cy + r * 0.85)
        bow.closeSubpath()
        p.drawPath(bow)
        p.restore()


# ---------------------------------------------------------------------------
#  Яркое конфетти со звёздами
# ---------------------------------------------------------------------------
class SparklesOverlay(QWidget):
    """Прозрачный оверлей с конфетти-фейерверком для эффекта "Верно!".

    Для верного ответа -- взрыв из 100 частиц: звёзды, ленты и круги
    сочных цветов. Для неверного -- спокойные голубые пузырьки.
    Виджет не перехватывает клики.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self._particles: List[dict] = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def burst(self, correct: bool = True) -> None:
        """Запускает фейерверк (верно) или пузырьки (неверно)."""
        if self.parent() is None:
            return
        self.setGeometry(self.parent().rect())
        self.raise_()
        self._particles = []
        rng = random.Random()
        bright = [QColor("#FF5E5B"), QColor("#FF9F45"), QColor("#FFD54F"),
                  QColor("#66D97F"), QColor("#5BC8D6"), QColor("#F49AC2"),
                  QColor("#B19CD9"), QColor("#FFF3B0")]
        calm = [QColor(150, 180, 225), QColor(180, 200, 235)]
        cx, cy = self.width() / 2, self.height() / 2
        count = 100 if correct else 18
        for i in range(count):
            angle = rng.uniform(0, 2 * math.pi)
            if correct:
                speed = rng.uniform(3.5, 11.0)
                vy = math.sin(angle) * speed - 4.0   # импульс вверх
                shape = rng.choice(["star", "rect", "circle"])
            else:
                speed = rng.uniform(0.4, 1.2)
                vy = -rng.uniform(0.6, 1.6)          # пузырьки всплывают
                shape = "circle"
            self._particles.append({
                "x": cx + rng.uniform(-30, 30),
                "y": cy + rng.uniform(-20, 20),
                "vx": math.cos(angle) * speed,
                "vy": vy,
                "life": 1.0,
                "decay": rng.uniform(0.012, 0.02),
                "color": rng.choice(bright if correct else calm),
                "size": rng.uniform(7, 15) if correct else rng.uniform(5, 10),
                "shape": shape,
                "spin": rng.uniform(-14, 14),
                "rot": rng.uniform(0, 360),
                "outline": not correct,
            })
        self.show()
        self._timer.start(28)

    def _tick(self) -> None:
        """Обновляет физику частиц и запускает перерисовку."""
        alive = []
        for pt in self._particles:
            pt["x"] += pt["vx"]
            pt["y"] += pt["vy"]
            if pt["vy"] < 0 or pt["shape"] != "circle":
                pt["vy"] += 0.22          # гравитация для конфетти
            else:
                pt["vy"] -= 0.01          # пузырьки слегка ускоряются вверх
            pt["vx"] *= 0.995
            pt["life"] -= pt["decay"]
            pt["rot"] += pt["spin"]
            if pt["life"] > 0:
                alive.append(pt)
        self._particles = alive
        self.update()
        if not alive:
            self._timer.stop()
            self.hide()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        if not self._particles:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for pt in self._particles:
            color = QColor(pt["color"])
            color.setAlpha(int(255 * min(1.0, pt["life"] * 1.4)))
            size = pt["size"] * (0.5 + 0.5 * pt["life"])
            p.save()
            p.translate(pt["x"], pt["y"])
            p.rotate(pt["rot"])
            if pt["shape"] == "star":
                path = QPainterPath()
                r = size
                for i in range(10):
                    ang = math.pi / 2 + i * math.pi / 5
                    rad = r if i % 2 == 0 else r * 0.45
                    x = rad * math.cos(ang)
                    y = -rad * math.sin(ang)
                    if i == 0:
                        path.moveTo(x, y)
                    else:
                        path.lineTo(x, y)
                path.closeSubpath()
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(color)
                p.drawPath(path)
            elif pt["shape"] == "rect":
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(color)
                p.drawRoundedRect(-size / 2, -size / 4, size, size / 2, 2, 2)
            else:
                if pt["outline"]:
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.setPen(QPen(color, 2))
                else:
                    p.setBrush(color)
                    p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QPointF(0, 0), size / 2, size / 2)
            p.restore()


# ---------------------------------------------------------------------------
#  Экран автомата "однорукий бандит": строка примера на барабанах
# ---------------------------------------------------------------------------
class SlotMachineLabel(QWidget):
    """Строка примера в виде барабанов игрового автомата.

    Каждая цифра -- отдельный барабан: лента цифр прокручивается
    вертикально в ячейке (с затемнением сверху и снизу, как свод
    барабана), а барабаны фиксируются слева направо с заданным
    интервалом (~200 мс). Знаки действий и скобки стоят на местах.
    """

    reel_locked = Signal(int)     # зафиксирован барабан номер k (1-based)
    locked_all = Signal()         # все цифры зафиксированы

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._chars: List[str] = []
        self._digit_idx: List[int] = []
        self._digit_set: set = set()
        self._bases: List[int] = []
        self._locked = 0
        self._spinning = False
        self._placeholder = True
        self._scroll = 0           # прокрутка ленты, px
        self._speed = 30           # px за тик (примерно 900 px/с)
        self._interval_ms = 200
        self._lock_times: List[int] = []
        self._flash: dict = {}     # индекс цифры -> время фиксации
        self._elapsed = 0
        self._rng = random.Random()

        font = QFont("Comic Sans MS")
        font.setPixelSize(56)
        font.setWeight(QFont.Weight.Black)
        self._font = font
        self._fm = QFontMetrics(font)
        self._cell_h = int(self._fm.height() * 1.02)
        self.setFixedHeight(int(self._cell_h * 1.32))

        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------
    #  Публичный API
    # ------------------------------------------------------------------
    def stop(self) -> None:
        """Останавливает барабаны (смена сессии/выход)."""
        self._spinning = False
        self._timer.stop()

    def show_placeholder(self) -> None:
        """Показывает "..." до начала генерации."""
        self._spinning = False
        self._placeholder = True
        self._chars = []
        self._timer.stop()
        self.update()

    def prepare_spin(self, expression: str) -> None:
        """Готовит барабаны под строку примера: подбирает шрифт, задаёт
        размер и показывает неподвижные ленты. Вызывается ДО полёта
        персонажа, чтобы зона генерации имела точную геометрию."""
        self._chars = list(expression)
        self._digit_idx = [i for i, ch in enumerate(self._chars) if ch.isdigit()]
        self._digit_set = set(self._digit_idx)
        self._bases = [self._rng.randrange(10) for _ in self._chars]
        self._locked = 0
        self._flash = {}
        self._placeholder = False
        self._spinning = False
        self._prepared = True        # барабаны готовы, генерация ещё не шла
        self._scroll = 0
        self._elapsed = 0
        # Ширина под выражение (с адаптивным уменьшением шрифта для длинных).
        px = 56
        while px > 32:
            fm = self._font_metrics(px)
            total = sum(fm.horizontalAdvance(c) for c in self._chars) + 20
            if total <= 940:
                break
            px -= 4
        fm = self._font_metrics(px)
        self._font.setPixelSize(px)
        self._fm = fm
        self._cell_h = int(fm.height() * 1.02)
        self.setFixedHeight(int(self._cell_h * 1.32))
        self.setFixedWidth(max(sum(fm.horizontalAdvance(c)
                                   for c in self._chars) + 20, 120))
        self.update()

    def begin_reels(self, interval_ms: int = 200) -> None:
        """Запускает прокрутку подготовленных барабанов."""
        if not self._chars:
            return
        self._interval_ms = max(60, int(interval_ms))
        self._lock_times = [self._interval_ms * (k + 1)
                            for k in range(len(self._digit_idx))]
        self._spinning = True
        self._prepared = False       # генерация началась: знаки и цифры видимы
        self._scroll = 0
        self._elapsed = 0
        self._clock.restart()
        if not self._digit_idx:
            # Вырожденный случай: цифр нет -- сразу готово.
            self._spinning = False
            QTimer.singleShot(80, self.locked_all.emit)
        else:
            self._timer.start(30)
        self.update()

    def start_spin(self, expression: str, interval_ms: int = 200) -> None:
        """prepare_spin + begin_reels одним вызовом."""
        self.prepare_spin(expression)
        self.begin_reels(interval_ms)

    def text(self) -> str:
        """Итоговая строка примера (или "..." до генерации)."""
        return "".join(self._chars) if self._chars else "…"

    @property
    def font_px(self) -> int:
        """Размер цифр на барабанах, px (для синхронизации поля ответа)."""
        return self._font.pixelSize()

    @property
    def cell_h(self) -> int:
        """Высота ячейки барабана, px."""
        return self._cell_h

    @property
    def spinning(self) -> bool:
        return self._spinning

    # ------------------------------------------------------------------
    def _font_metrics(self, pixel_size: int):
        f = QFont(self._font)
        f.setPixelSize(pixel_size)
        return QFontMetrics(f)

    def _update_locks(self, elapsed_ms: int) -> None:
        """Фиксирует барабаны, чьё время наступило (чистая логика --
        вызывается из таймера и доступна тестам)."""
        self._elapsed = elapsed_ms
        while (self._locked < len(self._digit_idx)
               and elapsed_ms >= self._lock_times[self._locked]):
            idx = self._digit_idx[self._locked]
            self._flash[idx] = elapsed_ms
            self._locked += 1
            self.reel_locked.emit(self._locked)
        if (self._digit_idx and self._locked >= len(self._digit_idx)
                and elapsed_ms >= self._lock_times[-1] + 140):
            self._spinning = False
            self._timer.stop()
            self.locked_all.emit()

    def _tick(self) -> None:
        self._scroll += self._speed
        self._update_locks(self._clock.elapsed())
        self.update()

    # ------------------------------------------------------------------
    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.setFont(self._font)
        fm = self._fm

        if self._placeholder:
            p.setPen(QColor(Palette.TEXT_MUTED))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "…")
            p.end()
            return

        total_w = sum(fm.horizontalAdvance(c) for c in self._chars)
        x = (self.width() - total_w) / 2.0
        cell_h = self._cell_h
        top = (self.height() - cell_h) / 2.0
        locked_set = set(self._digit_idx[:self._locked])
        elapsed = self._elapsed

        dark = QColor(Palette.TEXT_DARK)
        coral = QColor(Palette.CORAL)
        for i, ch in enumerate(self._chars):
            adv = fm.horizontalAdvance(ch)
            if i in self._digit_set and i not in locked_set and self._prepared:
                # --- Барабан-заготовка: ПУСТАЯ ячейка (только свод) ---
                # До начала генерации символов на барабанах не видно.
                cell = QRectF(x, top, adv, cell_h)
                shade = QLinearGradient(x, top, x, top + cell_h)
                shade.setColorAt(0.00, QColor(45, 58, 75, 95))
                shade.setColorAt(0.25, QColor(45, 58, 75, 0))
                shade.setColorAt(0.75, QColor(45, 58, 75, 0))
                shade.setColorAt(1.00, QColor(45, 58, 75, 95))
                p.fillRect(cell, QBrush(shade))
            elif i in self._digit_set and i not in locked_set:
                # --- Барабан: вертикальная лента цифр в ячейке ---
                cell = QRectF(x, top, adv, cell_h)
                p.save()
                p.setClipRect(cell)
                off = self._scroll % cell_h
                base = (self._bases[i] - self._scroll // cell_h) % 10
                p.setPen(QPen(coral))
                for row in range(-1, 3):
                    digit = self._seq_digit(base + row)
                    yy = top + row * cell_h - off
                    p.drawText(QRectF(x, yy, adv, cell_h),
                               Qt.AlignmentFlag.AlignCenter, digit)
                # Свод барабана: мягкое затемнение к краям ячейки.
                shade = QLinearGradient(x, top, x, top + cell_h)
                shade.setColorAt(0.00, QColor(45, 58, 75, 95))
                shade.setColorAt(0.25, QColor(45, 58, 75, 0))
                shade.setColorAt(0.75, QColor(45, 58, 75, 0))
                shade.setColorAt(1.00, QColor(45, 58, 75, 95))
                p.fillRect(cell, QBrush(shade))
                p.restore()
            elif i in self._digit_set:
                # --- Зафиксированная цифра (с короткой вспышкой) ---
                t = 1.0
                dy = 0.0
                if i in self._flash:
                    dt = elapsed - self._flash[i]
                    if dt < 130:
                        t = max(0.0, dt / 130.0)
                        dy = -(1.0 - t) * 5.0     # цифра "доседает" в паз
                color = _slot_lerp(coral, dark, t)
                p.setPen(QPen(color))
                p.drawText(QRectF(x, top + dy, adv, cell_h),
                           Qt.AlignmentFlag.AlignCenter, ch)
            elif self._prepared:
                # Знаки действий и скобки НЕВИДИМЫ до начала генерации;
                # после генерации (spinning/зафиксировано) -- видимы.
                pass
            else:
                # Знак действия / скобка -- стоит на месте.
                p.setPen(QPen(dark))
                p.drawText(QRectF(x, top, adv, cell_h),
                           Qt.AlignmentFlag.AlignCenter, ch)
            x += adv
        p.end()

    @staticmethod
    def _seq_digit(n: int) -> str:
        return str(n % 10)


def _slot_lerp(c1: QColor, c2: QColor, t: float) -> QColor:
    """Линейная интерполяция цветов (вспышка фиксации цифры)."""
    t = max(0.0, min(1.0, t))
    return QColor(int(c1.red() + (c2.red() - c1.red()) * t),
                  int(c1.green() + (c2.green() - c1.green()) * t),
                  int(c1.blue() + (c2.blue() - c1.blue()) * t))
