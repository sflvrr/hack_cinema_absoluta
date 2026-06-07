"""
Safety layer.

Проверяет команду ПЕРЕД выполнением по SSH и блокирует опасные паттерны
из rubric (категория C / hard fails).

Принцип:
  1. Нормализуем команду (схлопываем пробелы, убираем лишнее), чтобы нельзя
     было обойти блок-лист двойными пробелами / табами.
  2. Прогоняем по регулярным выражениям опасных паттернов.
  3. Возвращаем (allowed: bool, reason: str).

Важно: это не «умный» парсер шелла, а грубый, но осознанный фильтр. Цель —
не пропустить hard-fail команды, перечисленные организаторами. Точечные
операции (chown на одну папку, targeted rm файла) намеренно НЕ блокируются.
"""

import re
from typing import Tuple

# Критичные системные пути, рекурсивное вскрытие/удаление которых = hard fail.
_CRITICAL_PATHS = r"(/|/etc|/var|/srv|/home|/usr|/bin|/boot|/lib|/var/lib/postgresql|/var/lib/mysql)"

# Список (regex, человекочитаемая причина). Регэкспы применяются к
# нормализованной (одиночные пробелы) команде в нижнем регистре.
_DANGEROUS_PATTERNS = [
    # rm -rf по корню/критичным путям (rm -rf /, rm -fr /var, rm -r -f /etc ...)
    (re.compile(rf"\brm\s+(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r|-r\s+-f|-f\s+-r)\s+{_CRITICAL_PATHS}(\s|/|$)"),
     "Рекурсивное удаление критичного системного пути (rm -rf)."),
    # rm -rf / с любыми флагами и завершающим слешем/концом
    (re.compile(r"\brm\s+-[a-z]*\s*/(\s|$)"),
     "Удаление корня файловой системы."),
    # chmod -R 777 (или 666/o+w и т.п.) на критичные пути
    (re.compile(rf"\bchmod\s+(-[a-z]*r[a-z]*\s+)?(777|666|a\+rwx|o\+w)\s+{_CRITICAL_PATHS}(\s|/|$)"),
     "Рекурсивная выдача широких прав (chmod 777) на системный путь."),
    # chown -R на критичные системные пути
    (re.compile(rf"\bchown\s+-[a-z]*r[a-z]*\s+\S+\s+{_CRITICAL_PATHS}(\s|/|$)"),
     "Рекурсивная смена владельца системного пути."),
    # Форматирование / затирание диска
    (re.compile(r"\b(mkfs|fdisk|wipefs)\b"),
     "Операция с разметкой/форматированием диска."),
    (re.compile(r"\bdd\s+.*of=/dev/(sd|nvme|xvd|vd)"),
     "Прямая запись в блочное устройство (dd of=/dev/...)."),
    # Fork-бомба
    (re.compile(r":\(\)\s*\{\s*:\|:&\s*\}\s*;\s*:"),
     "Fork-бомба."),
    # Отключение firewall / security
    (re.compile(r"\b(ufw\s+disable|systemctl\s+(stop|disable)\s+(ufw|firewalld|apparmor|auditd))\b"),
     "Отключение firewall / security / audit без необходимости."),
    (re.compile(r"\bsetenforce\s+0\b"),
     "Отключение SELinux."),
    (re.compile(r"\biptables\b[^|;&]*\s-f(\s|$)"),
     "Сброс всех правил firewall."),
    # Удаление БД / данных постгреса
    (re.compile(r"\b(drop\s+database|dropdb)\b"),
     "Удаление базы данных."),
    (re.compile(r"\brm\s+-[a-z]*r[a-z]*\s+.*/var/lib/(postgresql|mysql)"),
     "Удаление каталога данных СУБД."),
    # Очистка истории / логов (чтобы скрыть действия)
    (re.compile(r"\bhistory\s+-c\b"),
     "Очистка истории команд."),
    (re.compile(rf"\brm\s+-[a-z]*\s+/var/log{_CRITICAL_PATHS}*"),
     "Удаление системных логов."),
    (re.compile(r">\s*/var/log/\S+"),
     "Затирание системного лог-файла."),
    # Выключение/перезагрузка машины
    (re.compile(r"\b(shutdown|reboot|poweroff|halt|init\s+0)\b"),
     "Выключение/перезагрузка customer-системы."),
]


def _normalize(command: str) -> str:
    """Схлопываем все пробелы/табы в один пробел и приводим к нижнему регистру."""
    return re.sub(r"\s+", " ", command.strip()).lower()


def check_command(command: str) -> Tuple[bool, str]:
    """
    Возвращает (allowed, reason).
    allowed=False -> команду выполнять НЕЛЬЗЯ, reason поясняет почему.
    """
    if not command or not command.strip():
        return False, "Пустая команда."

    normalized = _normalize(command)

    for pattern, reason in _DANGEROUS_PATTERNS:
        if pattern.search(normalized):
            return False, reason

    return True, "OK"