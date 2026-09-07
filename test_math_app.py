# -*- coding: utf-8 -*-
"""
Unit-тесты для приложения "Математика — это весело!".

Покрывают:
    * генерацию корректных примеров для каждого класса (1-4);
    * отсутствие деления на ноль и деления с остатком;
    * отсутствие отрицательных промежуточных и финальных результатов;
    * соблюдение диапазонов и ФОРМ действий по классам:
        - 1 класс: всё в 0..20, только сложение и вычитание;
        - 2 класс: умножение однозначное x однозначное; деление --
          однозначное/двузначное : однозначное (делимое <= 81);
        - 3 класс: в умножении один множитель однозначный (произведение
          <= 100); в делении делитель однозначный, частное двузначное;
    * уникальность примеров (отсутствие совпадений с младшими классами);
    * корректность подсчёта оценок за сессию (пятибалльная шкала);
    * возрастные ограничения для выбора класса;
    * защиту от повторов примеров в течение трёх ближайших сессий;
    * сохранение и чтение статистики (StatsManager).

Запуск::

    python -m pytest test_math_app.py -v
"""
from __future__ import annotations

import os
import re
import sys

import pytest

# Гарантируем, что модули приложения импортируются.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from math_engine import (GRADE_CONFIGS, MathEngine, Problem, allowed_grades_for_age,
                          check_answer, grade_from_percent)
from stats_manager import StatsManager


# ---------------------------------------------------------------------------
#  Вспомогательные функции проверок
# ---------------------------------------------------------------------------
def _eval_display(display: str) -> float:
    """Независимо вычисляет значение строки примера (для сверки answer)."""
    expr = (display.rstrip(" =")
            .replace("×", "*").replace("÷", "/").replace("−", "-"))
    return eval(expr, {"__builtins__": {}}, {})


def _simple_range_ok(problem: Problem, lo: int, hi: int) -> bool:
    """Все числа и ответ простого примера в диапазоне [lo, hi]?"""
    return all(lo <= n <= hi for n in problem.numbers) and lo <= problem.answer <= hi


def _could_generate(problem: Problem, grade: int) -> bool:
    """Мог бы движок класса ``grade`` сгенерировать такой ПРОСТОЙ пример?

    Кодирует структурные правила каждого класса (диапазоны + формы
    умножения/деления), поэтому надёжно выявляет совпадения с младшими
    классами.
    """
    if len(problem.ops) > 1:
        return False  # сложный пример не может быть простым примером младшего класса
    op = problem.ops[0]
    n = problem.numbers
    if grade == 1:
        return op in ("+", "−") and all(0 <= v <= 20 for v in n)
    if grade == 2:
        if op in ("+", "−"):
            return all(0 <= v <= 100 for v in n)
        if op == "×":
            a, b, r = n
            return 1 <= a <= 9 and 1 <= b <= 9 and r <= 81
        if op == "÷":
            a, d, q = n
            return 1 <= d <= 9 and 1 <= q <= 9 and a <= 81
    if grade == 3:
        if op in ("+", "−"):
            return all(0 <= v <= 1000 for v in n)
        if op == "×":
            a, b, r = n
            return min(a, b) <= 9 and max(a, b) <= 100 and r <= 100
        if op == "÷":
            a, d, q = n
            return 2 <= d <= 9 and 10 <= q <= 499 and a <= 999
    if grade == 4:
        if op in ("+", "−"):
            return all(0 <= v <= 1_000_000 for v in n)
        if op == "×":
            return all(1 <= v <= 1_000_000 for v in n)
        if op == "÷":
            return all(1 <= v <= 1_000_000 for v in n)
    return False


