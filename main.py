# -*- coding: utf-8 -*-
"""
Точка входа в приложение "Математика — это весело!".

Собирает вместе стартовый экран, экран проверки и окно статистики.
Управляет навигацией между ними и сохранением результатов сессии.
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QSurfaceFormat
from PySide6.QtWidgets import (QApplication, QMainWindow, QMessageBox,
                                QStackedWidget, QVBoxLayout, QWidget)

from quiz_screen import QuizScreen
from start_screen import StartScreen
from stats_manager import StatsManager
from ui_styles import apply_theme

def _app_base_dir() -> str:
    """Базовый каталог приложения для хранения данных.

    Для PyInstaller-сборки (getattr(sys, "frozen")) __file__ указывает на
    временный каталог распаковки, поэтому используем папку самого .exe --
    тогда JSON-файлы статистики сохраняются рядом с программой и живут
    между запусками. В обычном режиме -- папка скрипта.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


# Каталог для JSON-файлов статистики (сохраняется между запусками,
# в т.ч. в собранном .exe).
DATA_DIR = os.path.join(_app_base_dir(), "data")


def _make_app_icon():
    """Создаёт иконку приложения кодом (никаких внешних ресурсов)."""
    from PySide6.QtCore import QRectF, QSize, Qt
    from PySide6.QtGui import (QBrush, QColor, QFont, QIcon, QPainter,
                                QRadialGradient)
    pm = QPixmap(QSize(128, 128))
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QRadialGradient(64, 64, 90)
    grad.setColorAt(0, QColor("#F2C94C"))
    grad.setColorAt(1, QColor("#FF8A7A"))
    p.setBrush(QBrush(grad))
    p.setPen(QColor("#FFFFFF"))
    p.drawEllipse(QRectF(8, 8, 112, 112))
    p.setPen(QColor("#FFFFFF"))
    p.setFont(QFont("Comic Sans MS", 40, QFont.Weight.Black))
    p.drawText(QRectF(0, 0, 128, 128), Qt.AlignmentFlag.AlignCenter, "1+2")
    p.end()
    return QIcon(pm)


