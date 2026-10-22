# -*- coding: utf-8 -*-
import subprocess
import time
import sys
import os

if sys.stdout is not None:
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
if sys.stderr is not None:
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
POLLER_SCRIPT = os.path.join(SCRIPT_DIR, "run_poller.py")
PYTHON_EXE = sys.executable.replace('pythonw.exe', 'python.exe')
LOG_FILE = os.path.join(SCRIPT_DIR, "watchdog.log")

def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    try:
        if sys.stdout is not None:
            sys.stdout.write(line)
            sys.stdout.flush()
    except Exception:
        pass
    try:
        with open(LOG_FILE, "a", encoding="utf-8", errors="replace") as f:
            f.write(line)
    except Exception:
        pass

log("==================================================")
log("[WATCHDOG] СЛУЖБА AI-РЕКРУТЕРА АВИТО АКТИВИРОВАНА")
log(f"Контролируемый скрипт: {POLLER_SCRIPT}")
log(f"Интерпретатор: {PYTHON_EXE}")
log("==================================================")

while True:
    try:
        log("Запуск рабочего процесса run_poller.py...")
        p = subprocess.Popen(
            [PYTHON_EXE, "-u", POLLER_SCRIPT],
            cwd=SCRIPT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        for line in p.stdout:
            log(line.rstrip())
        exit_code = p.wait()
        log(f"Процесс завершился с кодом {exit_code}. Перезапуск через 3 секунды...")
    except Exception as e:
        log(f"Ошибка в watchdog: {e}. Перезапуск через 5 секунд...")
        time.sleep(5)
    time.sleep(3)