# ---------------------------------------------------------------------------
#  Тесты: общая генерация
# ---------------------------------------------------------------------------
class TestGradeGeneration:
    """Проверки генератора для каждого класса."""

    @pytest.mark.parametrize("grade", [1, 2, 3, 4])
    def test_generates_many_problems(self, grade):
        """Генератор не падает при массовой генерации."""
        engine = MathEngine(grade, seed=grade)
        for _ in range(500):
            p = engine.next_problem()
            assert isinstance(p, Problem)
            assert p.grade == grade

    @pytest.mark.parametrize("grade", [1, 2, 3, 4])
    def test_answer_non_negative(self, grade):
        """Все ответы -- целые неотрицательные числа."""
        engine = MathEngine(grade)
        for _ in range(800):
            p = engine.next_problem()
            assert p.answer >= 0
            assert isinstance(p.answer, int)

    @pytest.mark.parametrize("grade", [1, 2, 3, 4])
    def test_answer_matches_display(self, grade):
        """answer совпадает с независимо вычисленным значением display."""
        engine = MathEngine(grade, seed=123)
        for _ in range(500):
            p = engine.next_problem()
            assert _eval_display(p.display) == p.answer

    @pytest.mark.parametrize("grade", [1, 2, 3, 4])
    def test_no_division_by_zero(self, grade):
        """Ни в одном примере нет деления на ноль."""
        engine = MathEngine(grade)
        for _ in range(800):
            p = engine.next_problem()
            try:
                _eval_display(p.display)
            except ZeroDivisionError:
                pytest.fail(f"Деление на ноль: {p.display}")

    @pytest.mark.parametrize("grade", [1, 2, 3, 4])
    def test_exact_division(self, grade):
        """Деление всегда без остатка (answer -- целое число)."""
        engine = MathEngine(grade)
        for _ in range(800):
            p = engine.next_problem()
            if "÷" in p.display:
                assert p.answer == int(p.answer)


# ---------------------------------------------------------------------------
#  Тесты: 1 класс
# ---------------------------------------------------------------------------
class TestGrade1:
    """1 класс: только сложение и вычитание, всё строго в 0..20.

    Примерно каждый пятый пример -- на два действия со скобками
    "(A + B) - C"; все промежуточные результаты и итог -- в 0..20.
    """

    def test_only_addition_subtraction(self):
        """Во всех примерах (простых и сложных) -- только + и -."""
        engine = MathEngine(1)
        for _ in range(1000):
            p = engine.next_problem()
            assert 1 <= len(p.ops) <= 2
            for op in p.ops:
                assert op in ("+", "−"), f"Недопустимое действие {op}: {p.display}"

    def test_numbers_in_range_0_20(self):
        """Все числа, промежуточные и итоговые результаты -- в 0..20."""
        engine = MathEngine(1)
        for _ in range(1000):
            p = engine.next_problem()
            assert _simple_range_ok(p, 0, 20), (
                f"Выход за диапазон: {p.display}{p.answer} numbers={p.numbers}")

    def test_complex_problems_appear_about_one_in_five(self):
        """Примеры со скобками появляются примерно в 20% случаев."""
        engine = MathEngine(1, seed=42)
        complex_count = 0
        total = 3000
        for _ in range(total):
            if "(" in engine.next_problem().display:
                complex_count += 1
        ratio = complex_count / total
        assert 0.14 <= ratio <= 0.26, (
            f"Доля сложных примеров {ratio:.2%} вне диапазона ~20%")

    def test_complex_form_and_bounds(self):
        """Сложные примеры 1 класса: форма (A + B) - C, все результаты 0..20."""
        engine = MathEngine(1, seed=7)
        pattern = re.compile(r"^\((\d+) \+ (\d+)\) - (\d+) = $")
        seen = 0
        for _ in range(4000):
            p = engine.next_problem()
            if "(" not in p.display:
                continue
            seen += 1
            m = pattern.match(p.display)
            assert m, f"Неверная форма сложного примера: {p.display}"
            a, b, c = map(int, m.groups())
            inner = a + b                     # промежуточный результат
            assert 0 <= inner <= 20, (
                f"Промежуточный результат {inner} вне 0..20: {p.display}")
            assert 0 <= c <= inner, (
                f"Вычитаемое больше суммы: {p.display}")
            assert p.answer == inner - c
            assert 0 <= p.answer <= 20
        assert seen > 100, "Сложные примеры почти не генерируются"