class MainWindow(QMainWindow):
    """Главное окно с переключением между стартовым и игровым экранами."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Математика — это весело!")
        # Минимальный размер, при котором интерфейс остаётся аккуратным;
        # при меньших размерах содержимое стартового экрана прокручивается.
        self.setMinimumSize(1020, 640)
        self.resize(1180, 780)
        self.setWindowIcon(_make_app_icon())

        self._stats = StatsManager(DATA_DIR)
        self._name = ""
        self._age = 8
        self._grade = 1
        self._character = "fairy"
        # Отдельное окно статистики (создаётся лениво, держим ссылку,
        # чтобы окно не уничтожалось сборщиком мусора).
        self._stats_window: StatsWindow | None = None

        # Стэк экранов.
        self._stack = QStackedWidget()
        central = QWidget()
        central.setObjectName("CentralWidget")
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._stack)
        self.setCentralWidget(central)

        self._start_screen = StartScreen(self._stats)
        self._quiz_screen = QuizScreen()

        self._stack.addWidget(self._start_screen)   # индекс 0
        self._stack.addWidget(self._quiz_screen)    # индекс 1

        # Сигналы.
        self._start_screen.start_requested.connect(self._on_start)
        self._start_screen.stats_requested.connect(self._show_stats_from_start)
        self._quiz_screen.session_finished.connect(self._on_session_finished)
        self._quiz_screen.back_requested.connect(self._go_start)

    # ------------------------------------------------------------------
    #  Навигация
    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        """Явно освобождаем GL-ресурсы персонажей и оверлеев."""
        widgets = ([self._quiz_screen._character_widget]
                   if self._quiz_screen._character_widget is not None else [])
        if getattr(self._quiz_screen, "_fx", None) is not None:
            widgets.append(self._quiz_screen._fx)
        widgets.extend(self._start_screen.findChildren(object))
        for w in widgets:
            cleanup = getattr(w, "_cleanup_gl", None)
            if cleanup is not None:
                try:
                    cleanup()
                except Exception:
                    pass
        # Единственный GL-контекст приложения -- спрайт-рендерер.
        try:
            from gl_characters import release_renderer
            release_renderer()
        except Exception:
            pass
        super().closeEvent(event)

    def _on_start(self, name: str, age: int, grade: int, character: str) -> None:
        """Обработчик начала проверки.

        Примеры трёх ближайших сессий этого класса передаются генератору,
        чтобы задания не повторялись (требование заказа).
        """
        self._name = name
        self._age = age
        self._grade = grade
        self._character = character
        # Сохраняем/обновляем профиль ученика.
        self._stats.get_user(name, age)
        recent = self._stats.recent_problems(name, grade, count=3)
        self._quiz_screen.start_session(grade, character, recent=recent)
        self._stack.setCurrentIndex(1)

    def _go_start(self) -> None:
        """Возврат на стартовый экран (с обновлением списка имён)."""
        self._start_screen.refresh_users()
        self._stack.setCurrentIndex(0)

    # ------------------------------------------------------------------
    #  Окно статистики
    # ------------------------------------------------------------------
    def _show_stats_from_start(self) -> None:
        """Открытие статистики со стартового экрана.

        Если имя не выбрано -- берём первого сохранённого ученика или
        предлагаем выбор из списка.
        """
        name = self._start_screen.current_name()
        if name and self._stats.has_user(name):
            self._open_stats_window(name)
            return
        users = self._stats.list_users()
        if not users:
            QMessageBox.information(
                self, "Статистика",
                "Пока нет сохранённых данных. Введи имя и начни первую проверку!")
            return
        if len(users) == 1:
            self._open_stats_window(users[0])
            return
        self._show_user_picker(users)

    def _open_stats_window(self, name: str) -> None:
        """Открывает (или активирует) отдельное окно статистики.

        QtCharts импортируется лениво -- это ускоряет запуск приложения
        (особенно собранного PyInstaller .exe).
        """
        from stats_window import StatsWindow
        data = self._stats.get_user(name, self._age)
        grades = sorted(int(g) for g in data.get("grades", {}).keys())
        grade = self._grade if self._grade in grades else (
            grades[-1] if grades else self._grade)
        if self._stats_window is None:
            self._stats_window = StatsWindow(self._stats)
        self._stats_window.load_user(name, data.get("age", self._age), grade)
        self._stats_window.show()
        self._stats_window.raise_()
        self._stats_window.activateWindow()

    def _show_user_picker(self, users: list) -> None:
        """Диалог выбора существующего ученика для просмотра статистики."""
        from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel,
                                        QListWidget, QVBoxLayout)
        dlg = QDialog(self)
        dlg.setWindowTitle("Выбери ученика")
        dlg.setMinimumWidth(320)
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel("Чью статистику показать?"))
        lw = QListWidget()
        lw.addItems(users)
        v.addWidget(lw)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec() == QDialog.DialogCode.Accepted and lw.currentItem():
            self._open_stats_window(lw.currentItem().text())

    # ------------------------------------------------------------------
    #  Завершение сессии
    # ------------------------------------------------------------------
    def _on_session_finished(self, total: int, correct: int,
                             problems: list) -> None:
        """Сохраняет результат сессии и показывает оценку."""
        result = self._stats.record_session(
            self._name, self._age, self._grade, total, correct, problems)
        from stats_window import SessionResultDialog
        dlg = SessionResultDialog(
            session_grade=result["session_grade"],
            class_grade=result["class_grade"],
            total=total, correct=correct, parent=self)
        dlg.exec()
        # После закрытия -- возврат на стартовый экран.
        self._go_start()


def _prefer_xcb_on_wayland() -> None:
    """На Linux под Wayland переключает Qt на xcb (XWayland).

    Причина: на целом ряде драйверов (в т.ч. NVIDIA) EGL/Wayland не даёт
    контекст OpenGL 3.3+ по явному запросу версии, а без запроса отдаёт
    лишь 3.2 -- шейдерам 3D-персонажей нужно 3.3. Через XWayland доступен
    полноценный десктопный OpenGL 4.x. Если пользователь задал платформу
    сам или X-сервера нет -- ничего не меняем.
    """
    if sys.platform.startswith("linux") \
            and os.environ.get("WAYLAND_DISPLAY") \
            and os.environ.get("DISPLAY") \
            and not os.environ.get("QT_QPA_PLATFORM"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"


def prepare_gl_environment() -> None:
    """Подготовка окружения для GL: платформа + формат поверхности.

    Вызывается из main() ДО создания QApplication; отдельная функция --
    чтобы интеграционные тесты могли повторить ровно тот же путь.
    """
    _prefer_xcb_on_wayland()
    # Общие GL-контексты нужны нескольким GL-виджетам. Явно запрашиваем
    # OpenGL 3.3 Core: шейдеры частиц рассчитаны на core-семантику
    # (в compatibility-контекстах 4.x драйвер NVIDIA некорректно
    # обрабатывает gl_PointSize с атрибутным размером). Через XWayland
    # такой контекст создаётся успешно; если платформа всё же не даёт
    # 3.3 Core -- gl_available() честно откатит персонажей в 2D.
    QApplication.setAttribute(
        Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setAlphaBufferSize(8)
    fmt.setDepthBufferSize(24)       # глубина для 3D-моделей персонажей
    fmt.setSwapInterval(1)           # vsync -- меньше нагрузка GPU
    QSurfaceFormat.setDefaultFormat(fmt)


def main() -> int:
    """Запускает приложение."""
    prepare_gl_environment()
    app = QApplication(sys.argv)
    apply_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
