# -*- coding: utf-8 -*-
"""
Стартовый экран: регистрация ученика и выбор персонажа-помощника.

На этом экране ребёнок вводит имя (или выбирает из выпадающего списка
уже сохранённых учеников, который формируется из JSON-файлов статистики),
возраст, выбирает класс (с учётом возрастных ограничений -- требование 3.3)
и персонажа, после чего начинает проверку.

Экран свёрнут в QScrollArea: при маленьком окне содержимое прокручивается,
а не искажается. Вся валидация (защита от некорректного ввода) реализована
здесь (требование 3.2).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QCompleter, QFormLayout,
                                QFrame, QGroupBox, QHBoxLayout, QLabel,
                                QPushButton, QRadioButton, QScrollArea,
                                QSpinBox, QVBoxLayout, QWidget)

from characters import CHARACTER_NAMES, make_character
from math_engine import allowed_grades_for_age
from ui_styles import Palette

try:
    from gl_characters import make_character_view
except Exception:                                    # pragma: no cover
    make_character_view = None


class StartScreen(QWidget):
    """Виджет стартового экрана с регистрацией.

    Сигналы:
        start_requested -- (name, age, grade, character) когда нажата кнопка
                           "Начать проверку" и данные корректны;
        stats_requested -- запрос на открытие окна статистики.
    """

    start_requested = Signal(str, int, int, str)
    stats_requested = Signal()

    def __init__(self, stats_manager, parent: QWidget | None = None):
        super().__init__(parent)
        self._stats = stats_manager
        self._character = "fairy"  # выбранный по умолчанию персонаж
        self._build_ui()

    # ------------------------------------------------------------------
    #  Построение интерфейса
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Содержимое в области прокрутки -- защита от искажений при
        # маленьком размере окна.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        content = QWidget()
        content.setMinimumWidth(860)      # минимальная ширина без искажений
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        title = QLabel("🌈 Математика — это весело!")
        title.setObjectName("TitleLabel")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Познакомимся? Расскажи о себе и выбери помощника!")
        subtitle.setObjectName("SubtitleLabel")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        # --- Карточка с формой -----------------------------------------
        card = QFrame()
        card.setObjectName("Card")
        card.setMinimumWidth(640)
        form_box = QGroupBox("👤 Данные ученика", card)

        # Имя: выпадающий список из сохранённых учеников + свободный ввод.
        self._name_combo = QComboBox()
        self._name_combo.setEditable(True)
        self._name_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._name_comboCompleter_setup()
        line_edit = self._name_combo.lineEdit()
        line_edit.setPlaceholderText("Выбери или введи имя, например: Маша")
        line_edit.setMaxLength(30)
        line_edit.returnPressed.connect(self._on_start)

        self._age_spin = QSpinBox()
        self._age_spin.setRange(6, 17)
        self._age_spin.setValue(7)
        self._age_spin.setSuffix(" лет")
        # Любое целое в диапазоне -- надёжная защита от нечислового ввода.
        self._age_spin.valueChanged.connect(self._refresh_grades)

        self._grade_combo = QComboBox()

        form = QFormLayout(form_box)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.addRow("Имя:", self._name_combo)
        form.addRow("Возраст:", self._age_spin)
        form.addRow("Класс:", self._grade_combo)

        self._hint = QLabel()
        self._hint.setObjectName("HintLabel")
        self._hint.setWordWrap(True)
        form.addRow(self._hint)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 14, 14, 14)
        card_layout.addWidget(form_box)

        # Форма и выбор персонажа -- рядом на широких экранах.
        mid_layout = QHBoxLayout()
        mid_layout.setSpacing(16)
        mid_layout.addWidget(card, stretch=5)

        # --- Выбор персонажа ---------------------------------------------
        char_box = QGroupBox("✨ Выбери помощника")
        char_box.setMinimumWidth(360)
        char_layout = QHBoxLayout(char_box)
        char_layout.setSpacing(12)
        self._char_group = QButtonGroup(self)
        self._char_group.setExclusive(True)

        for key, label in CHARACTER_NAMES.items():
            col = QVBoxLayout()
            col.setSpacing(4)
            if make_character_view is not None:
                preview = make_character_view(key, None, 230)
            else:
                preview = make_character(key, size=230)
            radio = QRadioButton(label)
            radio.setChecked(key == self._character)
            radio.toggled.connect(
                lambda checked, k=key: self._on_char_changed(checked, k))
            col.addWidget(preview, alignment=Qt.AlignmentFlag.AlignCenter)
            col.addWidget(radio, alignment=Qt.AlignmentFlag.AlignCenter)
            char_layout.addLayout(col)
            self._char_group.addButton(radio)

        mid_layout.addWidget(char_box, stretch=4)
        layout.addLayout(mid_layout)

        # --- Кнопки действий ---------------------------------------------
        buttons = QHBoxLayout()
        self._stats_btn = QPushButton("📊 Моя статистика")
        self._stats_btn.setObjectName("SecondaryButton")
        self._stats_btn.clicked.connect(self.stats_requested)

        self._start_btn = QPushButton("🚀 Начать проверку")
        self._start_btn.setObjectName("PrimaryButton")
        self._start_btn.clicked.connect(self._on_start)
        self._start_btn.setDefault(True)

        buttons.addStretch(1)
        buttons.addWidget(self._stats_btn)
        buttons.addWidget(self._start_btn)
        layout.addLayout(buttons)
        layout.addStretch(1)

        scroll.setWidget(content)
        outer.addWidget(scroll)

        self._refresh_grades()
        self.refresh_users()

    def _name_comboCompleter_setup(self) -> None:
        """Настраивает автодополнение для ввода имени."""
        completer = QCompleter()
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._name_combo.setCompleter(completer)

    # ------------------------------------------------------------------
    #  Обработчики
    # ------------------------------------------------------------------
    def _on_char_changed(self, checked: bool, key: str) -> None:
        """Запоминает выбранного персонажа."""
        if checked:
            self._character = key

    def refresh_users(self) -> None:
        """Обновляет выпадающий список имён из JSON-файлов статистики."""
        current = self._name_combo.currentText()
        self._name_combo.blockSignals(True)
        self._name_combo.clear()
        users = self._stats.list_users()
        if users:
            self._name_combo.addItems(users)
        # Восстанавливаем введённый текст (не затираем то, что печатает ребёнок).
        if current:
            self._name_combo.lineEdit().setText(current)
        self._name_combo.blockSignals(False)

    def _refresh_grades(self) -> None:
        """Обновляет список доступных классов в зависимости от возраста."""
        age = self._age_spin.value()
        allowed = allowed_grades_for_age(age)
        prev = self._grade_combo.currentText()
        self._grade_combo.blockSignals(True)
        self._grade_combo.clear()
        for g in allowed:
            self._grade_combo.addItem(f"{g} класс", g)
        # Пытаемся восстановить прежний выбор, если он всё ещё доступен.
        if prev:
            idx = self._grade_combo.findText(prev)
            if idx >= 0:
                self._grade_combo.setCurrentIndex(idx)
        self._grade_combo.blockSignals(False)
        self._hint.setText(
            "Доступные классы зависят от возраста: "
            "6–7 лет → 1 класс; 8 лет → 1–2; 9 лет → 1–3; 10+ лет → 1–4."
        )

    def _on_start(self) -> None:
        """Проверяет данные и испускает сигнал начала проверки."""
        name = self._name_combo.currentText().strip()
        if not name:
            self._name_combo.lineEdit().setStyleSheet(
                f"border: 3px solid {Palette.ERROR};")
            self._name_combo.lineEdit().setPlaceholderText(
                "Введите имя, пожалуйста!")
            self._name_combo.setFocus()
            return
        # Сбрасываем подсветку ошибки.
        self._name_combo.lineEdit().setStyleSheet("")
        age = self._age_spin.value()
        grade = self._grade_combo.currentData()
        if grade is None:
            return
        # Гарантируем, что класс соответствует возрасту.
        if grade not in allowed_grades_for_age(age):
            return
        self.start_requested.emit(name, age, int(grade), self._character)

    # ------------------------------------------------------------------
    #  Внешний API
    # ------------------------------------------------------------------
    def current_name(self) -> str:
        """Текущий текст поля имени."""
        return self._name_combo.currentText().strip()

    def set_name(self, name: str) -> None:
        """Подставляет имя в поле ввода."""
        self._name_combo.lineEdit().setText(name)
