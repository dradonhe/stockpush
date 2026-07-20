"""
APScheduler-based realtime scheduler for F5.1 realtime trading signals.

Supports time-based scheduling with trading hours restrictions.
"""

import logging
import threading
from datetime import datetime, time
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


class RealtimeScheduler:
    """APScheduler BackgroundScheduler wrapper for realtime trading signal jobs.

    Supports dual trading windows (morning + afternoon). Thread-safe.
    """

    def __init__(
        self,
        morning_start: str = "09:25",
        morning_end: str = "11:35",
        afternoon_start: str = "13:00:05",
        afternoon_end: str = "15:05",
        interval_seconds: int = 60,
    ) -> None:
        self.morning_start = morning_start
        self.morning_end = morning_end
        self.afternoon_start = afternoon_start
        self.afternoon_end = afternoon_end
        self.interval_seconds = interval_seconds
        self._lock = threading.Lock()
        self._scheduler = BackgroundScheduler()

    def _is_within_trading_hours(self) -> bool:
        now = datetime.now()
        hms = now.strftime("%H:%M:%S")
        if self.morning_start <= hms <= self.morning_end:
            return True
        if self.afternoon_start <= hms <= self.afternoon_end:
            return True
        return False

    def _is_past_end(self) -> bool:
        """Check if current time is past the afternoon_end."""
        now = datetime.now().time()
        parts = self.afternoon_end.split(":")
        h, m = int(parts[0]), int(parts[1])
        s = int(parts[2]) if len(parts) > 2 else 0
        end = time(h, m, s)
        return now > end

    def start(self, job_func, job_id: str = "f51_realtime_job") -> None:
        """
        Start the scheduler with a job function.

        Args:
            job_func: Callable to run on schedule.
            job_id: Unique identifier for the job.
        """
        with self._lock:
            if self._scheduler.running:
                logger.warning("Scheduler already running, skipping start.")
                return

            def wrapped_job():
                try:
                    if self._is_within_trading_hours():
                        job_func()
                    elif self._is_past_end():
                        logger.info("Job %s auto-stopped: past afternoon_end %s", job_id, self.afternoon_end)
                        self.stop(job_id)
                    else:
                        logger.debug(
                            "Job %s skipped: outside trading hours (morning %s-%s, afternoon %s-%s)",
                            job_id,
                            self.morning_start,
                            self.morning_end,
                            self.afternoon_start,
                            self.afternoon_end,
                        )
                except Exception:
                    logger.exception("Job %s failed", job_id)

            trigger = IntervalTrigger(seconds=self.interval_seconds)

            self._scheduler.add_job(
                wrapped_job,
                trigger=trigger,
                id=job_id,
                replace_existing=True,
                misfire_grace_time=self.interval_seconds,
                max_instances=2,
                coalesce=True,
            )
            self._scheduler.start()
            logger.info(
                f"Scheduler started: job_id=%s, interval=%ds, trading_hours=%s-%s, %s-%s",
                job_id,
                self.interval_seconds,
                self.morning_start,
                self.morning_end,
                self.afternoon_start,
                self.afternoon_end,
            )

    def stop(self, job_id: str = "f51_realtime_job") -> None:
        """
        Stop the scheduler and remove the job.

        Args:
            job_id: Identifier of the job to remove.
        """
        with self._lock:
            if not self._scheduler.running:
                logger.warning("Scheduler not running, skipping stop.")
                return

            self._scheduler.remove_job(job_id)
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped: job_id=%s", job_id)

    def is_running(self) -> bool:
        """
        Check if the scheduler is currently running.

        Returns:
            True if the scheduler is running.
        """
        with self._lock:
            return self._scheduler.running

    def get_next_run_time(self, job_id: str = "f51_realtime_job") -> Optional[datetime]:
        """
        Get the next scheduled run time for a job.

        Args:
            job_id: Identifier of the job.

        Returns:
            datetime of next run, or None if job not found.
        """
        with self._lock:
            job = self._scheduler.get_job(job_id)
            if job is None:
                return None
            return job.next_run_time


# ---------------------------------------------------------------------------
# Global convenience functions
# ---------------------------------------------------------------------------

_global_scheduler: Optional[RealtimeScheduler] = None


def get_scheduler() -> Optional[RealtimeScheduler]:
    """
    Get the global scheduler instance.

    Returns:
        The global RealtimeScheduler instance, or None if not initialized.
    """
    return _global_scheduler


def init_scheduler(
    start_time: str = "09:05",
    end_time: str = "15:05",
    interval_seconds: int = 60,
) -> RealtimeScheduler:
    """
    Initialize the global scheduler instance.

    Args:
        start_time: Trading hours start in HH:MM format.
        end_time: Trading hours end in HH:MM format.
        interval_seconds: Job interval in seconds.

    Returns:
        The initialized RealtimeScheduler instance.
    """
    global _global_scheduler
    with _scheduler_lock:
        if _global_scheduler is None:
            _global_scheduler = RealtimeScheduler(
                morning_start=start_time,
                morning_end=end_time,
                interval_seconds=interval_seconds,
            )
    return _global_scheduler