# ---------------------------------------------------------------------------
#  Тесты: 2 класс
# ---------------------------------------------------------------------------
class TestGrade2:
    """2 класс: диапазоны и формы умножения/деления."""

    def test_addsub_range_0_100(self):
        """Сложение/вычитание и их результаты -- 0..100."""
        engine = MathEngine(2, seed=7)
        for _ in range(1500):
            p = engine.next_problem()
            if len(p.ops) == 1 and p.ops[0] in ("+", "−"):
                assert _simple_range_ok(p, 0, 100), f"{p.display}{p.answer}"

    def test_multiplication_single_digit(self):
        """Умножение: однозначное x однозначное (таблица умножения)."""
        engine = MathEngine(2, seed=8)
        seen = 0
        for _ in range(3000):
            p = engine.next_problem()
            if len(p.ops) == 1 and p.ops[0] == "×":
                seen += 1
                a, b, r = p.numbers
                assert 1 <= a <= 9 and 1 <= b <= 9, (
                    f"Множитель не однозначный: {p.display}")
                assert r == a * b and r <= 81, f"{p.display}{r}"
        assert seen > 50, "Умножение почти не генерируется"

    def test_division_single_digit_divisor(self):
        """Деление: делитель однозначный, делимое <= 81, частное <= 9."""
        engine = MathEngine(2, seed=9)
        seen = 0
        for _ in range(3000):
            p = engine.next_problem()
            if len(p.ops) == 1 and p.ops[0] == "÷":
                seen += 1
                a, d, q = p.numbers
                assert 1 <= d <= 9, f"Делитель не однозначный: {p.display}"
                assert a == d * q and a <= 81, f"Делимое > 81: {p.display}{q}"
                assert 1 <= q <= 9, f"Частное > 9 (нетабличное): {p.display}{q}"
        assert seen > 50, "Деление почти не генерируется"

    def test_complex_appear(self):
        """Сложные примеры (со скобками) действительно генерируются."""
        engine = MathEngine(2)
        found = False
        for _ in range(2000):
            if "(" in engine.next_problem().display:
                found = True
                break
        assert found, "Сложные примеры не генерируются"

    def test_complex_numbers_single_digit_in_parens(self):
        """В сложных примерх 2 класса числа внутри скобок -- однозначные.

        Требование 4.3: "выражение в скобках с однозначными целыми числами".
        Делимое вне скобок может быть двузначным (оно кратно произведению
        однозначных чисел в скобках).
        """
        engine = MathEngine(2)
        for _ in range(3000):
            p = engine.next_problem()
            if "(" in p.display:
                for match in re.finditer(r"\(([^()]+)\)", p.display):
                    inner = match.group(1)
                    for n in re.findall(r"\d+", inner):
                        assert 0 <= int(n) <= 9, (
                            f"Число {n} в скобках ({inner}) не однозначное: "
                            f"{p.display}")


# ---------------------------------------------------------------------------
#  Тесты: 3 класс
# ---------------------------------------------------------------------------
class TestGrade3:
    """3 класс: диапазоны и формы умножения/деления."""

    def test_addsub_range_0_1000(self):
        engine = MathEngine(3, seed=11)
        for _ in range(1500):
            p = engine.next_problem()
            if len(p.ops) == 1 and p.ops[0] in ("+", "−"):
                assert _simple_range_ok(p, 0, 1000)

    def test_multiplication_one_factor_single_digit(self):
        """В умножении один из множителей однозначный, произведение <= 100."""
        engine = MathEngine(3, seed=12)
        seen = 0
        for _ in range(3000):
            p = engine.next_problem()
            if len(p.ops) == 1 and p.ops[0] == "×":
                seen += 1
                a, b, r = p.numbers
                assert min(a, b) <= 9, (
                    f"Оба множителя многозначные: {p.display}")
                assert r == a * b and r <= 100, f"{p.display}{r}"
        assert seen > 50

    def test_division_single_digit_divisor(self):
        """В делении делитель однозначный; делимое до 999, частное двузначное."""
        engine = MathEngine(3, seed=13)
        seen = 0
        seen_three_digit = 0
        for _ in range(3000):
            p = engine.next_problem()
            if len(p.ops) == 1 and p.ops[0] == "÷":
                seen += 1
                a, d, q = p.numbers
                assert 2 <= d <= 9, f"Делитель не однозначный: {p.display}"
                assert a == d * q and a <= 999, f"Делимое > 999: {p.display}{q}"
                assert 10 <= q <= 499, (
                    f"Частное вне диапазона: {p.display}{q}")
                if a >= 100:
                    seen_three_digit += 1
        assert seen > 50
        assert seen_three_digit > 10, (
            "Трёхзначные делимые почти не встречаются")


