# -*- coding: utf-8 -*-
"""
Экран проверки: генерация примеров, ввод ответа, проверка и обратная связь.

Ключевые детали (по требованиям заказчика):
    * пример и поле ответа стоят в ОДНОЙ строке: "A + B = [поле ввода]";
      поле принимает до 10 символов;
    * перед генерацией персонаж подлетает к месту РЯДОМ с карточкой задания:
        - Фея Динь на крыльях, осыпая путь золотой пылью; у карточки бросает
          горсть волшебной пыли по крутой дуге -- на месте падения
          вырастает оседающее облако;
        - Боевой Прайм на реактивном ранце; у карточки стреляет реактивным
          снарядом из пушки на руке по настильной траектории -- взрыв
          и медленно оседающее облако дыма;
      как только появилось облако, персонаж возвращается на своё место и
      ОДНОВРЕМЕННО запускается генерация "однорукий бандит";
    * все эффекты (пыль, дым, взрыв, конфетти) -- шейдерные GPU-частицы
      (ModernGL); при недоступности OpenGL используется QPainter-оверлей;
    * интервал фиксации цифры -- 250 мс;
    * после ответа: строка "Правильный ответ", яркая анимация и реплика
      персонажа в облачке ("Ты молодец! Классно!" / "В следующий раз
      обязательно получится");
    * примеры не повторяются внутри сессии и в трёх ближайших сессиях.
"""
from __future__ import annotations

import math
import random
from typing import List, Optional, Set

from PySide6.QtCore import QEasingCurve, QPointF, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QIntValidator,
                            QPainter, QPen)
from PySide6.QtWidgets import (QFrame, QGraphicsDropShadowEffect, QHBoxLayout,
                                QLabel, QLineEdit, QPushButton, QVBoxLayout,
                                QWidget)

from animated_widgets import FeedbackWidget, SlotMachineLabel
from math_engine import MathEngine, Problem, check_answer
from ui_styles import Palette
from characters import make_character

try:
    from gl_characters import MagicFXOverlay, gl_available, make_character_view
except Exception:                                    # pragma: no cover
    MagicFXOverlay = None
    gl_available = None
    make_character_view = None


def _gl_ok() -> bool:
    """Ленивая проверка GL (проба требует уже созданный QApplication)."""
    if make_character_view is None or MagicFXOverlay is None:
        return False
    try:
        return bool(gl_available())
    except Exception:
        return False


def _qcolor(r: int, g: int, b: int, a: int = 255):
    """Создаёт QColor из RGBA."""
    from PySide6.QtGui import QColor as _QC
    return _QC(r, g, b, a)


