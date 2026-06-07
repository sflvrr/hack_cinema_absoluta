"""
SSH runner.

Выполняет ОДНУ одобренную команду на customer-VM по SSH.

Исправлены баги исходной версии:
  - os.basename -> os.path.basename (раньше падало при первом неудачном ключе);
  - SSHClient пересоздаётся на каждой итерации перебора ключей;
  - поддержка не только RSA, но и Ed25519 / ECDSA ключей
    (Azure VM часто используют Ed25519);
  - клиент всегда закрывается (finally);
  - явные таймауты на коннект и на выполнение команды (категория E).

Safety-проверка вызывается ДО подключения (см. safety.check_command).
"""

import os
import glob
import logging
from typing import List, Optional

import paramiko

from .safety import check_command

logger = logging.getLogger(__name__)

SSH_USERNAME = os.getenv("SSH_USERNAME", "azureuser")
SSH_CONNECT_TIMEOUT = 10
SSH_EXEC_TIMEOUT = 30

# Классы ключей, которые пробуем загрузить из одного .pem.
# (DSA намеренно опущен — устарел и на Azure VM не встречается.)
_KEY_CLASSES = [
    paramiko.RSAKey,
    paramiko.Ed25519Key,
    paramiko.ECDSAKey,
]


def _find_key_paths() -> List[str]:
    """Ищем .pem сначала в /keys (docker volume), затем локально в keys/."""
    paths = glob.glob("/keys/*.pem")
    if not paths:
        paths = glob.glob("keys/*.pem")
    return paths


def _load_key(key_path: str) -> Optional[paramiko.PKey]:
    """Пробуем загрузить ключ как RSA/Ed25519/ECDSA — что подойдёт."""
    for key_cls in _KEY_CLASSES:
        try:
            return key_cls.from_private_key_file(key_path)
        except paramiko.SSHException:
            continue
        except Exception as e:  # noqa: BLE001 — логируем и пробуем следующий тип
            logger.debug(f"Не удалось загрузить {os.path.basename(key_path)} как {key_cls.__name__}: {e}")
            continue
    return None


def run_ssh_command(ip: str, command: str) -> str:
    """
    Выполняет команду на VM. Возвращает строку: вывод команды ИЛИ текст ошибки.
    Команда сначала проходит safety-проверку.
    """
    allowed, reason = check_command(command)
    if not allowed:
        logger.warning(f"BLOCKED command on {ip}: {reason} | cmd={command!r}")
        return f"BLOCKED BY SAFETY LAYER: {reason}"

    key_files = _find_key_paths()
    if not key_files:
        return "SSH Error: файлы ключей (.pem) не найдены в /keys или keys/"

    last_error = "no keys tried"

    for key_path in key_files:
        key = _load_key(key_path)
        if key is None:
            last_error = f"Не удалось распознать формат ключа {os.path.basename(key_path)}"
            continue

        # Новый клиент на каждую попытку — переиспользовать «грязный» нельзя.
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            logger.info(f"Подключение к {ip} ключом {os.path.basename(key_path)}...")
            client.connect(
                hostname=ip,
                username=SSH_USERNAME,
                pkey=key,
                timeout=SSH_CONNECT_TIMEOUT,
                banner_timeout=SSH_CONNECT_TIMEOUT,
                auth_timeout=SSH_CONNECT_TIMEOUT,
            )
            logger.info(f"Успех. Выполняем команду на {ip}...")
            _, stdout, stderr = client.exec_command(command, timeout=SSH_EXEC_TIMEOUT)
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            output = out + err
            return output if output.strip() else "[Command executed successfully, no output]"

        except paramiko.AuthenticationException:
            last_error = f"Auth failed with {os.path.basename(key_path)}"
            logger.info(last_error)
            continue
        except Exception as e:  # noqa: BLE001
            logger.error(f"SSH error for {ip} with {os.path.basename(key_path)}: {e}")
            last_error = str(e)
            continue
        finally:
            client.close()

    return f"SSH Connection Error: не удалось подключиться ни одним ключом. Последняя ошибка: {last_error}"