# ---------------------------------------------------------------------------
#  Тесты: 4 класс
# ---------------------------------------------------------------------------
class TestGrade4:
    """4 класс: полные диапазоны."""

    def test_addsub_range_0_1000000(self):
        engine = MathEngine(4, seed=21)
        for _ in range(1000):
            p = engine.next_problem()
            if len(p.ops) == 1 and p.ops[0] in ("+", "−"):
                assert _simple_range_ok(p, 0, 1_000_000)

    def test_muldiv_range_1_1000000(self):
        engine = MathEngine(4, seed=22)
        for _ in range(1000):
            p = engine.next_problem()
            if len(p.ops) == 1 and p.ops[0] in ("×", "÷"):
                assert _simple_range_ok(p, 1, 1_000_000)

    def test_complex_numbers_within_class_limit(self):
        """Все числа сложных примеров 4 класса не превышают 1 000 000.

        Регрессионный тест: раньше делимое в шаблоне "A : (B × C) - D"
        могло достигать миллиардов.
        """
        engine = MathEngine(4, seed=31)
        seen = 0
        for _ in range(4000):
            p = engine.next_problem()
            if "(" in p.display:
                seen += 1
                for n in p.numbers:
                    assert n <= 1_000_000, (
                        f"Число {n} превышает 1 000 000: {p.display}")
        assert seen > 50, "Сложные примеры почти не генерируются"


# ---------------------------------------------------------------------------
#  Тесты: отсутствие отрицательных промежуточных результатов
# ---------------------------------------------------------------------------
class TestNoNegativeIntermediate:
    """Проверка требования 4.8: нет отрицательных результатов в скобках."""

    @pytest.mark.parametrize("grade", [2, 3, 4])
    def test_no_negative_inside_parentheses(self, grade):
        engine = MathEngine(grade)
        for _ in range(3000):
            p = engine.next_problem()
            if "(" not in p.display:
                continue
            for match in re.finditer(r"\(([^()]+)\)", p.display):
                inner = match.group(1)
                value = _eval_display(inner)
                assert value >= 0, (
                    f"Отрицательное значение в скобках ({inner}) = {value}: "
                    f"{p.display}")


# ---------------------------------------------------------------------------
#  Тесты: отсутствие совпадений с младшими классами
# ---------------------------------------------------------------------------
class TestNoOverlapWithLowerGrades:
    """Пример класса N не мог быть сгенерирован ни в одном младшем классе."""

    @pytest.mark.parametrize("grade", [2, 3, 4])
    def test_simple_problems_not_from_lower_grades(self, grade):
        engine = MathEngine(grade, seed=99)
        for _ in range(2000):
            p = engine.next_problem()
            if len(p.ops) == 1:
                for lower in range(1, grade):
                    assert not _could_generate(p, lower), (
                        f"Пересечение: G{grade} пример '{p.display}{p.answer}' "
                        f"мог быть сгенерирован в G{lower}")

    def test_no_identical_displays_between_grades_1_and_2(self):
        """Ни один пример 2 класса не совпадает дословно с примером 1 класса.

        В 1 классе теперь есть примеры "(A + B) - C" -- проверяем, что
        генератор 2 класса не выдаёт точно такие же строки.
        """
        engine1 = MathEngine(1, seed=1)
        grade1_displays = {engine1.next_problem().display for _ in range(4000)}
        engine2 = MathEngine(2, seed=2)
        for _ in range(4000):
            p = engine2.next_problem()
            assert p.display not in grade1_displays, (
                f"Пример 2 класса совпадает с примером 1 класса: {p.display}")


# ---------------------------------------------------------------------------
#  Тесты: защита от повторов в течение трёх ближайших сессий
# ---------------------------------------------------------------------------
class TestNoRepeats:
    """Примеры не повторяются внутри сессии и между тремя сессиями."""

    def test_no_repeats_within_session(self):
        """Внутри одной сессии примеры не повторяются."""
        engine = MathEngine(1, seed=5)
        seen = set()
        for _ in range(60):
            p = engine.next_problem()
            assert p.display not in seen, f"Повтор внутри сессии: {p.display}"
            seen.add(p.display)

    def test_recent_problems_excluded(self):
        """Примеры из трёх последних сессий не выдаются снова."""
        engine = MathEngine(1, seed=6)
        first = [engine.next_problem().display for _ in range(40)]
        # Новая сессия с "недавними" примерами.
        engine2 = MathEngine(1, seed=7, recent=set(first[:30]))
        for _ in range(50):
            p = engine2.next_problem()
            assert p.display not in set(first[:30]), (
                f"Повтор из недавних сессий: {p.display}")

    def test_used_problems_recorded(self):
        """used_problems возвращает все показанные примеры сессии."""
        engine = MathEngine(2, seed=8)
        for _ in range(20):
            engine.next_problem()
        assert len(engine.used_problems) == 20
        assert len(set(engine.used_problems)) == 20  # все уникальны

    def test_stats_recent_problems(self, tmp_path):
        """StatsManager.recent_problems возвращает объединение трёх сессий."""
        sm = StatsManager(data_dir=str(tmp_path))
        sm.record_session("Аня", 8, 2, 10, 9, problems=["2 × 3 = ", "5 + 5 = "])
        sm.record_session("Аня", 8, 2, 10, 8, problems=["7 × 8 = "])
        sm.record_session("Аня", 8, 2, 10, 7, problems=["9 − 4 = "])
        sm.record_session("Аня", 8, 2, 10, 6,
                          problems=["6 × 6 = ", "20 + 30 = "])
        recent = sm.recent_problems("Аня", 2, count=3)
        # Последние три сессии (без первой).
        assert recent == {"7 × 8 = ", "9 − 4 = ", "6 × 6 = ", "20 + 30 = "}

    def test_problems_persisted_in_json(self, tmp_path):
        """Список примеров сессии сохраняется в JSON."""
        sm = StatsManager(data_dir=str(tmp_path))
        sm.record_session("Боря", 9, 3, 4, 4, problems=["10 × 5 = "])
        block = sm.get_stats("Боря", 3)
        assert block["sessions"][0]["problems"] == ["10 × 5 = "]