# ---------------------------------------------------------------------------
#  Классический (QPainter) оверлей полёта -- резервный путь без OpenGL
# ---------------------------------------------------------------------------
class ClassicFlightOverlay(QWidget):
    """QPainter-версия полёта: та же последовательность, что и на GPU.

    Последовательность: подлёт рядом с карточкой -> бросок пыли по дуге или
    снаряд со взрывом -> оседающее облако (on_cloud: стартует генерация и
    возврат) -> возврат персонажа (on_done).
    """

    FLY_MS = 950
    RETURN_MS = 850
    DUST_T = 620          # мс полёта горсти пыли
    SHELL_T = 300         # мс полёта снаряда

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self._particles: List[dict] = []
        self._char: Optional[QWidget] = None
        self._kind = "fairy"
        self._on_cloud = None
        self._on_done = None
        self._active = False
        self._fly_anim = None
        self._shell_anim = None
        self._t = 0.0
        self._rng = random.Random()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def _after(self, ms: int, fn) -> None:
        """Отложенный вызов через QTimer-ребёнка: умирает вместе с
        оверлеем и не стреляет в удалённые C++ объекты."""
        t = QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(fn)
        t.timeout.connect(t.deleteLater)
        t.start(ms)

    def _live_char(self) -> bool:
        """Жив ли ещё виджет персонажа (не съеден ли deleteLater)."""
        if self._char is None:
            return False
        try:
            self._char.width()
            return True
        except RuntimeError:
            self._char = None
            return False

    # ------------------------------------------------------------------
    def begin(self, char: QWidget, start: QPoint, land: QPoint,
              card_center: QPoint, kind: str, on_cloud, on_done) -> None:
        self._char = char
        self._kind = kind
        self._on_cloud = on_cloud
        self._on_done = on_done
        self._target = QPointF(card_center)
        self._particles = []
        self._active = True
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        char.setParent(self)
        char.move(start)
        char.show()
        self._start_topleft = QPoint(start)
        self._start_pos = QPointF(start) + QPointF(char.width() / 2,
                                                   char.height() / 2)
        self._char_half = char.width() / 2 * 0.92
        ctrl = QPointF((start.x() + land.x()) / 2,
                       min(start.y(), land.y()) - 120)
        self._run_arc(QPointF(start), QPointF(land), ctrl, self.FLY_MS,
                      self._arrived)

    def _run_arc(self, a: QPointF, b: QPointF, ctrl: QPointF, ms: int,
                 done, returning: bool = False) -> None:
        anim = QEasingCurveWrap(self, ms)
        anim.step = lambda t: self._place(a, b, ctrl, t)
        anim.finished.connect(done)
        anim.start()
        self._fly_anim = anim

    def _place(self, a: QPointF, b: QPointF, ctrl: QPointF, t: float) -> None:
        mt = 1.0 - t
        x = mt * mt * a.x() + 2 * mt * t * ctrl.x() + t * t * b.x()
        y = mt * mt * a.y() + 2 * mt * t * ctrl.y() + t * t * b.y()
        if self._live_char():
            self._char.move(int(x), int(y))
            self._trail(x + self._char.width() / 2,
                        y + self._char.height() / 2)

    def _trail(self, cx: float, cy: float) -> None:
        """След: искры феи / пламя и дым ранца Прайма."""
        if self._kind == "fairy":
            for _ in range(2):
                self._particles.append(self._mk_pt(
                    cx + self._rng.uniform(-12, 12), cy + self._rng.uniform(-10, 10),
                    self._rng.uniform(-14, 14), self._rng.uniform(-8, 24),
                    0.7, self._rng.uniform(4, 9), QColor(255, 230, 130)))
        else:
            fy = cy + self._char_half * 0.9
            for _ in range(2):
                self._particles.append(self._mk_pt(
                    cx + self._rng.uniform(-8, 8), fy,
                    self._rng.uniform(-10, 10), self._rng.uniform(30, 110),
                    0.35, self._rng.uniform(6, 12),
                    QColor(self._rng.choice(["#FF9F45", "#FFD54F", "#5BC8D6"]))))
            self._particles.append(self._mk_pt(
                cx + self._rng.uniform(-8, 8), fy + 6,
                self._rng.uniform(-8, 8), self._rng.uniform(15, 50),
                1.1, self._rng.uniform(10, 16), QColor(150, 160, 175, 150),
                smoke=True))

    @staticmethod
    def _mk_pt(x, y, vx, vy, life, size, color, smoke=False, ring=False):
        return {"x": x, "y": y, "vx": vx, "vy": vy, "life": life,
                "size": size, "color": QColor(color), "smoke": smoke,
                "ring": ring, "rot": 0.0,
                "spin": 0.0 if not ring else 0.0}

    def _arrived(self) -> None:
        if self._kind == "fairy":
            hand = QPointF(self._char_center().x() + 40,
                           self._char_center().y() - 26)
            self._throw_dust(hand)
            self._after(self.DUST_T, lambda: self._settle_cloud(
                golden=True))
        else:
            arm = QPointF(self._char_center().x() + 30,
                          self._char_center().y() + 22)
            self._fire_shell(arm)

    def _char_center(self) -> QPointF:
        if not self._live_char():
            return QPointF(self._target)
        return QPointF(self._char.x() + self._char.width() / 2,
                       self._char.y() + self._char.height() / 2)

    def _throw_dust(self, hand: QPointF) -> None:
        """Горсть пыли по крутой дуге в центр карточки."""
        T = self.DUST_T / 1000.0
        g = 500.0
        for _ in range(80):
            jitter = self._rng.uniform(-26, 26)
            dx = self._target.x() + jitter - hand.x()
            dy = self._target.y() + self._rng.uniform(-16, 16) - hand.y()
            vx = dx / T
            vy = (dy - 0.5 * g * T * T) / T
            self._particles.append(self._mk_pt(
                hand.x(), hand.y(), vx, vy, T + self._rng.uniform(0, 0.1),
                self._rng.uniform(3, 7),
                QColor(self._rng.choice(["#FFE678", "#FFD54F", "#FFF3B0",
                                         "#F0C8F5"])), smoke=True))

    def _fire_shell(self, arm: QPointF) -> None:
        anim = QEasingCurveWrap(self, self.SHELL_T)
        state = {"prev": QPointF(arm)}

        def step(t: float) -> None:
            x = arm.x() + (self._target.x() - arm.x()) * t
            y = arm.y() + (self._target.y() - arm.y()) * t \
                - 26 * math.sin(math.pi * t)
            self._shell_pos = QPointF(x, y)
            self._particles.append(self._mk_pt(
                x, y, self._rng.uniform(-16, 16), self._rng.uniform(-8, 8),
                0.4, self._rng.uniform(4, 8), QColor(255, 180, 90)))

        anim.step = step
        anim.finished.connect(lambda: self._explode())
        anim.start()
        self._shell_anim = anim

    def _explode(self) -> None:
        for _ in range(3):
            self._particles.append(self._mk_pt(
                self._target.x(), self._target.y(), 0, 0, 0.25, 80,
                QColor(255, 244, 200)))
        self._particles.append(self._mk_pt(
            self._target.x(), self._target.y(), 0, 0, 0.55, 100,
            QColor(255, 190, 90), ring=True))
        for _ in range(40):
            ang = self._rng.uniform(0, math.tau)
            speed = self._rng.uniform(100, 520)
            self._particles.append(self._mk_pt(
                self._target.x(), self._target.y(),
                math.cos(ang) * speed, math.sin(ang) * speed - 100,
                self._rng.uniform(0.7, 1.2), self._rng.uniform(4, 9),
                QColor(self._rng.choice(["#FF5E5B", "#FF9F45", "#FFD54F",
                                         "#9AA3B2"]))))
        self._after(120, lambda: self._settle_cloud(golden=False))

    def _settle_cloud(self, golden: bool) -> None:
        """Оседающее облако; одновременно стартует генерация и возврат."""
        palette = ([QColor(255, 235, 158, 150), QColor(255, 224, 128, 130),
                    QColor(240, 200, 245, 120)] if golden else
                   [QColor(110, 114, 124, 140), QColor(140, 145, 155, 120),
                    QColor(90, 94, 104, 150)])
        for i in range(30):
            ang = self._rng.uniform(0, math.tau)
            r = 18 + (i % 5) * 13
            self._particles.append(self._mk_pt(
                self._target.x() + math.cos(ang) * r * 0.5,
                self._target.y() + math.sin(ang) * r * 0.36,
                math.cos(ang) * self._rng.uniform(4, 20),
                math.sin(ang) * self._rng.uniform(3, 14),
                self._rng.uniform(2.0, 2.9), self._rng.uniform(26, 58),
                self._rng.choice(palette), smoke=True))
        if self._on_cloud is not None:
            self._on_cloud()
            self._on_cloud = None
        # Возврат персонажа в исходный угол.
        end = QPointF(self._start_topleft)
        ctrl = QPointF((self._char_center().x() + end.x()) / 2,
                       min(self._char_center().y(), end.y()) - 130)
        self._run_return(end, ctrl)

    def _run_return(self, end: QPointF, ctrl: QPointF) -> None:
        start = QPointF(self._char.x(), self._char.y()) if self._char else end

        def place(t: float) -> None:
            mt = 1.0 - t
            x = mt * mt * start.x() + 2 * mt * t * ctrl.x() + t * t * end.x()
            y = mt * mt * start.y() + 2 * mt * t * ctrl.y() + t * t * end.y()
            if self._live_char():
                self._char.move(int(x), int(y))
                self._trail(x + self._char.width() / 2,
                            y + self._char.height() / 2)

        anim = QEasingCurveWrap(self, self.RETURN_MS)
        anim.step = place
        anim.finished.connect(self._flight_done)
        anim.start()
        self._fly_anim = anim

    def _flight_done(self) -> None:
        self._active = False
        if self._on_done is not None:
            self._on_done()
            self._on_done = None

    def abort(self) -> None:
        if self._fly_anim is not None:
            self._fly_anim.stop()
        if self._shell_anim is not None:
            self._shell_anim.stop()
        self._fly_anim = self._shell_anim = None
        self._on_cloud = None
        self._on_done = None
        self._char = None              # виджет мог быть удалён deleteLater
        self._active = False
        self._timer.stop()
        self.hide()

    # ------------------------------------------------------------------
    def _tick(self) -> None:
        self._t += 0.03
        alive = []
        for pt in self._particles:
            pt["x"] += pt["vx"] * 0.03
            pt["y"] += pt["vy"] * 0.03
            if pt.get("smoke"):
                pt["vx"] *= 0.94
                pt["vy"] = pt["vy"] * 0.94 + 1.2     # оседание
                pt["size"] += 0.35
            else:
                pt["vy"] += 14.0
            pt["life"] -= 0.03
            if pt["life"] > 0:
                alive.append(pt)
        self._particles = alive
        self.update()
        if not alive and not self._active:
            self._timer.stop()
            self.hide()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        if not self._particles:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for pt in self._particles:
            c = QColor(pt["color"])
            c.setAlpha(int(255 * min(1.0, pt["life"] / 0.8)))
            size = pt["size"] * (0.6 + 0.4 * min(1.0, pt["life"]))
            p.setPen(Qt.PenStyle.NoPen)
            if pt.get("ring"):
                rr = (1.0 - pt["life"] / 0.55) * 80 + 10
                ring_c = QColor(255, 190, 90, int(190 * pt["life"] / 0.55))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(ring_c, 4, Qt.PenStyle.DotLine))
                p.drawEllipse(pt["x"], pt["y"], rr, rr)
                continue
            p.setBrush(c)
            p.drawEllipse(QPointF(pt["x"], pt["y"]), size / 2, size / 2)
        p.end()

    def start_anim_timer(self) -> None:
        self._timer.start(30)


