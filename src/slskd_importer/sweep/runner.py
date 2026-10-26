"""LibrarySweep orchestrator: start, schedule, status. Composes check + decide."""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import logging
import os
import time
from collections.abc import Callable

from slskd_importer.catalog.musicbrainz import MusicBrainzClient
from slskd_importer.catalog.spotify import SpotifyResolver
from slskd_importer.library.files import FileProcessor
from slskd_importer.records.database import Database
from slskd_importer.records.sweep_models import RUN_DONE, RUN_INTERRUPTED, SweepRun, SweepSong
from slskd_importer.records.sweep_repo import SweepRepository
from slskd_importer.settings.config import Config
from slskd_importer.soulseek.client import SlskdClient
from slskd_importer.soulseek.scoring import ResultScorer
from slskd_importer.sweep import audit as rules
from slskd_importer.sweep import fingerprint as fp
from slskd_importer.sweep import schedule as sched
from slskd_importer.sweep import sound as sound_mod
from slskd_importer.sweep.audit import Audit
from slskd_importer.sweep.check import CheckMixin
from slskd_importer.sweep.decide import DecideMixin
from slskd_importer.sweep.outcomes import (
    HEARTBEAT_SECS,
    LOOP_TICK_SECS,
    OUTCOME_ERROR,
    OUTCOME_LABELS,
    REPLACED_DIR,
    REVIEW_DIR,
    STALE_RUN_SECS,
    ReportHook,
    SongResult,
    SweepReport,
)
from slskd_importer.sweep.place import is_due, library_files

logger = logging.getLogger(__name__)


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


