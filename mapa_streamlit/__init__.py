from pathlib import Path

import tomli

import logging
import os
from pathlib import Path
from typing import List, Union

import numpy as np
import rasterio as rio

from mapa_streamlit import conf
from mapa_streamlit.caching import get_hash_of_geojson, tiff_for_bbox_is_cached

from mapa_streamlit.stac import fetch_stac_items_for_bbox
from mapa_streamlit.tiling import get_x_y_from_tiles_format, split_array_into_tiles
from mapa_streamlit.utils import TMPDIR, ProgressBar, path_to_clipped_tiff
from mapa_streamlit.verification import verify_input_and_output_are_valid
from mapa_streamlit.zip import create_zip_archive

log = logging.getLogger(__name__)
logging.basicConfig()
log.setLevel(os.getenv("MAPA_LOG_LEVEL", "INFO"))




def convert_bbox_to_tif(
    user_defined_collection:str,
    user_defined_bands:list,
    bbox_geometry: dict,
    output_file: str = "output",
    split_area_in_tiles: str = "1x1",
    compress: bool = True,
    allow_caching: bool = True,
    cache_dir: Union[Path, str] = TMPDIR(),
    progress_bar: Union[None, object] = None,
) -> Union[Path, List[Path]]:
    """
    Takes a GeoJSON containing a bounding box as input, fetches the required STAC GeoTIFFs for the
    given bounding box and creates a STL file with elevation data from the GeoTIFFs.

    Parameters
    ----------
    bbox_geometry : dict
        GeoJSON containing the coordinates of the bounding box, selected on the ipyleaflet widget. Usually the
        value of `drawer.last_draw["geometry"]` is used for this.
    output_file : str, optional
        Name and path to output file. File ending should not be provided. Mapa will add .zip or .stl depending
        on the settings. By default "output"
    max_res : bool, optional
        Whether maximum resolution should be used. Note, that this flag potentially increases compute time
        and memory consumption dramatically. The default behavior (i.e. max_res=False) should return 3d models
        with sufficient resolution, while the output stl file should be < ~300 MB. By default False
    split_area_in_tiles : str, optional
        Split the selected bounding box into tiles with this option. The allowed format of a given string is
        "nxm" e.g. "1x1", "2x3", "4x4" or similar, where "1x1" would not split at all and result in only
        one stl file. If an allowed tile format is specified, `nxm` stl files will be computed. By default "1x1"
    compress : bool, optional
        If enabled, the output stl file(s) will be compressed to a zip file. Compressing is recommended as it
        reduces the data volume of typical stl files by a factor of ~4.
    allow_caching : bool, optional
        Whether caching previous downloaded GeoTIFF files should be enabled/disabled. By default True
    cache_dir: Union[Path, str]
        Path to a directory which should be used as local cache. This is helpful when intermediary tiff files
        should be persisted even after the temp directory gets cleaned-up by e.g. a restart. By default TMPDIR
    progress_bar : Union[None, object], optional
        A streamlit progress bar object can be used to indicate the progress of downloading the STAC items. By
        default None

    Returns
    -------
    Union[Path, List[Path]]
        Path or list of paths to the resulting output file(s) on your local machine.
    """

    # fail early in case of missing requirements
    if bbox_geometry is None:
        raise ValueError("⛔️  ERROR: make sure to draw a rectangle on the map first!")

    # evaluate tile format to fail early in case of invalid input value
    tiles = get_x_y_from_tiles_format(split_area_in_tiles)

    args = locals().copy()
    args.pop("progress_bar", None)
    log.info(f"⏳  converting bounding box to file with arguments: {args}")

    if progress_bar:
        steps = tiles.x * tiles.y * 2 if compress else tiles.x * tiles.y
        progress_bar = ProgressBar(progress_bar=progress_bar, steps=steps)

    list_paths_to_tiffs,xx=fetch_stac_items_for_bbox(user_defined_bands,
    user_defined_collection,
    bbox_geometry,
    allow_caching,
    cache_dir,
    progress_bar)    
    print("######################",list_paths_to_tiffs)


    if progress_bar:
        progress_bar.step()
    if compress:
        return create_zip_archive(files=list_paths_to_tiffs, output_file=f"{output_file}.zip", progress_bar=progress_bar)
    else:
        return list_paths_to_tiffs[0] if len(list_paths_to_tiffs) == 1 else list_paths_to_tiffs
    



def _get_version_from_project_toml():
    with open(Path(__file__).parent.parent / "pyproject.toml", "rb") as f:
        toml_dict = tomli.load(f)

    return toml_dict["tool"]["poetry"]["version"]


__version__ = _get_version_from_project_toml()
