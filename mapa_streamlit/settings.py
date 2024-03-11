from importlib.metadata import version
from typing import Tuple

from mapa_streamlit import __version__

MAP_CENTER = [25.0, 55.0]
MAP_ZOOM = 3

BTN_LABEL_CREATE_TIF = "Click to request data"
BTN_LABEL_DOWNLOAD_TIFS = "Click to download .tifs"
BTN_LABEL_DOWNLOAD_GIFS = "Click to download gif"

MAX_ALLOWED_AREA_SIZE = 25.0

DISK_CLEANING_THRESHOLD = 60.0



DEFAULT_Z_OFFSET = 2
DEFAULT_Z_SCALE = 2.0
DEFAULT_MODEL_SIZE = 100
DEFAULT_TILING_FORMAT = "1x1"


class ZOffsetSlider:
    label: str = "Z-offset:"
    min_value: int = 0
    max_value: int = 20
    value: int = DEFAULT_Z_OFFSET
    help: str = "Offset (in millimeter) to be used to extrude a base in which the 3D elevation shape will be put on."


class ZScaleSlider:
    label: str = "Z-scale:"
    min_value: float = 0.0
    max_value: float = 5.0
    value: float = DEFAULT_Z_SCALE
    step: float = 0.1
    help: str = "Factor to be multiplied to the z-axis in order to scale the elevation up (or down)."


class ModelSizeSlider:
    label: str = "Model size:"
    min_value: int = 10
    max_value: int = 200
    value: int = DEFAULT_MODEL_SIZE
    step: int = 1
    help: str = (
        "Desired output size of the 3d model in millimeter. In case of a rectangular shaped model, this value will be "
        "used for the north-south dimension of the model."
    )


class SquaredCheckbox:
    label: str = "Squared model output?"
    help: str = (
        "Enable this to force the computed output STL file to be squared in x and y dimensions. Note, that the "
        "rectangle you selected will be cut to achieve this. This option might be helpful, as drawing a perfect "
        "square by hand is impossible and because the visual map is projected."
    )


class TilingSelect:
    label: str = "Please ignore this!"#Split output STL file in multiple tiles?"
    options: Tuple[str] = (DEFAULT_TILING_FORMAT, "1x2", "2x1", "2x2", "2x3", "3x2", "3x3")
    help: str = (
        "Please ignore this I need to remove it"
    )
