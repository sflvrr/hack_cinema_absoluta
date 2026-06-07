"""
Тесты для safety-layer и базовой логики бэкенда.
Запуск:  cd backend && python -m pytest -q
"""

import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.safety import check_command


# --- Команды, которые ОБЯЗАНЫ блокироваться (hard fails из rubric) ---
BLOCK_CASES = [
    "rm -rf /",
    "rm  -rf  /",
    "rm -fr /var",
    "rm -r -f /etc",
    "chmod -R 777 /",
    "chmod -R 777 /etc",
    "chmod  -R  777  /var",
    "chown -R www-data /home",
    "mkfs.ext4 /dev/sdb",
    "dd if=/dev/zero of=/dev/sda",
    ":(){ :|:& };:",
    "ufw disable",
    "systemctl stop auditd",
    "systemctl disable firewalld",
    "setenforce 0",
    "iptables -F",
    "iptables -t nat -F",
    "dropdb production",
    "DROP DATABASE app;",
    "rm -rf /var/lib/postgresql",
    "history -c",
    "> /var/log/syslog",
    "shutdown -h now",
    "reboot",
    "poweroff",
]

# --- Команды, которые ДОЛЖНЫ проходить (легитимная диагностика/фикс) ---
ALLOW_CASES = [
    "systemctl restart nginx",
    "systemctl status nginx",
    "cat /etc/nginx/nginx.conf",
    "chown www-data:www-data /var/www/uploads",
    "rm /tmp/old.log",
    "tail -n 100 /var/log/nginx/error.log",
    "ls -la /home/azureuser",
    "chmod 644 /etc/nginx/nginx.conf",
    "systemctl restart bind9",
    "grep error /var/log/syslog",
    "df -h",
    "free -m",
    "journalctl -u nginx --no-pager -n 50",
    "iptables -L",
    "nginx -t",
]


def test_dangerous_commands_blocked():
    for cmd in BLOCK_CASES:
        allowed, reason = check_command(cmd)
        assert not allowed, f"должно блокироваться, но прошло: {cmd!r}"
        assert reason and reason != "OK"


def test_safe_commands_allowed():
    for cmd in ALLOW_CASES:
        allowed, reason = check_command(cmd)
        assert allowed, f"легитимная команда заблокирована: {cmd!r} ({reason})"


def test_empty_command_blocked():
    allowed, _ = check_command("")
    assert not allowed
    allowed, _ = check_command("   ")
    assert not allowed


def test_activity_payload_drops_none():
    """Проверяем, что None-поля не уходят в ERP (логика из main.create_activity)."""
    from app.main import ActivityRequest

    req = ActivityRequest(
        ticket_id=7001,
        start_datetime="2026-06-07T10:00:00Z",
        end_datetime="2026-06-07T10:25:00Z",
        summary="Restored nginx",
    )
    payload = {k: v for k, v in req.model_dump().items() if v is not None}
    assert "root_cause" not in payload
    assert payload["summary"] == "Restored nginx"
    assert payload["ticket_id"] == 7001