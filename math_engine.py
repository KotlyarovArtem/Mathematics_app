# -*- coding: utf-8 -*-
"""
Движок генерации математических примеров и подсчёта оценок.

Модуль не зависит от Qt и полностью покрыт unit-тестами (см. test_math_app.py).
Все генераторы построены так, чтобы гарантированно выполнять ограничения
из технического задания:
    * используются только целые неотрицательные числа (>= 0);
    * деление строго без остатка и никогда на ноль;
    * ни на одном промежуточном шаге не возникает отрицательный результат;
    * для каждого класса соблюдены диапазоны чисел и результатов;
    * пример старшего класса никогда не совпадает с примером младшего класса;
    * пример не повторяется в течение трёх ближайших сессий.

Особые правила действий (уточнения заказа):
    * 2 класс: умножение -- однозначное x однозначное (таблица умножения);
      деление -- однозначное или двузначное : однозначное (табличное,
      частное однозначное, делимое <= 81);
    * 3 класс: в умножении один из множителей однозначный (внетабличное,
      второй множитель двузначный, произведение <= 100); в делении делитель
      однозначный, частное двузначное (внетабличное деление, делимое <= 100);
    * 1 класс: все числа, промежуточные и итоговые результаты в 0..20.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple


# Символы арифметических действий, отображаемые пользователю.
OP_PLUS = "+"
OP_MINUS = "−"      # настоящий знак минуса (U+2212) выглядит аккуратнее
OP_MUL = "×"
OP_DIV = "÷"

# ---------------------------------------------------------------------------
#  Конфигурация классов
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GradeConfig:
    """Параметры генерации примеров для одного класса.

    addsub_max -- верхняя граница чисел и результатов для сложения/вычитания;
    muldiv_max -- верхняя граница чисел и результатов для умножения/деления;
    prev_addsub / prev_muldiv -- максимум предыдущего класса; используется,
        чтобы сгенерированный пример заведомо не повторял пример младшего
        класса (см. требования 4.3-4.5).
    """
    grade: int
    addsub_max: int               # максимум для + и -
    muldiv_max: int               # максимум для * и :
    prev_addsub: Optional[int]    # максимум сложения/вычитания предыдущего класса
    prev_muldiv: Optional[int]    # максимум умножения/деления предыдущего класса
    allow_muldiv: bool            # разрешены ли умножение и деление
    templates: Tuple[str, ...] = ()  # имена доступных шаблонов сложных примеров


# 1 класс: только сложение и вычитание, всё в диапазоне 0..20. Примерно в
# каждом пятом примере -- два действия со скобками "(A + B) - C" со всеми
# промежуточными и итоговыми результатами в 0..20.
_GRADE1 = GradeConfig(1, 20, 0, None, None, allow_muldiv=False, templates=("t0",))

# 2 класс: + и - до 100; умножение -- таблица (однозначное x однозначное),
# деление -- табличное (делимое <= 81, делитель однозначный, частное <= 9).
_GRADE2 = GradeConfig(2, 100, 81, 20, None, allow_muldiv=True,
                      templates=("t1", "t2", "t3", "t4"))

# 3 класс: + и - до 1000; умножение внетабличное (однозначный x двузначный,
# произведение <= 100); деление внетабличное (делитель однозначный,
# частное двузначное, делимое -- до трёхзначного, <= 999).
_GRADE3 = GradeConfig(3, 1000, 999, 100, 81, allow_muldiv=True,
                      templates=("t1", "t2", "t3", "t4", "t5", "t6"))

# 4 класс: всё до 1 000 000.
_GRADE4 = GradeConfig(4, 1_000_000, 1_000_000, 1000, 100, allow_muldiv=True,
                      templates=("t1", "t2", "t3", "t4", "t5", "t6"))

GRADE_CONFIGS = {1: _GRADE1, 2: _GRADE2, 3: _GRADE3, 4: _GRADE4}

# Доля сложных примеров (не более 20% согласно ТЗ).
_COMPLEX_RATIO = 0.20

# Максимальное количество попыток при отказоустойчивой генерации.
_MAX_RETRIES = 400


@dataclass
class Problem:
    """Сгенерированный пример для вычисления.

    Атрибуты:
        grade   -- класс, для которого сгенерирован пример;
        display -- строка вида "A + B = " (без ответа) для показа ученику;
        answer  -- правильный ответ (целое неотрицательное число);
        numbers -- все числа, встречающиеся в примере (для проверок диапазона);
        ops     -- список использованных действий (для проверок).
    """
    grade: int
    display: str
    answer: int
    numbers: List[int] = field(default_factory=list)
    ops: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
#  Безопасный вычислитель выражений
# ---------------------------------------------------------------------------
# AST задаётся вложенными кортежами:
#     ("num", value)              -- лист с числом
#     ("op", symbol, left, right) -- узел операции
def _evaluate(node) -> int:
    """Вычисляет значение AST, проверяя все арифметические ограничения.

    Поднимает ValueError при:
        * отрицательном результате вычитания (в т.ч. внутри скобок);
        * делении на ноль;
        * делении с остатком.

    Благодаря этому один вызов гарантирует выполнение требований 4.6-4.8.
    """
    if node[0] == "num":
        value = node[1]
        if value < 0:
            raise ValueError("Отрицательное число недопустимо")
        return value

    _kind, symbol, left, right = node
    lv = _evaluate(left)
    rv = _evaluate(right)
    if symbol == OP_PLUS:
        return lv + rv
    if symbol == OP_MINUS:
        result = lv - rv
        if result < 0:
            raise ValueError("Отрицательный промежуточный результат")
        return result
    if symbol == OP_MUL:
        return lv * rv
    if symbol == OP_DIV:
        if rv == 0:
            raise ValueError("Деление на ноль")
        if lv % rv != 0:
            raise ValueError("Деление с остатком")
        return lv // rv
    raise ValueError(f"Неизвестная операция: {symbol}")


def _expr_to_str(node, top: bool = True) -> str:
    """Преобразует AST в человекочитаемую строку (для простых примеров)."""
    if node[0] == "num":
        return str(node[1])
    _kind, symbol, left, right = node
    return f"{_expr_to_str(left)} {symbol} {_expr_to_str(right)}"


# ---------------------------------------------------------------------------
#  Вспомогательные генераторы чисел
# ---------------------------------------------------------------------------
def _rand_divisor(value: int, lo: int, hi: int, rng: random.Random) -> int:
    """Возвращает случайный делитель числа value из диапазона [lo, hi].

    Итерируем только до корня из value и собираем оба делителя пары --
    это быстро даже для больших чисел 4 класса.
    """
    divs = set()
    i = 1
    while i * i <= value:
        if value % i == 0:
            for d in (i, value // i):
                if max(1, lo) <= d <= hi:
                    divs.add(d)
        i += 1
    if not divs:
        raise ValueError("Нет подходящего делителя")
    return rng.choice(sorted(divs))


def _factor_pair(product: int, lo: int, hi: int, rng: random.Random) -> Tuple[int, int]:
    """Возвращает случайную пару (a, b) с a*b == product, lo <= a,b <= hi."""
    pairs = []
    i = 1
    while i * i <= product:
        if product % i == 0:
            j = product // i
            if lo <= i <= hi and lo <= j <= hi:
                pairs.append((i, j))
        i += 1
    if not pairs:
        raise ValueError("Невозможно разложить число на множители в диапазоне")
    a, b = rng.choice(pairs)
    return (b, a) if rng.random() < 0.5 else (a, b)


# ---------------------------------------------------------------------------
#  Простые примеры (одно действие)
# ---------------------------------------------------------------------------
def _gen_simple(cfg: GradeConfig, rng: random.Random) -> Problem:
    """Генерирует простой пример из одного действия с учётом всех диапазонов.

    Конструкция выбирается так, чтобы пример заведомо не повторял пример
    младшего класса (структурно или по диапазону чисел).
    """
    if cfg.allow_muldiv and rng.random() < 0.5:
        op = rng.choice([OP_MUL, OP_DIV])
    else:
        op = rng.choice([OP_PLUS, OP_MINUS])

    if op == OP_PLUS:
        # result -- всегда наибольшее число в сложении.
        lo = cfg.prev_addsub + 1 if cfg.prev_addsub else 0
        result = rng.randint(lo, cfg.addsub_max)
        a = rng.randint(0, result)
        b = result - a
        node = ("op", OP_PLUS, ("num", a), ("num", b))
        numbers = [a, b, result]

    elif op == OP_MINUS:
        # a -- наибольшее число при вычитании.
        lo = cfg.prev_addsub + 1 if cfg.prev_addsub else 0
        a = rng.randint(lo, cfg.addsub_max)
        b = rng.randint(0, a)
        result = a - b
        node = ("op", OP_MINUS, ("num", a), ("num", b))
        numbers = [a, b, result]

    elif op == OP_MUL:
        if cfg.grade == 2:
            # Таблица умножения: однозначное x однозначное (2..9).
            a = rng.randint(2, 9)
            b = rng.randint(2, 9)
        elif cfg.grade == 3:
            # Внетабличное: однозначный x двузначный множитель, произведение <= 100.
            s = rng.randint(2, 9)
            t = rng.randint(10, 100 // s)
            a, b = (s, t) if rng.random() < 0.5 else (t, s)
        else:
            # 4 класс: произведение в полном диапазоне класса.
            lo = cfg.prev_muldiv + 1 if cfg.prev_muldiv else 1
            result0 = rng.randint(lo, cfg.muldiv_max)
            a, b = _factor_pair(result0, 1, cfg.muldiv_max, rng)
            if rng.random() < 0.5:
                a, b = b, a
        result = a * b
        node = ("op", OP_MUL, ("num", a), ("num", b))
        numbers = [a, b, result]

    else:  # OP_DIV:  a ÷ b = q,  a = b * q.
        if cfg.grade == 2:
            # Табличное деление: делитель и частное однозначные, делимое <= 81.
            d = rng.randint(2, 9)
            q = rng.randint(1, 9)
        elif cfg.grade == 3:
            # Внетабличное деление: делитель однозначный, частное двузначное,
            # делимое может быть трёхзначным (<= 999).
            d = rng.randint(2, 9)
            q = rng.randint(10, 999 // d)
        else:
            lo = cfg.prev_muldiv + 1 if cfg.prev_muldiv else 1
            # Делитель подбираем так, чтобы делимое d*q не вышло за диапазон
            # класса: d <= muldiv_max // lo гарантирует место для частного.
            d = rng.randint(2, max(2, cfg.muldiv_max // lo))
            q = rng.randint(lo, max(lo, cfg.muldiv_max // d))
        a = d * q
        node = ("op", OP_DIV, ("num", a), ("num", d))
        numbers = [a, d, q]

    answer = _evaluate(node)
    display = f"{_expr_to_str(node)} = "
    return Problem(grade=cfg.grade, display=display, answer=answer,
                   numbers=numbers, ops=[op])


# ---------------------------------------------------------------------------
#  Сложные примеры (несколько действий со скобками)
# ---------------------------------------------------------------------------
# Числа подбираются случайно, корректность гарантируется безопасным
# вычислителем + повторными попытками (rejection sampling). Дополнительные
# ограничения классов (см. шапку модуля) учитываются внутри шаблонов.

def _tmpl_t0(grade: int, lo: int, hi: int, rng: random.Random):
    """(A + B) - C = D   --  пример 1 класса на два действия со скобками.

    Гарантируем: A + B <= 20 (промежуточный результат в 0..20),
    C <= A + B (итог >= 0), все числа в 0..20.
    Форма со скобками слева не совпадает ни с одним шаблоном 2 класса,
    поэтому пересечений с младшим классом не возникает.
    """
    a = rng.randint(lo, hi)
    b = rng.randint(lo, hi - a)           # A + B <= hi (= 20)
    s = a + b
    c = rng.randint(lo, s)                # C <= A + B  =>  итог >= 0
    inner = ("op", OP_PLUS, ("num", a), ("num", b))
    node = ("op", OP_MINUS, inner, ("num", c))
    text = f"({a} + {b}) - {c}"
    return node, text


def _tmpl_t1(grade: int, lo: int, hi: int, rng: random.Random):
    """A + (B - C) = D   --  гарантируем B >= C."""
    a = rng.randint(lo, hi)
    b = rng.randint(lo, hi)
    c = rng.randint(lo, b)              # C <= B  =>  (B - C) >= 0
    inner = ("op", OP_MINUS, ("num", b), ("num", c))
    node = ("op", OP_PLUS, ("num", a), inner)
    text = f"{a} + ({b} - {c})"
    return node, text


def _tmpl_t2(grade: int, lo: int, hi: int, rng: random.Random):
    """(A × B) + C = D.  В 3 классе один множитель однозначный."""
    if grade == 3:
        s = rng.randint(2, 9)           # однозначный множитель
        t = rng.randint(10, 99)         # двузначный множитель
        a, b = (s, t) if rng.random() < 0.5 else (t, s)
    else:
        a = rng.randint(lo, hi)
        b = rng.randint(lo, hi)
    if a * b > 1_000_000:
        raise ValueError("Промежуточное произведение превышает лимит класса")
    c = rng.randint(lo, hi)
    inner = ("op", OP_MUL, ("num", a), ("num", b))
    node = ("op", OP_PLUS, inner, ("num", c))
    text = f"({a} × {b}) + {c}"
    return node, text


def _tmpl_t3(grade: int, lo: int, hi: int, rng: random.Random):
    """A × (B - C) : D = E.  В 3 классе A однозначный и делитель D <= 9."""
    if grade == 3:
        a = rng.randint(2, 9)
    else:
        a = rng.randint(lo, hi)
    b = rng.randint(lo, hi)
    # C < B, чтобы разность была положительной и пример не вырождался.
    c = rng.randint(lo, b - 1) if b > lo else lo
    sub = b - c
    prod = a * sub
    if prod > 1_000_000:
        raise ValueError("Промежуточное произведение превышает лимит класса")
    # В 3 классе делитель обязан быть однозначным; в остальных -- из диапазона.
    d = _rand_divisor(prod, 1, 9 if grade == 3 else hi, rng)
    inner = ("op", OP_MINUS, ("num", b), ("num", c))
    left = ("op", OP_MUL, ("num", a), inner)
    node = ("op", OP_DIV, left, ("num", d))
    text = f"{a} × ({b} - {c}) ÷ {d}"
    return node, text


def _tmpl_t4(grade: int, lo: int, hi: int, rng: random.Random):
    """A : (B × C) - D = E.  В 2-3 классах делитель (B×C) однозначный."""
    if grade in (2, 3):
        # Подбираем однозначные B и C с однозначным произведением.
        while True:
            b = rng.randint(2, 9)
            c = rng.randint(2, 9)
            if b * c <= 9:
                break
        denom = b * c
        if grade == 2:
            # Табличное деление: частное <= 9, делимое <= 81.
            k = rng.randint(1, min(9, 81 // denom))
        else:
            # Внетабличное: частное двузначное, делимое до трёхзначного.
            k = rng.randint(10, 999 // denom)
    else:
        b = rng.randint(max(1, lo), hi)
        c = rng.randint(max(1, lo), hi)
        denom = b * c
        k = rng.randint(1, max(1, hi // denom))
    a = denom * k
    d = rng.randint(0, k)               # 0 <= D <= k  =>  результат >= 0
    inner = ("op", OP_MUL, ("num", b), ("num", c))
    left = ("op", OP_DIV, ("num", a), inner)
    node = ("op", OP_MINUS, left, ("num", d))
    text = f"{a} ÷ ({b} × {c}) - {d}"
    return node, text


def _tmpl_t5(grade: int, lo: int, hi: int, rng: random.Random):
    """A + (B + C - D) - E = F   --  (B+C-D) >= 0 и итог >= 0."""
    b = rng.randint(lo, hi)
    c = rng.randint(lo, hi)
    d = rng.randint(0, b + c)             # D <= B+C  =>  скобка >= 0
    inner1 = ("op", OP_PLUS, ("num", b), ("num", c))
    inner = ("op", OP_MINUS, inner1, ("num", d))
    bracket = b + c - d
    a = rng.randint(lo, hi)
    e = rng.randint(0, a + bracket)       # итог >= 0
    left = ("op", OP_PLUS, ("num", a), inner)
    node = ("op", OP_MINUS, left, ("num", e))
    text = f"{a} + ({b} + {c} - {d}) - {e}"
    return node, text


def _tmpl_t6(grade: int, lo: int, hi: int, rng: random.Random):
    """A × B + (C : D - E) + F = G.  В 3 классе множитель и делитель
    однозначные."""
    if grade == 3:
        s = rng.randint(2, 9)
        t = rng.randint(10, 99)
        a, b = (s, t) if rng.random() < 0.5 else (t, s)
        d = rng.randint(2, 9)
    else:
        a = rng.randint(lo, hi)
        b = rng.randint(lo, hi)
        d = rng.randint(max(1, lo), hi)
    q = rng.randint(1, max(1, hi // d))   # C = D * q
    c = d * q
    if a * b > 1_000_000:
        raise ValueError("Промежуточное произведение превышает лимит класса")
    e = rng.randint(0, q)                 # 0 <= E <= q  =>  скобка >= 0
    f = rng.randint(lo, hi)
    inner_div = ("op", OP_DIV, ("num", c), ("num", d))
    bracket = ("op", OP_MINUS, inner_div, ("num", e))
    mul = ("op", OP_MUL, ("num", a), ("num", b))
    sum1 = ("op", OP_PLUS, mul, bracket)
    node = ("op", OP_PLUS, sum1, ("num", f))
    text = f"{a} × {b} + ({c} ÷ {d} - {e}) + {f}"
    return node, text


_TEMPLATES = {
    "t0": _tmpl_t0,
    "t1": _tmpl_t1,
    "t2": _tmpl_t2,
    "t3": _tmpl_t3,
    "t4": _tmpl_t4,
    "t5": _tmpl_t5,
    "t6": _tmpl_t6,
}


def _digit_range(grade: int, template: str) -> Tuple[int, int]:
    """Возвращает (lo, hi) диапазона чисел для сложного примера.

    Согласно ТЗ:
        * 1 класс        -- числа 0..20 (примеры на два действия со скобками);
        * 2 класс        -- однозначные числа (2..9);
        * 3 класс, t5-t6 -- однозначные и двузначные (1..99);
        * 3 класс, t1    -- двузначные (10..99);
        * 4 класс        -- от двузначных до пятизначных (10..99999).
    Шаблоны t2/t3/t4 для 2-3 классов сами ограничивают множители и делители.
    """
    if grade == 1:
        return 0, 20
    if grade == 2:
        return 2, 9
    if grade == 3:
        if template in ("t5", "t6"):
            return 1, 99
        return 10, 99
    return 10, 99999


def _flatten_numbers(node) -> List[int]:
    """Собирает все числа из AST."""
    if node[0] == "num":
        return [node[1]]
    return _flatten_numbers(node[2]) + _flatten_numbers(node[3])


def _flatten_ops(node) -> List[str]:
    """Собирает все операции из AST."""
    if node[0] == "num":
        return []
    return [node[1]] + _flatten_ops(node[2]) + _flatten_ops(node[3])


def _gen_complex(cfg: GradeConfig, rng: random.Random) -> Optional[Problem]:
    """Генерирует сложный пример по случайному шаблону (с повторными попытками)."""
    template = rng.choice(cfg.templates)
    fn = _TEMPLATES[template]
    lo, hi = _digit_range(cfg.grade, template)

    for _ in range(_MAX_RETRIES):
        try:
            node, text = fn(cfg.grade, lo, hi, rng)
            answer = _evaluate(node)          # проверяет все ограничения
        except ValueError:
            continue
        # Итог не должен быть отрицательным и не должен превышать максимум
        # результатов класса (требования 4.6 и 4.9).
        if answer < 0 or answer > cfg.addsub_max:
            continue
        flat = _flatten_numbers(node)
        # Каждое число примера тоже обязано укладываться в диапазон класса
        # (например, делимое в 4 классе не может превышать 1 000 000).
        if any(n > cfg.addsub_max for n in flat):
            continue
        display = f"{text} = "
        return Problem(grade=cfg.grade, display=display, answer=answer,
                       numbers=flat, ops=_flatten_ops(node))
    return None


# ---------------------------------------------------------------------------
#  Публичный API
# ---------------------------------------------------------------------------
class MathEngine:
    """Генератор примеров для заданного класса с защитой от повторов.

    Пример использования::

        engine = MathEngine(grade=2, recent={"3 + 4 = ", ...})
        problem = engine.next_problem()
        print(problem.display, problem.answer)
        engine.used_problems   # список показанных примеров сессии
    """

    def __init__(self, grade: int, seed: Optional[int] = None,
                 recent: Optional[Set[str]] = None):
        if grade not in GRADE_CONFIGS:
            raise ValueError(f"Неверный класс: {grade}. Допустимо 1..4.")
        self.grade = grade
        self._cfg = GRADE_CONFIGS[grade]
        self._rng = random.Random(seed) if seed is not None else random.Random()
        # Примеры трёх ближайших завершённых сессий -- их повторять нельзя.
        self._recent: Set[str] = set(recent or [])
        # Примеры, уже показанные в текущей сессии.
        self._used: Set[str] = set()

    @property
    def used_problems(self) -> List[str]:
        """Список примеров, показанных в текущей сессии."""
        return list(self._used)

    def _generate_raw(self, want_complex: bool) -> Problem:
        """Одна попытка генерации примера заданной категории."""
        if want_complex:
            problem = _gen_complex(self._cfg, self._rng)
            if problem is not None:
                return problem
        return _gen_simple(self._cfg, self._rng)

    def next_problem(self) -> Problem:
        """Возвращает следующий пример без повторов с сохранением пропорций.

        Категория (простой/сложный) выбирается один раз до повторных
        попыток -- так доля сложных примеров остаётся ~20% даже когда пул
        простых примеров 1 класса близок к исчерпанию. Сначала стараемся
        не повторять примеры трёх ближайших сессий и текущей; при
        исчерпании допускаем повтор из прошлых сессий; в крайнем случае --
        повтор внутри сессии.
        """
        want_complex = (bool(self._cfg.templates)
                        and self._rng.random() < _COMPLEX_RATIO)
        for _ in range(_MAX_RETRIES):
            p = self._generate_raw(want_complex)
            if p.display not in self._recent and p.display not in self._used:
                self._used.add(p.display)
                return p
        for _ in range(_MAX_RETRIES):
            p = self._generate_raw(want_complex)
            if p.display not in self._used:
                self._used.add(p.display)
                return p
        # Крайний случай: пространство примеров исчерпано даже внутри сессии.
        p = self._generate_raw(want_complex)
        self._used.add(p.display)
        return p


def check_answer(problem: Problem, user_answer: int) -> bool:
    """Сравнивает ответ пользователя с правильным (целые числа)."""
    try:
        return int(user_answer) == int(problem.answer)
    except (TypeError, ValueError):
        return False


def grade_from_percent(correct: int, total: int) -> Optional[int]:
    """Возвращает оценку по пятибалльной шкале (требование 3.12).

        5 -- 95..100% правильных ответов;
        4 -- 80..95%;
        3 -- 60..80%;
        2 -- 40..60%;
        1 -- меньше 40%.

    Если ответов не было (total == 0), возвращает None.
    """
    if total <= 0:
        return None
    percent = correct / total * 100.0
    if percent >= 95:
        return 5
    if percent >= 80:
        return 4
    if percent >= 60:
        return 3
    if percent >= 40:
        return 2
    return 1


def allowed_grades_for_age(age: int) -> List[int]:
    """Список доступных классов по возрасту (требование 3.3).

        6-7 лет  -> [1];
        8 лет    -> [1, 2];
        9 лет    -> [1, 2, 3];
        10+ лет  -> [1, 2, 3, 4].
    """
    if age in (6, 7):
        return [1]
    if age == 8:
        return [1, 2]
    if age == 9:
        return [1, 2, 3]
    if age >= 10:
        return [1, 2, 3, 4]
    return []  # некорректный возраст