class QEasingCurveWrap:
    """Обёртка анимации для классического оверлея (совместимость по API)."""

    def __init__(self, parent, ms: int):
        from PySide6.QtCore import QVariantAnimation
        self._anim = QVariantAnimation(parent)
        self._anim.setDuration(ms)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.valueChanged.connect(lambda v: self.step(float(v)))
        self.step = lambda t: None
        self.finished = self._anim.finished

    def start(self) -> None:
        self._anim.start()

    def stop(self) -> None:
        self._anim.stop()


# ---------------------------------------------------------------------------
#  Экран проверки
# ---------------------------------------------------------------------------
class QuizScreen(QWidget):
    """Экран решения примеров.

    Сигналы:
        session_finished -- (total, correct, problems) при завершении;
        back_requested   -- возврат на стартовый экран.
    """

    session_finished = Signal(int, int, list)
    back_requested = Signal()

    # Реплики персонажа.
    PHRASE_CORRECT = "Ты молодец! Классно!"
    PHRASE_WRONG = "В следующий раз обязательно получится"

    # Интервал фиксации цифры на барабанах автомата (мс).
    SLOT_INTERVAL_MS = 200

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._engine: Optional[MathEngine] = None
        self._problem: Optional[Problem] = None
        self._total = 0
        self._correct = 0
        self._character_key = "fairy"
        self._character_widget: Optional[QWidget] = None
        self._char_placeholder: Optional[QWidget] = None
        self._answered = False
        self._rng = random.Random()
        self._build_ui()

    # ------------------------------------------------------------------
    #  Интерфейс
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(12)

        # Верхняя панель: счётчик и кнопка завершения.
        top = QHBoxLayout()
        self._progress_label = QLabel("Решено: 0  |  Верно: 0")
        self._progress_label.setObjectName("SubtitleLabel")
        top.addWidget(self._progress_label)
        top.addStretch(1)

        self._finish_btn = QPushButton("🏁 Закончить проверку")
        self._finish_btn.setObjectName("DangerButton")
        self._finish_btn.clicked.connect(self._on_finish)
        top.addWidget(self._finish_btn)
        root.addLayout(top)

        # Центральная карточка с примером.
        self._problem_card = QFrame()
        self._problem_card.setObjectName("ProblemCard")
        self._problem_card.setMinimumHeight(250)
        shadow = QGraphicsDropShadowEffect(self._problem_card)
        shadow.setBlurRadius(30)
        shadow.setOffset(0, 6)
        shadow.setColor(_qcolor(0, 0, 0, 70))
        self._problem_card.setGraphicsEffect(shadow)

        card_layout = QVBoxLayout(self._problem_card)
        card_layout.setSpacing(10)
        card_layout.setContentsMargins(30, 26, 30, 22)

        # --- Строка примера: "A + B" "=" "[поле ввода]" на одном уровне ---
        row = QHBoxLayout()
        row.setSpacing(14)
        row.addStretch(1)

        # Строка примера -- экран автомата "однорукий бандит": цифры
        # крутятся в вертикальных барабанах и фиксируются слева направо.
        self._expr_label = SlotMachineLabel()
        self._expr_label.locked_all.connect(self._finish_slot_animation)
        row.addWidget(self._expr_label, 0, Qt.AlignmentFlag.AlignVCenter)

        eq = QLabel("=")
        eq.setObjectName("ProblemLabel")
        eq.setAlignment(Qt.AlignmentFlag.AlignCenter)
        eq.setMinimumHeight(84)
        row.addWidget(eq)

        # Поле ввода ответа: до 10 символов, крупное, в строке примера.
        self._answer_edit = QLineEdit()
        # До 10 символов: QRegularExpressionValidator (QIntValidator
        # ограничен 32-битным int и не пропустил бы десятую цифру).
        from PySide6.QtGui import QRegularExpressionValidator
        from PySide6.QtCore import QRegularExpression
        self._answer_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"\d{1,10}")))
        self._answer_edit.setPlaceholderText("ответ")
        self._answer_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._answer_edit.setMaxLength(10)
        f = QFont("Comic Sans MS")
        f.setPointSize(30)
        f.setWeight(QFont.Weight.Black)
        self._answer_edit.setFont(f)
        fm = QFontMetrics(f)
        self._answer_edit.setFixedWidth(fm.horizontalAdvance("0" * 10) + 36)
        self._answer_edit.setFixedHeight(70)
        self._answer_edit.returnPressed.connect(self._on_submit)
        self._answer_edit.setEnabled(False)
        row.addWidget(self._answer_edit)
        row.addStretch(1)
        card_layout.addLayout(row)

        # Строка "Правильный ответ".
        self._correct_label = QLabel()
        self._correct_label.setObjectName("CorrectAnswerLabel")
        self._correct_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self._correct_label)

        # Яркая анимированная оценка ответа.
        self._feedback = FeedbackWidget(self._problem_card)
        card_layout.addWidget(self._feedback, stretch=1)

        root.addWidget(self._problem_card, stretch=1)

        # Персонаж слева, кнопки снизу.
        self._bottom_layout = QHBoxLayout()
        if _gl_ok() and make_character_view is not None:
            self._character_widget = make_character_view("fairy", self, 200)
        else:
            self._character_widget = make_character("fairy", self, 200)
        self._bottom_layout.addWidget(self._character_widget,
                                      alignment=Qt.AlignmentFlag.AlignBottom)
        self._bottom_layout.addStretch(1)
        btn_col = QVBoxLayout()

        self._submit_btn = QPushButton("✅ Проверить ответ")
        self._submit_btn.setObjectName("PrimaryButton")
        self._submit_btn.clicked.connect(self._on_submit)
        btn_col.addWidget(self._submit_btn)

        self._next_btn = QPushButton("➡️ Следующий пример")
        self._next_btn.setObjectName("NextButton")
        self._next_btn.clicked.connect(self._next_problem)
        self._next_btn.setEnabled(False)
        btn_col.addWidget(self._next_btn)
        self._bottom_layout.addLayout(btn_col)
        root.addLayout(self._bottom_layout)

        # Облачко с репликой персонажа.
        self._bubble = QLabel(self)
        self._bubble.setWordWrap(True)
        self._bubble.setStyleSheet(
            "QLabel { background: #FFFFFF; border-radius: 16px; "
            "border: 3px solid #5BA8D6; padding: 10px 16px; "
            "font-size: 19px; font-weight: 800; color: #2D3A4B; }")
        self._bubble.adjustSize()
        self._bubble.hide()
        self._bubble_timer = QTimer(self)
        self._bubble_timer.setSingleShot(True)
        self._bubble_timer.timeout.connect(self._bubble.hide)

        # Оверлеи: GPU (ModernGL) или классический QPainter.
        if _gl_ok() and MagicFXOverlay is not None:
            self._fx = MagicFXOverlay(self)
            self._flight = None
        else:
            self._fx = None
            self._flight = ClassicFlightOverlay(self)
        # Конфетти-оверлей для классического пути.
        if self._fx is None:
            from animated_widgets import SparklesOverlay
            self._sparkles = SparklesOverlay(self)
        else:
            self._sparkles = None

    # ------------------------------------------------------------------
    #  Управление сессией
    # ------------------------------------------------------------------
    def start_session(self, grade: int, character_key: str,
                      recent: Optional[Set[str]] = None) -> None:
        """Начинает новую сессию проверки для указанного класса."""
        self._cleanup_flight()
        self._expr_label.stop()
        self._engine = MathEngine(grade, recent=recent)
        self._character_key = character_key
        # GL-виджет переиспользуем: смена персонажа без нового GL-контекста
        # (пересоздание контекстов течёт на части драйверов).
        from gl_characters import GLCharacterWidget as _GLW
        if isinstance(self._character_widget, _GLW):
            self._character_widget.set_character(character_key)
        elif self._character_widget is not None:
            self._bottom_layout.removeWidget(self._character_widget)
            # Явно освобождаем GL-ресурсы ДО удаления виджета: в общей
            # share-группе "недоудалённые" объекты живут до конца процесса.
            cleanup = getattr(self._character_widget, "_cleanup_gl", None)
            if cleanup is not None:
                cleanup()
            self._character_widget.setParent(None)
            self._character_widget.deleteLater()
            self._character_widget = None
        if self._character_widget is None:
            if _gl_ok() and make_character_view is not None:
                self._character_widget = make_character_view(character_key, self, 200)
            else:
                self._character_widget = make_character(character_key, self, 200)
            self._bottom_layout.insertWidget(
                0, self._character_widget,
                alignment=Qt.AlignmentFlag.AlignBottom)
        self._total = 0
        self._correct = 0
        self._update_progress()
        self._next_problem()

    @property
    def used_problems(self) -> List[str]:
        return self._engine.used_problems if self._engine else []

    def _next_problem(self) -> None:
        """Генерирует новый пример: персонаж летит к карточке, бросает
        пыль/стреляет, появляется облако -- и стартует "барабан"."""
        if self._engine is None:
            return
        self._answered = False
        self._problem = self._engine.next_problem()

        self._answer_edit.clear()
        self._answer_edit.setEnabled(False)
        self._correct_label.setText("")
        self._feedback.clear()
        self._bubble.hide()
        self._bubble.setText("")
        self._next_btn.setEnabled(False)
        self._submit_btn.setEnabled(False)
        # Готовим барабаны сразу: зона генерации получает точную геометрию
        # ещё до полёта -- персонаж садится у начала строки, а не "где-то".
        self._expr_label.prepare_spin(self._problem.display[:-2])
        self._sync_answer_font()
        QTimer.singleShot(60, self._begin_flight)

    def _sync_answer_font(self) -> None:
        """Размер символов в поле ответа -- как размер цифр на барабанах."""
        px = self._expr_label.font_px
        f = QFont("Comic Sans MS")
        f.setPixelSize(px)
        f.setWeight(QFont.Weight.Black)
        self._answer_edit.setFont(f)
        fm = QFontMetrics(f)
        self._answer_edit.setFixedWidth(fm.horizontalAdvance("0" * 10) + 36)
        self._answer_edit.setFixedHeight(int(self._expr_label.cell_h * 1.18))

    # ------------------------------------------------------------------
    #  Полёт персонажа к карточке задания
    # ------------------------------------------------------------------
    def _flight_targets(self) -> tuple:
        """(старт, посадка у НАЧАЛА строки, центр зоны генерации,
        (ширина, высота) зоны строки примера)."""
        char = self._character_widget
        start = char.mapTo(self, char.rect().topLeft())
        card = self._problem_card.mapTo(self, self._problem_card.rect().topLeft())
        cw, ch = char.width(), char.height()
        # Строка примера -- зона генерации задания.
        expr = self._expr_label.mapTo(self, self._expr_label.rect().topLeft())
        ew = max(self._expr_label.width(), 160)
        eh = max(self._expr_label.height(), 60)
        zone_center = QPoint(expr.x() + ew // 2, expr.y() + eh // 2)
        # Посадка: слева от начала строки, на уровне строки -- персонаж
        # оказывается прямо у места генерации, а не в центре карточки.
        land = QPoint(max(cw // 2, expr.x() - int(cw * 0.38)),
                      zone_center.y())
        land.setX(min(land.x(), self.width() - cw // 2))
        land.setY(max(ch // 2, min(land.y(), self.height() - ch // 2)))
        return start, land, zone_center, (ew, eh)

    def _begin_flight(self) -> None:
        if self._problem is None or self._character_widget is None:
            return
        # Если прошлый полёт не успел завершиться -- прибираем за ним.
        if self._char_placeholder is not None:
            self._cleanup_flight()
        char = self._character_widget
        # Держим место в макете, пока персонаж в полёте.
        self._char_placeholder = QWidget()
        self._char_placeholder.setFixedSize(char.size())
        self._bottom_layout.replaceWidget(char, self._char_placeholder)

        start, land, zone_center, zone_size = self._flight_targets()

        if self._fx is not None:
            # GPU-путь: живой персонаж прячется, летит его текстурный слепок.
            # Снимок берём ДО hide(): у скрытого GL-виджета он пустой.
            snapshot = char.grab().toImage()
            char.hide()
            self._fx.begin_flight(
                self._character_key, snapshot,
                QPointF(start + QPoint(char.width() // 2, char.height() // 2)),
                QPointF(land), QPointF(zone_center), zone_size,
                on_cloud=self._start_slot_animation,
                on_done=self._restore_character)
        else:
            # Классический путь: точки -- левый верхний угол персонажа.
            land_topleft = land - QPoint(char.width() // 2, char.height() // 2)
            self._flight.begin(
                char, start, land_topleft, zone_center, self._character_key,
                on_cloud=self._start_slot_animation,
                on_done=self._restore_character)
            self._flight.start_anim_timer()

    def _restore_character(self) -> None:
        """Возвращает персонажа на место после полёта."""
        if self._char_placeholder is None or self._character_widget is None:
            return
        char = self._character_widget
        if char.parent() is not self:
            char.setParent(self)
        char.show()
        self._bottom_layout.replaceWidget(self._char_placeholder, char)
        self._char_placeholder.deleteLater()
        self._char_placeholder = None

    def _cleanup_flight(self) -> None:
        """Принудительно завершает полёт (смена сессии, выход)."""
        if self._fx is not None:
            self._fx.abort()
        if self._flight is not None:
            self._flight.abort()
        if self._char_placeholder is not None:
            self._restore_character()

    # ------------------------------------------------------------------
    #  Анимация "однорукий бандит"
    # ------------------------------------------------------------------
    def _start_slot_animation(self) -> None:
        """Запускает прокрутку подготовленных барабанов (параллельно с
        возвратом персонажа): цифры фиксируются слева направо каждые
        SLOT_INTERVAL_MS (~200 мс)."""
        self._expr_label.begin_reels(self.SLOT_INTERVAL_MS)

    def _finish_slot_animation(self) -> None:
        """Все барабаны зафиксированы: включаем ввод ответа."""
        self._answer_edit.setEnabled(True)
        self._submit_btn.setEnabled(True)
        self._answer_edit.setFocus()

    # ------------------------------------------------------------------
    #  Проверка ответа
    # ------------------------------------------------------------------
    def _on_submit(self) -> None:
        if self._answered or self._problem is None:
            return
        if not self._answer_edit.isEnabled():
            return
        text = self._answer_edit.text().strip()
        if not text:
            self._answer_edit.setFocus()
            return
        try:
            user_answer = int(text)
        except ValueError:
            return

        self._answered = True
        self._answer_edit.setEnabled(False)
        self._submit_btn.setEnabled(False)
        self._next_btn.setEnabled(True)
        self._next_btn.setFocus()

        is_correct = check_answer(self._problem, user_answer)
        self._total += 1
        if is_correct:
            self._correct += 1

        self._correct_label.setText(
            f"Правильный ответ: {self._problem.answer}")
        self._feedback.show_feedback(is_correct)

        # Объёмные эффекты: GPU-частицы или классическое конфетти.
        center = self._feedback.mapTo(self, self._feedback.rect().center())
        if self._fx is not None:
            self._fx.burst(is_correct, center.x(), center.y())
        elif self._sparkles is not None:
            self._sparkles.setGeometry(self.rect())
            self._sparkles.raise_()
            self._sparkles.burst(correct=is_correct)

        self._show_bubble(self.PHRASE_CORRECT if is_correct else self.PHRASE_WRONG)
        self._update_progress()

    def _show_bubble(self, text: str) -> None:
        """Облачко с репликой персонажа."""
        self._bubble.setText(text)
        self._bubble.adjustSize()
        char_h = self._character_widget.height() if self._character_widget else 200
        x = 26
        y = max(12, self.height() - char_h - self._bubble.height() - 70)
        self._bubble.move(x, y)
        self._bubble.show()
        self._bubble.raise_()
        self._bubble_timer.start(2800)

    def _update_progress(self) -> None:
        self._progress_label.setText(
            f"Решено: {self._total}  |  Верно: {self._correct}")

    def _on_finish(self) -> None:
        self._cleanup_flight()
        if self._total == 0:
            self.back_requested.emit()
            return
        self.session_finished.emit(self._total, self._correct,
                                   self.used_problems)