class LibrarySweep(CheckMixin, DecideMixin):
    """One library's sweep. Front ends set *on_report*."""

    def __init__(
        self,
        config: Config,
        db: Database,
        spotify: SpotifyResolver,
        musicbrainz: MusicBrainzClient,
        slskd: SlskdClient,
        scorer: ResultScorer,
        processor: FileProcessor,
        *,
        owner: str = "bot",
    ):
        self.config = config
        self.db = db
        self.spotify = spotify
        self.musicbrainz = musicbrainz
        self.slskd = slskd
        self.scorer = scorer
        self.processor = processor
        self.owner = owner
        self.repo = SweepRepository(db)
        self.on_report: ReportHook | None = None
        self.audit = rules.audit
        self.fingerprint = fp.fingerprint
        self.sound = sound_mod.sound
        self.sleep = asyncio.sleep
        self._task: asyncio.Task | None = None
        self._run: SweepRun | None = None
        self._decide_lock = asyncio.Lock()
        self._slot_reported: float | None = None
        self._download_lock = asyncio.Lock()

    @property
    def users(self) -> set[int]:
        """Who gets reports and `/sweep`: library ACL if set, else all allowed users."""
        library = self.config.telegram_library_users
        if library:
            return set(library)
        return set(self.config.telegram_allowed_users or ())

    @property
    def enabled(self) -> bool:
        return bool(self.users)

    @property
    def root(self) -> str:
        return self.config.output_dir

    @property
    def replaced_dir(self) -> str:
        return os.path.join(self.root, REPLACED_DIR)

    @property
    def review_dir(self) -> str:
        return os.path.join(self.root, REVIEW_DIR)

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def current_run(self) -> SweepRun | None:
        return self._run if self.running else None

    # ------------------------------------------------------------- start/stop

    def _live_run_elsewhere(self, now: float) -> SweepRun | None:
        """A sweep another process is running right now (its row written in the last STALE_RUN_SECS)."""
        for run in self.repo.running_runs():
            if self._run is not None and run.id == self._run.id:
                continue
            if now - run.updated_at < STALE_RUN_SECS:
                return run
        return None

    def start(self, trigger: str = "manual", force: bool = False) -> tuple[SweepRun | None, str]:
        """Start a sweep in the background; (the run, "") or (None, why not). Needs a running event loop."""
        if not self.enabled:
            return None, "no Telegram users configured to receive the sweep"
        missing = rules.missing_tools()
        if missing:
            return None, f"the sweep cannot measure files without {' and '.join(missing)}"
        if self.running:
            return None, "a sweep is already running"
        other = self._live_run_elsewhere(time.time())
        if other is not None:
            return None, f"another process is running sweep {other.id}"
        for stale in self.repo.running_runs():
            stale.status = RUN_INTERRUPTED
            self.repo.save_run(stale)
        run = self.repo.add_run(SweepRun(trigger=trigger, force=force, owner=self.owner))
        self._launch(run)
        return run, ""

    def _launch(self, run: SweepRun) -> None:
        self._run = run
        self._task = asyncio.get_running_loop().create_task(self._sweep(run), name=f"library-sweep-{run.id}")

    def resume(self) -> SweepRun | None:
        """At startup: continue this owner's sweep that a stop interrupted (or any stale one). Returns it."""
        if not self.enabled or self.running:
            return None
        missing = rules.missing_tools()
        if missing:
            logger.error("Library sweep not continued: %s missing", " and ".join(missing))
            return None
        now = time.time()
        for run in self.repo.running_runs():
            if run.owner == self.owner or now - run.updated_at >= STALE_RUN_SECS:
                logger.info("Library sweep %d continues where it stopped", run.id)
                self._launch(run)
                return run
        return None

    async def stop(self) -> None:
        """Cancel the running sweep (shutdown): its row stays running, the next start continues it."""
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    # ------------------------------------------------------------------ a run

    async def _sweep(self, run: SweepRun) -> None:
        keepalive = asyncio.get_running_loop().create_task(self._keepalive(run))
        try:
            if not os.path.isdir(self.root):
                logger.error("Library sweep %d: %s is not a folder (unmounted?); nothing checked", run.id, self.root)
                run.counts[OUTCOME_ERROR] = run.counts.get(OUTCOME_ERROR, 0) + 1
                await self._finish(run)
                return
            names = await asyncio.to_thread(library_files, self.root)
            if names:
                await asyncio.to_thread(self.repo.forget_missing, set(names))
            order = self._order(names)
            run.total, run.done = len(order), 0
            self.repo.save_run(run)
            logger.info(
                "Library sweep %d (%s%s): %d files", run.id, run.trigger, ", forced" if run.force else "", run.total
            )
            pause = False
            for name in order:
                result = await self._check_logged(name, run, pause)
                run.done += 1
                if result is None:
                    continue
                pause = result.searched
                run.counts[result.outcome] = run.counts.get(result.outcome, 0) + 1
                run.current = ""
                self.repo.save_run(run)
            await asyncio.to_thread(self.purge_parked)
            await self._finish(run)
        except asyncio.CancelledError:
            logger.info(
                "Library sweep %d stopped at %d of %d; the next start continues it", run.id, run.done, run.total
            )
            raise
        except Exception:
            logger.exception("Library sweep %d failed", run.id)
            run.status = RUN_INTERRUPTED
            self.repo.save_run(run)
        finally:
            keepalive.cancel()

    def _order(self, names: list[str]) -> list[str]:
        """Worst tier first (files never audited first of all), then by name."""
        tiers = {s.file: s.tier for s in self.repo.songs()}

        def key(name: str):
            tier = tiers.get(name)
            return (rules.TIERS.index(tier) + 1 if tier in rules.TIERS else 0, name)

        return sorted(names, key=key)

    async def _finish(self, run: SweepRun) -> None:
        run.status, run.finished_at, run.current = RUN_DONE, time.time(), ""
        self.repo.save_run(run)
        summary = ", ".join(f"{OUTCOME_LABELS.get(k, k).lower()} {v}" for k, v in sorted(run.counts.items()))
        logger.info("Library sweep %d done: %s", run.id, summary or "nothing was due")
        await self._notify(self.report(run))

    def report(self, run: SweepRun, in_progress: bool = False) -> SweepReport:
        return SweepReport(
            run=run,
            reviews=[] if in_progress else self.repo.pending_reviews(),
            in_progress=in_progress,
        )

    async def _notify(self, report: SweepReport) -> None:
        if self.on_report is None:
            return
        try:
            await self.on_report(report)
        except Exception:
            logger.exception("Sending the library sweep report failed")

    async def _keepalive(self, run: SweepRun) -> None:
        """Write the run row every HEARTBEAT_SECS for the sweep's whole life, so no other process takes it
        for dead while a song downloads, decodes or is fingerprinted."""
        while True:
            await asyncio.sleep(HEARTBEAT_SECS)
            try:
                self.repo.save_run(run)
            except Exception:
                logger.warning("Sweep %s: could not write its row", run.id, exc_info=True)

    async def _check_logged(self, name: str, run: SweepRun, pause: bool) -> SongResult | None:
        """check_song with its log line and its row written; None when the song was not due."""
        path = os.path.join(self.root, name)
        try:
            due = await self._audited_and_due(name, run)
        except Exception:
            logger.exception("Sweep: could not audit %s", name)
            due = None
        if due is None:
            return None
        song, original = due
        if pause:
            await self.sleep(self.config.library_sweep_pause_secs)
        run.current = name
        self.repo.save_run(run)
        try:
            result = await self.check_song(path, song, original, run)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Sweep: checking %s failed", name, exc_info=True)
            result = SongResult(OUTCOME_ERROR, f"{type(exc).__name__}: {exc}"[:300], searched=True)
        self.repo.mark_checked(name, time.time(), result.outcome, result.detail)
        logger.info(
            "Sweep %d/%d %s (%s): %s%s",
            run.done + 1,
            run.total,
            name,
            original.tier,
            OUTCOME_LABELS.get(result.outcome, result.outcome),
            f": {result.detail}" if result.detail else "",
        )
        return result

    async def _audited_and_due(self, name: str, run: SweepRun) -> tuple[SweepSong, Audit] | None:
        """The song's row (audited again when the file changed) and audit, when it is due in *run*."""
        path = os.path.join(self.root, name)
        try:
            st = os.stat(path)
        except OSError:
            return None
        song = self.repo.get_song(name)
        if song is None or song.size != st.st_size or song.mtime != st.st_mtime:
            measured = await asyncio.to_thread(self.audit, path)
            song = SweepSong(
                file=name,
                stem=os.path.splitext(name)[0],
                size=st.st_size,
                mtime=st.st_mtime,
                tier=measured.tier,
                audit=measured.to_dict(),
                declined_at=song.declined_at if song is not None else None,
            )
            self.repo.save_audit(song)
        if not is_due(song, run, time.time()):
            return None
        return song, Audit.from_dict(song.audit)

    async def schedule_loop(self, now: Callable[[], datetime.datetime] | None = None) -> None:
        """Continue an interrupted sweep, then start one at every LIBRARY_SWEEP_SCHEDULE slot; purge hourly.

        A slot missed while the bot was down is caught up at start. When a
        slot comes while a sweep still runs, the owner gets a progress report
        instead. The first slot after the feature is turned on starts the first
        sweep (or /sweep, at once).
        """
        now = now or (lambda: datetime.datetime.now().astimezone())
        schedule = sched.parse_schedule(self.config.library_sweep_schedule)
        loop_started = now().timestamp()
        self.resume()
        while True:
            try:
                await asyncio.to_thread(self.purge_parked)
                if schedule is not None:
                    await self._maybe_start(schedule, now(), loop_started)
            except Exception:
                logger.exception("Library sweep schedule tick failed")
            current = now()
            wait = float(LOOP_TICK_SECS)
            if schedule is not None:
                wait = min(wait, max(1.0, (sched.next_run(schedule, current) - current).total_seconds()))
            await self.sleep(wait)

    async def _maybe_start(self, schedule: sched.Schedule, current: datetime.datetime, loop_started: float) -> None:
        slot = sched.previous_run(schedule, current).timestamp()
        last = self.repo.last_started_at()
        due = (last is not None and last < slot) or (last is None and slot >= loop_started)
        if not due:
            return
        if self.running:
            if self._slot_reported != slot and self._run is not None:
                self._slot_reported = slot
                await self._notify(self.report(self._run, in_progress=True))
            return
        run, why = self.start("schedule")
        if run is None:
            logger.info("Scheduled library sweep not started: %s", why)

    def status(self) -> dict:
        """The sweep's state for /sweep status and the MCP: the current or last run, tiers, pairs waiting."""
        run = self.current_run or self.repo.latest_run()
        try:
            schedule = sched.parse_schedule(self.config.library_sweep_schedule)
        except ValueError:
            schedule = None
        next_at = sched.next_run(schedule, datetime.datetime.now().astimezone()) if schedule else None
        return {
            "enabled": self.enabled,
            "running": self.running,
            "schedule": str(schedule) if schedule else "off",
            "next_scheduled": next_at.isoformat(timespec="minutes") if next_at else None,
            "run": None
            if run is None
            else {
                "id": run.id,
                "trigger": run.trigger,
                "forced": run.force,
                "status": run.status,
                "position": run.done,
                "files": run.total,
                "current": run.current or None,
                "counts": dict(run.counts),
                "started_at": _iso(run.started_at),
                "finished_at": _iso(run.finished_at),
            },
            "tiers": self.repo.tier_counts(),
            "reviews_waiting": len(self.repo.pending_reviews()),
            "pause_secs": self.config.library_sweep_pause_secs,
            "keep_days": self.config.library_sweep_keep_days,
            "fingerprint": fp.fpcalc_available(),
            "missing_tools": rules.missing_tools(),
        }