# ---------------------------------------------------------------------------
#  Тесты: оценка по пятибалльной шкале
# ---------------------------------------------------------------------------
class TestGrading:
    """Проверка функции grade_from_percent (требование 3.12)."""

    @pytest.mark.parametrize("correct,total,expected", [
        (100, 100, 5),   # 100%
        (95, 100, 5),    # 95%
        (94, 100, 4),    # <95%
        (80, 100, 4),    # 80%
        (79, 100, 3),    # <80%
        (60, 100, 3),    # 60%
        (59, 100, 2),    # <60%
        (40, 100, 2),    # 40%
        (39, 100, 1),    # <40%
        (0, 100, 1),     # 0%
    ])
    def test_grade_boundaries(self, correct, total, expected):
        assert grade_from_percent(correct, total) == expected

    def test_no_answers_returns_none(self):
        assert grade_from_percent(0, 0) is None

    def test_check_answer(self):
        """Сравнение ответов пользователя и правильного."""
        p = Problem(grade=1, display="2 + 3 = ", answer=5)
        assert check_answer(p, 5) is True
        assert check_answer(p, 4) is False
        assert check_answer(p, "5") is True  # строка-число


# ---------------------------------------------------------------------------
#  Тесты: возрастные ограничения
# ---------------------------------------------------------------------------
class TestAgeGrades:
    """Проверка allowed_grades_for_age (требование 3.3)."""

    @pytest.mark.parametrize("age,expected", [
        (6, [1]), (7, [1]),
        (8, [1, 2]),
        (9, [1, 2, 3]),
        (10, [1, 2, 3, 4]),
        (12, [1, 2, 3, 4]),
    ])
    def test_allowed_grades(self, age, expected):
        assert allowed_grades_for_age(age) == expected

    def test_invalid_age_empty(self):
        assert allowed_grades_for_age(3) == []
        assert allowed_grades_for_age(-1) == []


