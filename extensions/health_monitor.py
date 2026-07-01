"""
JARVIS Health Monitor — Phase 1
Monitors system status and reports back to Bob.
Standalone extension — no core files touched.
"""

import datetime
import platform
import psutil


def get_health_report() -> dict:
    """
    Returns a snapshot of JARVIS system health.
    CPU, memory, disk, uptime, and timestamp.
    """
    try:
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.datetime.now() - boot_time

        return {
            "status": "online",
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "uptime_hours": round(uptime.total_seconds() / 3600, 2),
            "cpu_percent": cpu,
            "memory_used_percent": mem.percent,
            "memory_used_gb": round(mem.used / 1e9, 2),
            "memory_total_gb": round(mem.total / 1e9, 2),
            "disk_used_percent": disk.percent,
            "disk_free_gb": round(disk.free / 1e9, 2),
            "platform": platform.system(),
            "python_version": platform.python_version(),
        }

    except Exception as e:
        return {
            "status": "error",
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "error": str(e),
        }


def health_summary() -> str:
    """
    Returns a human-readable health summary for JARVIS to report to Bob.
    """
    r = get_health_report()

    if r["status"] == "error":
        return f"⚠️ Health check failed: {r['error']}"

    lines = [
        "🟢 JARVIS Health Report",
        f"⏱️  Uptime: {r['uptime_hours']} hours",
        f"🖥️  CPU: {r['cpu_percent']}%",
        f"🧠 Memory: {r['memory_used_percent']}% ({r['memory_used_gb']} / {r['memory_total_gb']} GB)",
        f"💾 Disk: {r['disk_used_percent']}% used — {r['disk_free_gb']} GB free",
        f"🐍 Python: {r['python_version']} on {r['platform']}",
        f"🕐 Checked: {r['timestamp']}",
    ]

    return "\n".join(lines)


if __name__ == "__main__":
    print(health_summary())
