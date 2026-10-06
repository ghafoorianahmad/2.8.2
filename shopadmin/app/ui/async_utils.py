"""Background work so the window never freezes while shopapi is answering.

All HTTP calls run on a ``QThreadPool`` worker and report back through Qt
signals, which are delivered on the GUI thread.

Robustness note: an exception raised inside a *queued* Qt slot does not
propagate as a Python error — Qt prints it and DISCONNECTS the slot, so a single
bug in one callback would silently break every later update. Every callback is
therefore invoked through :func:`_guard`, which logs and reports instead.
"""
from __future__ import annotations

import inspect
import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from ..api_client import ApiError
from ..logging_setup import get_logger

log = get_logger("worker")

MSG_UNEXPECTED = "خطای پیش‌بینی‌نشده در انجام عملیات رخ داد. جزئیات در فایل لاگ ثبت شد."

#: Strong references to in-flight workers.
#:
#: PySide6 does NOT keep a Python reference to a QRunnable handed to
#: QThreadPool.start(). Without this registry the worker — and with it its
#: signal object and every connected callback — is garbage-collected before the
#: background function finishes, so the UI would silently never update.
_ACTIVE_WORKERS: dict[int, "_Worker"] = {}


def _guard(callback: Callable[..., Any] | None, label: str) -> Callable[..., None] | None:
    """Wrap a callback so a failure inside it cannot break the signal chain."""
    if callback is None:
        return None

    def wrapper(*args: Any, **kwargs: Any) -> None:
        try:
            callback(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - never let a UI callback kill the chain
            # Full traceback on purpose: the type alone is not enough to diagnose
            # a failure that only shows up under a particular test ordering.
            log.exception(
                "%s callback failed: %s\n%s",
                label,
                type(exc).__name__,
                traceback.format_exc(),
            )

    return wrapper


class WorkerSignals(QObject):
    finished = Signal(object)          # result
    failed = Signal(str, str)          # Persian message, kind
    done = Signal()                    # always emitted last
    progress = Signal(str)             # optional progress text


class _Worker(QRunnable):
    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    def _accepts_progress(self) -> bool:
        """True when ``fn`` declares an ``on_progress`` parameter.

        Introspection is used rather than catching TypeError, because catching it
        would silently swallow a genuine TypeError raised *inside* the function.
        """
        try:
            signature = inspect.signature(self.fn)
        except (TypeError, ValueError):
            return False
        if "on_progress" in signature.parameters:
            return True
        return any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )

    def run(self) -> None:
        try:
            if self._accepts_progress():
                try:
                    result = self.fn(
                        *self.args, on_progress=self.signals.progress.emit, **self.kwargs
                    )
                except TypeError:
                    # The declared parameter was not actually accepted (e.g. a
                    # bound C++ slot): retry without it.
                    result = self.fn(*self.args, **self.kwargs)
            else:
                result = self.fn(*self.args, **self.kwargs)
        except ApiError as exc:
            self.signals.failed.emit(exc.message, exc.kind)
        except Exception as exc:  # noqa: BLE001 - never let a thread die silently
            log.exception("background task failed: %s", type(exc).__name__)
            self.signals.failed.emit(MSG_UNEXPECTED, "unexpected")
        else:
            self.signals.finished.emit(result)
        finally:
            self.signals.done.emit()


def run_async(
    fn: Callable[..., Any],
    *args: Any,
    on_success: Callable[[Any], None] | None = None,
    on_error: Callable[[str, str], None] | None = None,
    on_done: Callable[[], None] | None = None,
    on_progress: Callable[[str], None] | None = None,
    **kwargs: Any,
) -> _Worker:
    """Run ``fn`` off the GUI thread and deliver the outcome via callbacks.

    ``on_progress`` is only used when ``fn`` declares an ``on_progress``
    parameter (or accepts ``**kwargs``).

    The guarded wrappers are attached to the worker object on purpose: PySide6
    keeps only a WEAK reference to a plain-function slot, so a wrapper that is
    only a local variable would be garbage-collected before the signal fires and
    the callback would silently never run.
    """
    worker = _Worker(fn, *args, **kwargs)
    #: keep-alive for the wrappers below (see the registry note above)
    worker.callbacks = [
        _guard(on_success, "on_success"),
        _guard(on_error, "on_error"),
        _guard(on_done, "on_done"),
        _guard(on_progress, "on_progress"),
    ]
    guarded_success, guarded_error, guarded_done, guarded_progress = worker.callbacks
    if guarded_success is not None:
        worker.signals.finished.connect(guarded_success)
    if guarded_error is not None:
        worker.signals.failed.connect(guarded_error)
    if guarded_done is not None:
        worker.signals.done.connect(guarded_done)
    if guarded_progress is not None:
        worker.signals.progress.connect(guarded_progress)

    # Hold the worker and release it once it reports completion.
    _ACTIVE_WORKERS[id(worker)] = worker
    worker.signals.done.connect(lambda: _ACTIVE_WORKERS.pop(id(worker), None))

    QThreadPool.globalInstance().start(worker)
    return worker


def active_worker_count() -> int:
    """Number of background tasks still held alive (used by tests)."""
    return len(_ACTIVE_WORKERS)


class AutoRefresh(QObject):
    """QTimer wrapper used by the pages that poll shopapi."""

    triggered = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.triggered.emit)
        self._seconds = 0

    @property
    def seconds(self) -> int:
        return self._seconds

    @property
    def is_running(self) -> bool:
        return self._timer.isActive()

    def configure(self, seconds: int) -> None:
        self._seconds = max(0, int(seconds))
        if self._seconds <= 0:
            self._timer.stop()
            return
        self._timer.start(self._seconds * 1000)

    def pause(self) -> None:
        self._timer.stop()

    def resume(self) -> None:
        if self._seconds > 0:
            self._timer.start(self._seconds * 1000)


def wait_for_pool(timeout_ms: int = 5000) -> bool:
    """Test helper: block until queued background work has finished."""
    return QThreadPool.globalInstance().waitForDone(timeout_ms)