# ---------------------------------------------------------------------------
#  Тесты: менеджер статистики
# ---------------------------------------------------------------------------
class TestStatsManager:
    """Проверки StatsManager."""

    def test_record_and_read(self, tmp_path):
        sm = StatsManager(data_dir=str(tmp_path))
        r = sm.record_session("Аня", 8, 2, total=10, correct=9)
        assert r["session_grade"] == 4
        assert r["class_grade"] == 4
        assert r["class_total"] == 10
        assert r["class_sessions"] == 1
        assert (tmp_path / "Аня.json").exists()

    def test_class_grade_is_average(self, tmp_path):
        sm = StatsManager(data_dir=str(tmp_path))
        sm.record_session("Боря", 9, 3, total=10, correct=10)  # 5
        r = sm.record_session("Боря", 9, 3, total=10, correct=8)  # 4
        assert r["class_grade"] == 4.5
        assert r["class_sessions"] == 2

    def test_grades_independent(self, tmp_path):
        """Статистика по разным классам ведётся раздельно."""
        sm = StatsManager(data_dir=str(tmp_path))
        sm.record_session("Вера", 10, 1, total=10, correct=5)
        sm.record_session("Вера", 10, 2, total=10, correct=10)
        g1 = sm.get_stats("Вера", 1)
        g2 = sm.get_stats("Вера", 2)
        assert g1["total_answers"] == 10
        assert g2["total_answers"] == 10
        assert g1["correct_answers"] == 5
        assert g2["correct_answers"] == 10

    def test_persistence_after_reload(self, tmp_path):
        """Данные сохраняются между запусками."""
        sm = StatsManager(data_dir=str(tmp_path))
        sm.record_session("Гена", 8, 2, total=10, correct=9)
        sm2 = StatsManager(data_dir=str(tmp_path))
        assert sm2.has_user("Гена")
        stats = sm2.get_stats("Гена", 2)
        assert len(stats["sessions"]) == 1

    def test_missing_file_returns_none(self, tmp_path):
        sm = StatsManager(data_dir=str(tmp_path))
        assert sm.get_stats("НетТакого", 1) is None
        assert not sm.has_user("НетТакого")

    def test_cyrillic_filename(self, tmp_path):
        """Кириллические имена сохраняются корректно."""
        sm = StatsManager(data_dir=str(tmp_path))
        sm.record_session("Матвей", 7, 1, total=5, correct=5)
        assert (tmp_path / "Матвей.json").exists()

    def test_name_with_spaces_sanitized(self, tmp_path):
        """Имена с пробелами превращаются в безопасные имена файлов."""
        sm = StatsManager(data_dir=str(tmp_path))
        sm.record_session("Анна Мария", 8, 1, total=5, correct=5)
        assert (tmp_path / "Анна_Мария.json").exists()

    def test_corrupted_file_handled(self, tmp_path):
        """Повреждённый JSON не валит приложение."""
        (tmp_path / "Слом.json").write_text("{ некорректный json", encoding="utf-8")
        sm = StatsManager(data_dir=str(tmp_path))
        assert sm.get_stats("Слом", 1) is None
        assert not sm.has_user("Слом")

    def test_empty_total_handled(self, tmp_path):
        """Сессия без ответов не падает."""
        sm = StatsManager(data_dir=str(tmp_path))
        r = sm.record_session("Дима", 8, 2, total=0, correct=0)
        assert r["session_grade"] is None

    def test_list_users(self, tmp_path):
        """list_users возвращает имена всех сохранённых учеников."""
        sm = StatsManager(data_dir=str(tmp_path))
        sm.record_session("Ева", 7, 1, 5, 5)
        sm.record_session("Женя", 9, 3, 5, 4)
        assert sorted(sm.list_users()) == ["Ева", "Женя"]


# ---------------------------------------------------------------------------
#  Тесты: GPU-шейдеры ModernGL (выполняются при наличии headless OpenGL)
# ---------------------------------------------------------------------------
def _gl_headless_ok() -> bool:
    """Доступен ли headless OpenGL (для проверки шейдеров)."""
    try:
        import moderngl
        ctx = moderngl.create_standalone_context()
        ctx.release()
        return True
    except Exception:
        return False


