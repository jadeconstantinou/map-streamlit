import logging
import warnings
from pydantic import PydanticDeprecatedSince20
from pathlib import Path
from typing import Any, List, Tuple, Union
from urllib import request
from odc.stac import stac_load
import rasterio as rio
import pandas as pd
import numpy as np
import rioxarray
from pathlib import Path
from geogif import dgif


import geojson
from pystac.item import Item
from pystac_client import Client
import stackstac

from mapa_streamlit import conf
from mapa_streamlit.caching import get_hash_of_geojson
from mapa_streamlit.cleaning import _delete_files_in_dir, run_cleanup_job
from mapa_streamlit.exceptions import NoSTACItemFound
from mapa_streamlit.utils import GIFTMPDIR, TMPDIR, ProgressBar
import pystac_client

from mapa_streamlit.zip import create_gif_zip_archive, create_zip_archive
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

    array = np.stack([xarray[b].values for b in bands], axis=-1)
    key = {i: bands[i] for i in range(len(bands))}

    for i, arr in enumerate(array):
        filename=Path(collection+"_"
            + pd.to_datetime(xarray[bands[0]].time.values[i])
            .to_pydatetime()
            .strftime("%Y-%m-%d_%H-%M-%S")
            + ".tif")
        with rio.open(
        filepath/filename,
        "w",
        **meta,
        ) as dst:
            for j in range(meta["count"]):
                dst.write(arr[:, :, j], j + 1)
                dst.set_band_description(j+1,key[j])   

                paths.append(filepath/filename)
    return paths,array



def fetch_stac_items_for_bbox(
    user_defined_bands:list, user_defined_collection:str, geojson: dict, allow_caching: bool, cache_dir: Path, date_range:str,progress_bar: Union[None, ProgressBar] = None, 
) -> Tuple:
    
    items = search_stac_for_items(user_defined_collection, geojson,date_range)

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
        
        paths,array=save_images_from_xarr(xx,cache_dir,user_defined_bands,user_defined_collection)
        
        if progress_bar:
            progress_bar.step()
        print("######",paths)
        return paths, array, xx
    else:
        raise NoSTACItemFound("Could not find the desired STAC item for the given bounding box.")

def search_stac_for_items(user_defined_collection, geojson,date_range):
    bbox = _turn_geojson_into_bbox(geojson)
    
    catalog = pystac_client.Client.open(
        conf.PLANETARY_COMPUTER_API_URL,
        modifier=planetary_computer.sign_inplace,
    )

    search = catalog.search(
        collections=[user_defined_collection],  # landsat-c2-l2, sentinel-2-l2a
        bbox=bbox,
        datetime=date_range,
        query={
            "eo:cloud_cover": {"lt": 20},
        },
    )
    items = search.get_all_items()
    return items


def get_band_metadata(collection:str):
    catalog = pystac_client.Client.open(
    conf.PLANETARY_COMPUTER_API_URL,
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

def filter(bands,resolution,items,bbox,perc_thresh):#remove perc_thresh
    stack = stackstac.stack(items, bounds_latlon=bbox, resolution=resolution,epsg=None)

    data = stack.sel(band=bands)

    pixel_thresh = perc_thresh/100 * data['x'].shape[0] *data['y'].shape[0] * len(bands)
    nodata_filtered = data.dropna('time', thresh=int(pixel_thresh))

    ts = nodata_filtered.persist()
    return ts

def save_gif(gif):
    filename=Path("my_gif.gif")
    with open(filename, "wb") as f:
        f.write(gif)
    path=filename
    return path

def create_and_save_gif(geojson,geo_hash,user_defined_collection,user_defined_bands,output_file,date_range,compress=True)->Path:
    gif_path_list=[]
    items=search_stac_for_items(user_defined_collection, geojson,date_range)
    print("#########################items!:",items)
    print(len(items))
    bbox = _turn_geojson_into_bbox(geojson)
    print(bbox)

    ts=filter(user_defined_bands,10,items,bbox,perc_thresh=1) #check with band that is 30m if this 10m would work
    print(ts)
    gif=dgif(ts,fps=0.5, date_bg=(34, 229, 235),date_color=(0, 0, 0),date_position="lr", date_format="%Y-%m-%d_%H:%M:%S", bytes=True).compute()#cmap="Greys",
    path=save_gif(gif)
    gif_path_list.append(path)
    print(path)
    print(output_file)
    # mapa_cache_dir = GIFTMPDIR()
    # run_cleanup_job(path=mapa_cache_dir, disk_cleaning_threshold=60)
    # path = mapa_cache_dir / geo_hash
    # _delete_files_in_dir(GIFTMPDIR(), ".zip")
    #output_file=GIFTMPDIR()/"gif.zip"
    if compress:
        return create_gif_zip_archive(files=gif_path_list, output_file=f"{output_file}.zip")
    else:
        return gif_path_list[0] if len(gif_path_list) == 1 else gif_path_list

    #return path,gif




    
