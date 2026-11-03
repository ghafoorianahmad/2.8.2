"""v2.18.0: record and play voice messages with what Windows itself has (``winmm``), no extra
library: QtMultimedia is left out of the build on purpose. Recording: 16 kHz mono WAV.

Everything here reports a failure as :class:`VoiceError` with a Persian sentence (no microphone,
a microphone blocked by Windows' privacy settings): a voice message must never stop the program.
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

#: A longer message is cut here: 16 kHz, 16 bit, mono = 32 kB per second (the server takes 10 MB).
MAX_SECONDS = 180
_ALIAS = "shopadmin_voice"


class VoiceError(RuntimeError):
    """A Persian sentence for the person using the program."""


def _mci(command: str) -> str:
    import ctypes

    buffer = ctypes.create_unicode_buffer(256)
    code = ctypes.windll.winmm.mciSendStringW(command, buffer, 255, 0)
    if code:
        raise VoiceError("میکروفون در دسترس نیست. میکروفون را وصل کنید و در تنظیمات حریم خصوصی "
                         "ویندوز اجازهٔ میکروفون را روشن کنید.")
    return buffer.value


def _short(folder: str) -> str:
    """mci refuses a file name of about 128 characters or more: the 8.3 form of the folder."""
    import ctypes

    buffer = ctypes.create_unicode_buffer(300)
    done = ctypes.windll.kernel32.GetShortPathNameW(folder, buffer, 300)
    return buffer.value if done else folder


class Recorder:
    """start() ... stop() -> (wav bytes, seconds)."""

    def __init__(self) -> None:
        self._started: float | None = None

    @property
    def recording(self) -> bool:
        return self._started is not None

    def start(self) -> None:
        if sys.platform != "win32":
            raise VoiceError("ضبط صدا فقط در ویندوز کار می‌کند.")
        self.cancel()
        _mci(f"open new type waveaudio alias {_ALIAS}")
        try:
            _mci(f"set {_ALIAS} bitspersample 16 channels 1 samplespersec 16000 "
                 "bytespersec 32000 alignment 2")
            _mci(f"record {_ALIAS}")
        except VoiceError:
            self.cancel()
            raise
        self._started = time.monotonic()

    def elapsed(self) -> int:
        return int(time.monotonic() - self._started) if self._started is not None else 0

    def stop(self) -> tuple[bytes, int]:
        if self._started is None:
            raise VoiceError("ضبطی در جریان نیست.")
        seconds = max(1, self.elapsed())
        self._started = None
        with tempfile.TemporaryDirectory(prefix="shopvoice") as folder:
            path = Path(_short(folder)) / "voice.wav"
            try:
                _mci(f"stop {_ALIAS}")
                _mci(f'save {_ALIAS} "{path}"')
            finally:
                self.cancel()
            return path.read_bytes(), seconds

    def cancel(self) -> None:
        self._started = None
        if sys.platform == "win32":
            try:
                _mci(f"close {_ALIAS}")
            except VoiceError:
                pass


def play(data: bytes) -> None:
    """Plays a WAV without blocking the window; a new one replaces what is playing."""
    if sys.platform != "win32":
        raise VoiceError("پخش صدا فقط در ویندوز کار می‌کند.")
    import winsound

    # asynchronous playing needs a file that stays: the folder is emptied on the next play
    folder = Path(tempfile.gettempdir()) / "shopadmin_voice"
    folder.mkdir(exist_ok=True)
    path = folder / "play.wav"
    try:
        winsound.PlaySound(None, winsound.SND_PURGE)
        path.write_bytes(data)
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC
                           | winsound.SND_NODEFAULT)
    except (OSError, RuntimeError):
        raise VoiceError("این پیام صوتی پخش نشد.") from None


def stop_playing() -> None:
    if sys.platform == "win32":
        import winsound

        winsound.PlaySound(None, winsound.SND_PURGE)