class TestGLShaders:
    """Проверка компиляции и рендера всех шейдеров gl_characters.py."""

    def test_shaders_compile_and_render(self):
        """Все программы компилируются; квад, тень и 6 типов частиц
        рендерятся; «мёртвые» частицы невидимы; персонаж не перевёрнут."""
        import re
        import struct
        import moderngl

        gl_src = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "gl_characters.py")
        src = open(gl_src, encoding="utf-8").read()
        names = ("QUAD_VS", "QUAD_FS", "AURA_VS", "AURA_FS",
                 "PARTICLE_VS", "PARTICLE_FS")
        shaders = {n: re.search(rf"{n} = \"\"\"(.*?)\"\"\"", src, re.S).group(1)
                   for n in names}

        ctx = moderngl.create_standalone_context()
        try:
            quad = ctx.program(vertex_shader=shaders["QUAD_VS"],
                               fragment_shader=shaders["QUAD_FS"])
            particles = ctx.program(vertex_shader=shaders["PARTICLE_VS"],
                                    fragment_shader=shaders["PARTICLE_FS"])
            aura = ctx.program(vertex_shader=shaders["AURA_VS"],
                               fragment_shader=shaders["AURA_FS"])

            fbo = ctx.simple_framebuffer((100, 100))
            fbo.use()
            ctx.viewport = (0, 0, 100, 100)
            ctx.enable(moderngl.BLEND)
            ctx.enable(moderngl.PROGRAM_POINT_SIZE)
            ctx.blend_func = (moderngl.SRC_ALPHA,
                              moderngl.ONE_MINUS_SRC_ALPHA,
                              moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA)

            # Квад персонажа: верх картинки должен оказаться вверху экрана.
            rows = [(255, 255, 255), (0, 0, 255), (0, 255, 0), (255, 0, 0)]
            tex = ctx.texture((4, 4), 4,
                              b"".join(bytes(c + (255,)) * 4 for c in rows))
            tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            vbo = ctx.buffer(struct.pack("8f", -1, -1, 1, -1, 1, 1, -1, 1))
            vao = ctx.vertex_array(quad, [(vbo, "2f", "in_pos")])
            fbo.clear(0, 0, 0, 0)
            tex.use(0)
            for k, v in dict(u_tex=0, u_time=0.0, u_kind=0.0,
                             u_res=(100.0, 100.0), u_center=(50.0, 50.0),
                             u_half=(48.0, 48.0), u_dpr=1.0,
                             u_shadow=0.0, u_off=(0.0, 0.0)).items():
                quad[k].value = v
            vao.render(moderngl.TRIANGLE_FAN)
            data = fbo.read(components=4, alignment=1)

            def px(x, row):
                i = (row * 100 + x) * 4
                return tuple(data[i:i + 3])

            top, bottom = px(50, 97), px(50, 2)
            assert top[0] > 200 and top[1] > 200, top        # верх = white-ряд
            assert bottom[0] > 200 and bottom[1] < 60, bottom  # низ = red-ряд

            # Частицы: все типы видимы; мёртвые/будущие скрыты.
            for label, ptype, size, min_a in (
                    ("spark", 0.0, 20, 60), ("dust", 1.0, 60, 25),
                    ("smoke", 2.0, 90, 30), ("confetti", 3.0, 14, 100),
                    ("bubble", 5.0, 12, 20)):
                fbo.clear(0, 0, 0, 0)
                pvbo = ctx.buffer(struct.pack(
                    "12f", 50, 50, 0, 0, 0.0, 1.0, size,
                    1.0, 0.5, 0.3, ptype, 0.7))
                pvao = ctx.vertex_array(particles, [(
                    pvbo, "2f 2f 1f 1f 1f 3f 1f 1f",
                    "in_pos", "in_vel", "in_birth", "in_life", "in_size",
                    "in_color", "in_type", "in_aux")])
                particles["u_now"].value = 0.1
                particles["u_res"].value = (100.0, 100.0)
                particles["u_dpr"].value = 1.0
                particles["u_point_max"].value = 256.0
                pvao.render(moderngl.POINTS, 1)
                d = fbo.read(components=4, alignment=1)
                assert d[(50 * 100 + 50) * 4 + 3] > min_a, label

            for birth in (-100.0, 100.0):
                fbo.clear(0, 0, 0, 0)
                pvbo = ctx.buffer(struct.pack(
                    "12f", 50, 50, 0, 0, birth, 1.0, 40, 1, 1, 1, 0.0, 0))
                pvao = ctx.vertex_array(particles, [(
                    pvbo, "2f 2f 1f 1f 1f 3f 1f 1f",
                    "in_pos", "in_vel", "in_birth", "in_life", "in_size",
                    "in_color", "in_type", "in_aux")])
                pvao.render(moderngl.POINTS, 1)
                d = fbo.read(components=4, alignment=1)
                assert d[(50 * 100 + 50) * 4 + 3] == 0

            # Аура.
            fbo.clear(0, 0, 0, 0)
            avbo = ctx.buffer(struct.pack(
                "8f", 0.0, 90.0, 0.3, 5.0, 1.0, 0.9, 0.5, 0.0))
            avao = ctx.vertex_array(aura, [(
                avbo, "1f 1f 1f 1f 3f 1f 1f",
                "in_phase", "in_radius", "in_speed", "in_size",
                "in_color", "in_type", "in_aux")])
            aura["u_time"].value = 0.0
            aura["u_center"].value = (50.0, 50.0)
            aura["u_res"].value = (100.0, 100.0)
            aura["u_scale"].value = 100.0 / 240.0
            aura["u_dpr"].value = 1.0
            avao.render(moderngl.POINTS, 1)
            d = fbo.read(components=4, alignment=1)
            assert d[(50 * 100 + 87) * 4 + 3] > 30
        finally:
            ctx.release()


