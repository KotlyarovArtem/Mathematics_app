# -*- coding: utf-8 -*-
"""
Менеджер статистики: сохранение и чтение данных учеников.

Статистика хранится в отдельных JSON-файлах (по одному на пользователя) в
каталоге ``data``. Для каждого класса ведётся отдельный набор сессий, поэтому
один и тот же ученик, обучающийся в разных классах, имеет независимую историю
(требование 3.3 и 3.11).
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Dict, List, Optional

from math_engine import grade_from_percent


# ---------------------------------------------------------------------------
#  Утилиты
# ---------------------------------------------------------------------------
def _safe_filename(name: str) -> str:
    """Преобразует имя пользователя в безопасное имя файла.

    Разрешаем кириллицу и латиницу, цифры, дефис и пробел (превращается в _).
    Пустое имя становится ``user``.
    """
    cleaned = re.sub(r"[^\w\u0400-\u04FF\- ]", "", name, flags=re.UNICODE)
    cleaned = cleaned.strip().replace(" ", "_")
    return cleaned if cleaned else "user"


def _new_session_record(total: int, correct: int, grade: Optional[int],
                        problems: Optional[List[str]] = None) -> Dict:
    """Создаёт запись одной сессии (включая список показанных примеров)."""
    return {
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "timestamp": int(time.time()),
        "total_answers": total,
        "correct_answers": correct,
        "wrong_answers": total - correct,
        "grade": grade,
        "problems": list(problems) if problems else [],
    }


# ---------------------------------------------------------------------------
#  Менеджер статистики
# ---------------------------------------------------------------------------
class StatsManager:
    """Чтение/запись статистики по ученикам и классам.

    Файл статистики пользователя имеет вид::

        {
          "name": "Маша",
          "age": 8,
          "grades": {
            "1": {
              "total_answers": 10,
              "correct_answers": 8,
              "wrong_answers": 2,
              "grade": 4,
              "sessions": [ { ... }, ... ]
            },
            ...
          }
        }
    """

    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)

    # ------------------------------------------------------------------
    #  Низкоуровневые операции с файлами
    # ------------------------------------------------------------------
    def _path_for(self, name: str) -> str:
        """Возвращает путь к JSON-файлу пользователя по его имени."""
        return os.path.join(self.data_dir, f"{_safe_filename(name)}.json")

    def _load(self, name: str) -> Optional[Dict]:
        """Загружает данные пользователя или None, если файла нет."""
        path = self._path_for(name)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                return None
            data.setdefault("grades", {})
            return data
        except (json.JSONDecodeError, OSError):
            # Повреждённый файл -- считаем, что данных нет.
            return None

    def _save(self, name: str, data: Dict) -> None:
        """Сохраняет данные пользователя (с резервной копией)."""
        path = self._path_for(name)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)  # атомарная замена

    # ------------------------------------------------------------------
    #  Публичный API
    # ------------------------------------------------------------------
    def get_user(self, name: str, age: int) -> Dict:
        """Возвращает (или создаёт) запись пользователя."""
        data = self._load(name)
        if data is None:
            data = {"name": name.strip(), "age": int(age), "grades": {}}
            self._save(name, data)
        else:
            # Обновляем возраст при необходимости.
            if data.get("age") != int(age):
                data["age"] = int(age)
                self._save(name, data)
        return data

    def has_user(self, name: str) -> bool:
        """Есть ли уже сохранённый пользователь с таким именем?"""
        return self._load(name) is not None

    def list_users(self) -> List[str]:
        """Список имён всех сохранённых пользователей."""
        users = []
        if not os.path.isdir(self.data_dir):
            return users
        for fname in os.listdir(self.data_dir):
            if fname.endswith(".json"):
                path = os.path.join(self.data_dir, fname)
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                    if isinstance(data, dict) and data.get("name"):
                        users.append(data["name"])
                except (json.JSONDecodeError, OSError):
                    continue
        return sorted(users)

    def _grade_block(self, data: Dict, grade: int) -> Dict:
        """Возвращает (или создаёт) блок статистики конкретного класса."""
        key = str(grade)
        grades = data.setdefault("grades", {})
        block = grades.get(key)
        if not isinstance(block, dict):
            block = {
                "total_answers": 0,
                "correct_answers": 0,
                "wrong_answers": 0,
                "grade": None,
                "sessions": [],
            }
            grades[key] = block
        block.setdefault("sessions", [])
        return block

    def record_session(self, name: str, age: int, grade: int,
                       total: int, correct: int,
                       problems: Optional[List[str]] = None) -> Dict:
        """Записывает завершённую сессию и пересчитывает агрегаты.

        ``problems`` -- список строк показанных примеров; используется, чтобы
        новые сессии не повторяли задания трёх ближайших сессий.

        Возвращает словарь с детальной сводкой для показа в окне статистики::

            {"session_grade": 4, "class_grade": 4.5, ...}
        """
        data = self.get_user(name, age)
        block = self._grade_block(data, grade)

        session_grade = grade_from_percent(correct, total)
        record = _new_session_record(total, correct, session_grade, problems)
        block["sessions"].append(record)

        # Агрегаты по классу.
        block["total_answers"] += total
        block["correct_answers"] += correct
        block["wrong_answers"] += (total - correct)
        # Оценка класса -- среднее по всем оценкам сессий.
        session_grades = [s["grade"] for s in block["sessions"]
                          if s.get("grade") is not None]
        block["grade"] = (round(sum(session_grades) / len(session_grades), 2)
                          if session_grades else None)

        self._save(name, data)

        return {
            "session_grade": session_grade,
            "class_grade": block["grade"],
            "session_total": total,
            "session_correct": correct,
            "session_wrong": total - correct,
            "class_total": block["total_answers"],
            "class_correct": block["correct_answers"],
            "class_wrong": block["wrong_answers"],
            "class_sessions": len(block["sessions"]),
            "sessions": list(block["sessions"]),
        }

    def get_stats(self, name: str, grade: int) -> Optional[Dict]:
        """Возвращает блок статистики класса или None, если данных нет."""
        data = self._load(name)
        if data is None:
            return None
        return data.get("grades", {}).get(str(grade))

    def recent_problems(self, name: str, grade: int, count: int = 3) -> set:
        """Множество примеров из ``count`` последних сессий класса.

        Используется генератором, чтобы задания не повторялись в течение
        трёх ближайших сессий (требование заказа).
        """
        block = self.get_stats(name, grade)
        if not block:
            return set()
        recent: set = set()
        for session in block.get("sessions", [])[-count:]:
            recent.update(session.get("problems", []))
        return recent
