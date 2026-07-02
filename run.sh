#!/usr/bin/env bash
# socials-agent run script.
#
# Usage:
#   ./run.sh start    — start the daemon in the background, write PID
#   ./run.sh stop     — stop the daemon via PID file
#   ./run.sh status   — is the daemon running?
#   ./run.sh restart  — stop + start
#   ./run.sh tail     — tail the daemon log
#   ./run.sh once     — run a one-shot pipeline tick (no daemon)
#
# PID file: /tmp/socials-agent.pid (override with SOCIALS_AGENT_PID)

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${SOCIALS_AGENT_PID:-/tmp/socials-agent.pid}"
LOG_FILE="${HERE}/logs/daemon.log"

cmd_start() {
  if [[ -f "${PID_FILE}" ]] && kill -0 "$(cat "${PID_FILE}")" 2>/dev/null; then
    echo "already running (pid $(cat "${PID_FILE}"))"
    exit 0
  fi
  cd "${HERE}"
  : > "${LOG_FILE}"
  nohup python3 src/daemon.py >> "${LOG_FILE}" 2>&1 &
  echo $! > "${PID_FILE}"
  sleep 1
  if kill -0 "$(cat "${PID_FILE}")" 2>/dev/null; then
    echo "started (pid $(cat "${PID_FILE}"), log ${LOG_FILE})"
  else
    echo "failed to start — see ${LOG_FILE}"
    rm -f "${PID_FILE}"
    exit 1
  fi
}

cmd_stop() {
  if [[ ! -f "${PID_FILE}" ]]; then
    echo "no pid file at ${PID_FILE} — nothing to stop"
    return 0
  fi
  pid="$(cat "${PID_FILE}")"
  if ! kill -0 "${pid}" 2>/dev/null; then
    echo "pid ${pid} not running — cleaning up"
    rm -f "${PID_FILE}"
    return 0
  fi
  kill "${pid}" 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    kill -0 "${pid}" 2>/dev/null || break
    sleep 0.5
  done
  if kill -0 "${pid}" 2>/dev/null; then
    echo "pid ${pid} did not exit, sending SIGKILL"
    kill -9 "${pid}" 2>/dev/null || true
  fi
  rm -f "${PID_FILE}"
  echo "stopped"
}

cmd_status() {
  if [[ -f "${PID_FILE}" ]] && kill -0 "$(cat "${PID_FILE}")" 2>/dev/null; then
    echo "running (pid $(cat "${PID_FILE}"))"
  else
    echo "not running"
    [[ -f "${PID_FILE}" ]] && rm -f "${PID_FILE}"
    exit 1
  fi
}

cmd_restart() {
  cmd_stop || true
  cmd_start
}

cmd_tail() {
  tail -n 100 -f "${LOG_FILE}"
}

cmd_once() {
  cd "${HERE}"
  python3 src/reply_monitor.py
  python3 src/triage.py
  SOCIALS_FORCE_SUMMARY=1 python3 src/daily_summary.py --force
}

case "${1:-}" in
  start)    cmd_start ;;
  stop)     cmd_stop ;;
  status)   cmd_status ;;
  restart)  cmd_restart ;;
  tail)     cmd_tail ;;
  once)     cmd_once ;;
  *)
    echo "usage: $0 {start|stop|status|restart|tail|once}"
    exit 2
    ;;
esac