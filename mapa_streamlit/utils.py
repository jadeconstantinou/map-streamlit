import logging
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)


def TMPDIR() -> Path:
    tmpdir = Path(tempfile.gettempdir()) / "mapa"
    if not tmpdir.is_dir():
        tmpdir.mkdir()
    return tmpdir

def GIFTMPDIR() -> Path:
    tmpdir = Path(tempfile.gettempdir()) / "mapa" /"gif"
    if not tmpdir.is_dir():
        tmpdir.mkdir()
    return tmpdir

class ProgressBar:
    def __init__(self, progress_bar: object, steps: int = 0) -> None:
        self.progress_bar = progress_bar  # streamlit st.progress_bar object
        self.steps: int = steps
        self.counter: int = 0

    def step(self) -> None:
        progress = 100 // (self.steps - 1) * (self.counter + 1)
        progress = progress if progress <= 100 else 100
        self.progress_bar.progress(progress)
        self.counter += 1
