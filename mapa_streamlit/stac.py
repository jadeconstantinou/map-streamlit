import logging
import warnings
from pydantic import PydanticDeprecatedSince20
from pathlib import Path
from typing import List, Union
from urllib import request
from odc.stac import stac_load
import rasterio as rio
import pandas as pd
import numpy as np
import rioxarray
from pathlib import Path


import geojson
from pystac.item import Item
from pystac_client import Client

from mapa_streamlit import conf
from mapa_streamlit.exceptions import NoSTACItemFound
from mapa_streamlit.utils import ProgressBar
import pystac_client
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=PydanticDeprecatedSince20)
    import planetary_computer

from mapa_streamlit.io import are_stac_items_planetary_computer

log = logging.getLogger(__name__)

def _bbox(coord_list):
    box = []
    for i in (0, 1):
        res = sorted(coord_list, key=lambda x: x[i])
        box.append((res[0][i], res[-1][i]))
    return [box[0][0], box[1][0], box[0][1], box[1][1]]


def _turn_geojson_into_bbox(geojson_bbox: dict) -> List[float]:
    coordinates = geojson_bbox["coordinates"]
    return _bbox(list(geojson.utils.coords(geojson.Polygon(coordinates))))


def save_images_from_xarr(xarray, filepath, bands:list, collection:str, datatype="float32"):
    count=len(bands)
    paths=[]
    xarray.rio.set_crs(int(xarray.spatial_ref.values))
    tf = xarray.rio.transform()
    crs = xarray.rio.crs
    width, height = len(xarray.x), len(xarray.y)
    meta = {
        "transform": tf,
        "crs": crs,
        "width": width,
        "height": height,
        "count": count,
        "dtype": datatype,
        "nodata": 0, 
    }

    rgb_array = np.stack([xarray[b].values for b in bands], axis=-1)
    key = {i: bands[i] for i in range(len(bands))}

    for i, arr in enumerate(rgb_array):
        print("type arr" , type(arr))
        filename=Path(collection+"_"
            + pd.to_datetime(xarray[bands[0]].time.values[i])
            .to_pydatetime()
            .strftime("%Y-%m-%d_%H-%M-%S")
            + ".tif")
        print("arr",arr)
        with rio.open(
        filepath/filename,
        "w",
        **meta,
        ) as dst:
            for j in range(meta["count"]):
                print(j)
                dst.write(arr[:, :, j], j + 1)
                dst.set_band_description(j+1,key[j])   

                paths.append(filepath/filename)
    return paths



def fetch_stac_items_for_bbox(
    user_defined_bands:list, user_defined_collection:str, geojson: dict, allow_caching: bool, cache_dir: Path, progress_bar: Union[None, ProgressBar] = None
) -> List[Path]:
    
    bbox = _turn_geojson_into_bbox(geojson)
    
    catalog = pystac_client.Client.open(
        conf.PLANETARY_COMPUTER_API_URL,
        modifier=planetary_computer.sign_inplace,
    )

    search = catalog.search(
        collections=[user_defined_collection],  # landsat-c2-l2, sentinel-2-l2a
        bbox=bbox,
        datetime="2023-10-20/2023-10-28",
        query={
            "eo:cloud_cover": {"lt": 20},
        },
    )
    items = search.get_all_items()

    patch_url = None
    if are_stac_items_planetary_computer(items):
        patch_url = planetary_computer.sign

        xx=stac_load(
            items,
            geopolygon=geojson,
            chunks={},  # <-- use Dask
            groupby= "solar_day",
            patch_url=patch_url,
            resampling="bilinear",
            fail_on_error=False,
            no_data=0
        )
    
   
    n = len(items)
    if progress_bar:
        progress_bar.steps += n
    if n > 0:
        log.info(f"⬇️  fetching {n} stac items...")
        
        files=save_images_from_xarr(xx,cache_dir,user_defined_bands,user_defined_collection)
        
        if progress_bar:
            progress_bar.step()
        print("######",files)
        return files
    else:
        raise NoSTACItemFound("Could not find the desired STAC item for the given bounding box.")


def get_band_metadata(collection:str):
    catalog = pystac_client.Client.open(
    "https://planetarycomputer.microsoft.com/api/stac/v1",
    modifier=planetary_computer.sign_inplace,
)
    if collection == "landsat-c2-l2":
        landsat = catalog.get_collection("landsat-c2-l2")
        landsat_df1=pd.DataFrame(landsat.summaries.get_list("eo:bands"))
        landsat_df2=pd.DataFrame.from_dict(landsat.extra_fields["item_assets"], orient="index")[["title", "description", "gsd"]]
        landsat_df2.columns.name = 'common_name'
        landsat_df2=landsat_df2.drop(columns=["description","title"])
        df = pd.merge(landsat_df1, landsat_df2, left_on='common_name', right_on='common_name', right_index=True, how='inner')
    
    else:
        sentinel= catalog.get_collection("sentinel-2-l2a")
        df=pd.DataFrame(sentinel.summaries.get_list("eo:bands"))
    
    return df