class TestGLTFModels:
    """3D-модели персонажей (GLB): загрузка, кадрирование, текстуры.

    Выполняется при наличии headless OpenGL и файлов моделей.
    """

    def test_models_load_render_framed(self):
        """Обе модели грузятся, рендерятся целиком (без обрезки),
        по центру, с текстурами; поворот меняет кадр."""
        import numpy as np
        import moderngl
        from gltf_model import (GLTFModel, fit_camera, mat_mul,
                                 mat_rotate_y, model_path)

        if not _gl_headless_ok():
            pytest.skip("Нет headless OpenGL")
        paths = {k: model_path(k) for k in ("fairy", "prime")}
        if any(p is None for p in paths.values()):
            pytest.skip("Файлы GLB-моделей не найдены")

        # QImage нужен для декодирования JPEG-текстур.
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])

        ctx = moderngl.create_standalone_context()
        try:
            size = 400
            fbo = ctx.simple_framebuffer((size, size))
            fbo.use()
            ctx.viewport = (0, 0, size, size)
            ctx.enable(moderngl.BLEND)
            ctx.enable(moderngl.DEPTH_TEST)
            ctx.blend_func = (moderngl.SRC_ALPHA,
                              moderngl.ONE_MINUS_SRC_ALPHA,
                              moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA)
            bg = np.array([25, 38, 51], dtype=np.int16)
            for key in ("fairy", "prime"):
                model = GLTFModel(ctx, paths[key])
                assert model.vertex_count > 1000
                frames = []
                for angle in (0.0, 1.5, 3.0, 4.5):
                    fbo.clear(0.098, 0.149, 0.20, 1.0)
                    proj, view, eye = fit_camera(model.bmin, model.bmax, 1.0)
                    model.draw((proj @ view).astype("f4"),
                               mat_mul(mat_rotate_y(angle)), eye)
                    arr = np.frombuffer(
                        fbo.read(components=4, alignment=1),
                        dtype=np.uint8).reshape(size, size, 4)
                    frames.append(arr.copy())
                    diff = np.abs(arr[:, :, :3].astype(np.int16) - bg).sum(axis=2)
                    ys, xs = np.where(diff > 40)
                    colored = arr[diff > 40][:, :3]
                    # Модель видима, полностью в кадре, по центру, текстурирована.
                    assert len(xs) > 3000, f"{key}: модель почти не видна"
                    assert ys.min() > 5 and ys.max() < size - 5, (
                        f"{key}: модель обрезана (y=[{ys.min()},{ys.max()}])")
                    assert abs((xs.min() + xs.max()) / 2 - size / 2) < 70, (
                        f"{key}: модель не по центру")
                    assert colored.std() > 10, f"{key}: нет текстур"
                # Поворот меняет изображение (витрина крутится).
                d = np.abs(frames[0].astype(int) - frames[1].astype(int)).sum()
                assert d > 100000, f"{key}: поворот не меняет кадр"
                model.release()
        finally:
            ctx.release()

class TestSlotMachineLabel:
    """Экран автомата: интервал фиксации цифр и итоговая строка."""

    def test_lock_interval_and_final_text(self):
        """Барабаны фиксируются слева направо каждые ~200 мс;
        после прокрутки отображается исходный пример."""
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QTimer
        from animated_widgets import SlotMachineLabel
        app = QApplication.instance() or QApplication([])

        w = SlotMachineLabel()
        locks: list = []
        w.reel_locked.connect(lambda k: locks.append((k, w._elapsed)))
        w.start_spin("25 + 5 ", interval_ms=200)
        assert w.spinning

        # Прокручиваем время вручную (без цикла событий) -- детерминированно.
        elapsed = 0
        while w.spinning and elapsed < 5000:
            elapsed += 40
            w._update_locks(elapsed)

        assert locks == [(1, 200), (2, 400), (3, 600)], locks
        assert not w.spinning
        assert w.text() == "25 + 5 "

        # Интервал между фиксациями -- 200 мс.
        ms = [m for _, m in locks]
        assert all(ms[i + 1] - ms[i] == 200 for i in range(len(ms) - 1))

    def test_placeholder_and_text(self):
        from PySide6.QtWidgets import QApplication
        from animated_widgets import SlotMachineLabel
        app = QApplication.instance() or QApplication([])
        w = SlotMachineLabel()
        assert w.text() == "…"
        w.show_placeholder()
        assert w.text() == "…"
        w.start_spin("7 × 8 ", interval_ms=200)
        assert w.text() == "7 × 8 "
        w.stop()
        assert not w.spinning

if __name__ == "__main__":
    # Запуск без pytest (для сред без pytest).
    sys.exit(pytest.main([__file__, "-v"]))
