# -*- coding: utf-8 -*-
"""
Окно статистики и итоговая оценка сессии.

Два класса:
    * ``StatsWindow`` -- полноценное отдельное окно (QMainWindow): его можно
      перетаскивать, распахивать на весь экран и менять размер. Внутри --
      все метрики за сессию и за класс, таблица всех сессий и график
      прогресса оценок (QtCharts). Окно полностью непрозрачное;
    * ``SessionResultDialog`` -- модальный диалог с крупной анимированной
                                 оценкой за завершённую сессию.
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCharts import (QBarCategoryAxis, QBarSeries, QBarSet, QChart,
                               QChartView, QLineSeries, QValueAxis)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QDialog, QFrame, QGridLayout,
                                QGroupBox, QHBoxLayout, QLabel, QMainWindow,
                                QPushButton, QScrollArea, QTableWidget,
                                QTableWidgetItem, QVBoxLayout, QWidget)

from animated_widgets import GradeBadge
from ui_styles import Palette


# ---------------------------------------------------------------------------
#  Окно статистики (полноценное отдельное окно)
# ---------------------------------------------------------------------------
class StatsWindow(QMainWindow):
    """Отдельное окно со статистикой по выбранному классу и графиком.

    Создаётся без родителя, поэтому ведёт себя как обычное окно операционной
    системы: перетаскивается за заголовок, разворачивается, меняет размер.
    """

    def __init__(self, stats_manager, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("StatsRoot")
        self.setWindowTitle("📊 Моя статистика")
        self.setMinimumSize(820, 600)
        self.resize(1020, 760)
        # Полностью непрозрачное окно с плотным фоном.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QMainWindow#StatsRoot {{ background: {Palette.BG_MINT}; }}")

        self._stats = stats_manager
        self._name: Optional[str] = None
        self._age = 8
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        # Всё содержимое -- в область прокрутки, чтобы при любом размере
        # окна были видны все строки статистики.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        content = QWidget()
        content.setMinimumWidth(760)
        content.setStyleSheet("background: transparent;")
        root = QVBoxLayout(content)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        title = QLabel("📊 Моя статистика")
        title.setObjectName("TitleLabel")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)

        # --- Панель выбора класса --------------------------------------
        selector = QHBoxLayout()
        grade_caption = QLabel("Класс:")
        grade_caption.setStyleSheet(
            f"font-size: 20px; font-weight: 800; color: {Palette.TEXT_DARK};")
        selector.addWidget(grade_caption)
        self._grade_combo = QComboBox()
        self._grade_combo.setMinimumWidth(160)
        self._grade_combo.currentIndexChanged.connect(self._refresh)
        selector.addWidget(self._grade_combo)
        selector.addStretch(1)
        self._close_btn = QPushButton("✖  Закрыть")
        self._close_btn.setObjectName("DangerButton")
        # Яркий явный стиль: кнопка видна всегда, независимо от темы.
        self._close_btn.setStyleSheet(
            f"QPushButton {{ background-color: {Palette.ERROR}; color: white;"
            "  border: none; border-radius: 20px; padding: 12px 26px;"
            "  font-size: 19px; font-weight: 800; }"
            f"QPushButton:hover {{ background-color: #E85555; }}")
        self._close_btn.setMinimumWidth(180)
        self._close_btn.setMinimumHeight(52)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setToolTip("Закрыть окно статистики")
        self._close_btn.clicked.connect(self.close)
        selector.addWidget(self._close_btn)
        root.addLayout(selector)

        # --- Метрики текущего класса (все восемь строк) ------------------
        self._metrics_box = QGroupBox("📋 Показатели")
        metrics_grid = QGridLayout(self._metrics_box)
        metrics_grid.setVerticalSpacing(8)
        self._metric_labels = {}
        metrics: List[tuple] = [
            ("session_total", "Ответов за сессию"),
            ("session_correct", "Верных за сессию"),
            ("session_wrong", "Неверных за сессию"),
            ("session_grade", "Оценка за сессию"),
            ("class_total", "Всего ответов (класс)"),
            ("class_correct", "Верных ответов (класс)"),
            ("class_wrong", "Неверных ответов (класс)"),
            ("class_grade", "Оценка за класс"),
        ]
        # Один столбец на группу, чтобы все строки были видны компактно.
        for i, (key, label) in enumerate(metrics):
            r, c = i % 4, (i // 4) * 2
            caption = QLabel(f"{label}:")
            caption.setStyleSheet(
                f"font-size: 17px; font-weight: 700; color: {Palette.TEXT_DARK};")
            val = QLabel("—")
            val.setStyleSheet(
                f"font-size: 21px; font-weight: 900; color: {Palette.MINT};")
            metrics_grid.addWidget(caption, r, c)
            metrics_grid.addWidget(val, r, c + 1)
            self._metric_labels[key] = val
        root.addWidget(self._metrics_box)

        # --- График прогресса оценок -------------------------------------
        chart_box = QGroupBox("📈 Прогресс оценок по сессиям")
        chart_layout = QVBoxLayout(chart_box)
        self._chart_view = QChartView()
        self._chart_view.setMinimumHeight(300)
        self._chart_view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Непрозрачный белый фон под графиком.
        self._chart_view.setChart(QChart())
        chart_layout.addWidget(self._chart_view)
        root.addWidget(chart_box)

        # --- Таблица всех сессий -----------------------------------------
        table_box = QGroupBox("🗂 Все сессии")
        table_layout = QVBoxLayout(table_box)
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["№", "Дата", "Ответов", "Верных", "Оценка"])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setMinimumHeight(200)
        table_layout.addWidget(self._table)
        root.addWidget(table_box)

        scroll.setWidget(content)
        self.setCentralWidget(scroll)

    # ------------------------------------------------------------------
    #  Обновление данных
    # ------------------------------------------------------------------
    def load_user(self, name: str, age: int, current_grade: int) -> None:
        """Загружает пользователя и показывает статистику выбранного класса."""
        self._name = name
        self._age = age
        data = self._stats.get_user(name, age)
        grades = sorted(int(g) for g in data.get("grades", {}).keys())
        if not grades:
            grades = [current_grade]
        self._grade_combo.blockSignals(True)
        self._grade_combo.clear()
        for g in grades:
            self._grade_combo.addItem(f"{g} класс", g)
        idx = self._grade_combo.findData(current_grade)
        self._grade_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._grade_combo.blockSignals(False)
        self._refresh()

    def _refresh(self) -> None:
        """Перерисовывает метрики, график и таблицу по выбранному классу."""
        if self._name is None or self._grade_combo.count() == 0:
            return
        grade = self._grade_combo.currentData()
        block = self._stats.get_stats(self._name, grade)
        if not block:
            for lbl in self._metric_labels.values():
                lbl.setText("—")
            self._table.setRowCount(0)
            self._chart_view.setChart(QChart())
            return

        # Метрики. Последняя сессия -- "текущая".
        sessions = block.get("sessions", [])
        last = sessions[-1] if sessions else {}
        self._metric_labels["session_total"].setText(
            str(last.get("total_answers", 0)))
        self._metric_labels["session_correct"].setText(
            str(last.get("correct_answers", 0)))
        self._metric_labels["session_wrong"].setText(
            str(last.get("wrong_answers", 0)))
        sg = last.get("grade")
        self._metric_labels["session_grade"].setText(str(sg) if sg else "—")
        self._metric_labels["class_total"].setText(
            str(block.get("total_answers", 0)))
        self._metric_labels["class_correct"].setText(
            str(block.get("correct_answers", 0)))
        self._metric_labels["class_wrong"].setText(
            str(block.get("wrong_answers", 0)))
        cg = block.get("grade")
        self._metric_labels["class_grade"].setText(str(cg) if cg else "—")

        # Таблица всех сессий.
        self._table.setRowCount(len(sessions))
        for i, s in enumerate(sessions):
            vals = [str(i + 1), s.get("date", ""),
                    str(s.get("total_answers", 0)),
                    str(s.get("correct_answers", 0)),
                    str(s.get("grade") or "—")]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._table.setItem(i, col, item)
        self._table.resizeColumnsToContents()

        # График.
        self._draw_chart(sessions)

    def _draw_chart(self, sessions: list) -> None:
        """Рисует график оценок по сессиям (требование 3.11)."""
        chart = QChart()
        chart.setTitle("Оценки по сессиям")
        chart.setTitleFont(QFont("Comic Sans MS", 14, QFont.Weight.Bold))
        chart.legend().setVisible(True)
        chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
        # Плотный белый фон диаграммы (никакой прозрачности).
        chart.setBackgroundBrush(QColor("#FFFFFF"))
        chart.setPlotAreaBackgroundVisible(True)
        chart.setPlotAreaBackgroundBrush(QColor("#FBFDFE"))

        series = QLineSeries()
        series.setName("Оценка")
        pen = QPen(QColor(Palette.CORAL))
        pen.setWidth(3)
        series.setPen(pen)
        bar_set = QBarSet("Оценка")
        bar_set.setColor(QColor(Palette.MINT))
        categories = []
        has_data = False
        for i, s in enumerate(sessions):
            g = s.get("grade")
            categories.append(f"#{i + 1}")
            if g is not None:
                series.append(i, float(g))
                bar_set.append(float(g))
                has_data = True
            else:
                bar_set.append(0.0)

        if not has_data:
            self._chart_view.setChart(chart)
            return

        # Столбчатая диаграмма + линия тренда поверх.
        bar_series = QBarSeries()
        bar_series.append(bar_set)
        chart.addSeries(bar_series)
        chart.addSeries(series)

        axis_x = QBarCategoryAxis()
        axis_x.append(categories)
        axis_x.setTitleText("Сессия")
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        bar_series.attachAxis(axis_x)
        series.attachAxis(axis_x)

        axis_y = QValueAxis()
        axis_y.setRange(1, 5)
        axis_y.setTickCount(5)
        axis_y.setTitleText("Оценка")
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        bar_series.attachAxis(axis_y)
        series.attachAxis(axis_y)

        chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
        self._chart_view.setChart(chart)


# ---------------------------------------------------------------------------
#  Диалог итоговой оценки за сессию
# ---------------------------------------------------------------------------
class SessionResultDialog(QDialog):
    """Модальный диалог с крупной анимированной оценкой за сессию."""

    def __init__(self, session_grade: Optional[int],
                 class_grade: Optional[float],
                 total: int, correct: int,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Оценка за сессию")
        self.setMinimumSize(480, 560)
        self._build(session_grade, class_grade, total, correct)

    def _build(self, session_grade, class_grade, total, correct) -> None:
        from PySide6.QtCore import QTimer

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel("🎉 Сессия завершена!")
        title.setObjectName("TitleLabel")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Бейдж с оценкой.
        self._badge = GradeBadge(self)
        layout.addWidget(self._badge, alignment=Qt.AlignmentFlag.AlignCenter)

        if session_grade is None:
            placeholder = QLabel("Нет данных для оценки")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(placeholder)

        # Текстовая сводка.
        summary = QLabel(
            f"Верных ответов: <b>{correct}</b> из <b>{total}</b><br>"
            f"Средняя оценка по классу: "
            f"<b>{class_grade if class_grade is not None else '—'}</b>")
        summary.setTextFormat(Qt.TextFormat.RichText)
        summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        summary.setStyleSheet(
            f"font-size: 20px; color: {Palette.TEXT_DARK}; background: transparent;")
        layout.addWidget(summary)

        layout.addStretch(1)
        close = QPushButton("Готово!")
        close.setObjectName("PrimaryButton")
        close.clicked.connect(self.accept)
        layout.addWidget(close)

        # Запускаем анимацию бейджа чуть позже, чтобы диалог успел показаться.
        if session_grade is not None:
            QTimer.singleShot(250, lambda: self._badge.set_grade(session_grade))
