import io
import logging
import uuid
import zipfile
from pathlib import Path
from typing import List, Union

from mapa_streamlit.utils import ProgressBar

log = logging.getLogger(__name__)


def create_zip_archive(
    files: List[Path], output_file: Union[str, Path], progress_bar: Union[ProgressBar, None] = None
) -> Path:
    log.info(f"📦  compressing files: {[f.name for f in files]}")
    with zipfile.ZipFile(output_file, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for f in files:
            zip_file.write(f, f.name)
            if progress_bar:
                progress_bar.step()
    log.info(f"✅  finished compressing files into: {output_file}")
    return Path(output_file)



def create_gif_zip_archive(
    files: List[Path], output_file: Union[str, Path]
) -> Path:
    log.info(f"📦  compressing files: {[f.name for f in files]}")
    with zipfile.ZipFile(output_file, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for f in files:
            zip_file.write(f, f.name)
    log.info(f"✅  finished compressing files into: {output_file}")
    return Path(output_file)