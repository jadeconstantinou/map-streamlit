import logging
import warnings
from pydantic import PydanticDeprecatedSince20
from pathlib import Path
from typing import List, Tuple, Union
from odc.stac import stac_load
import rasterio as rio
import pandas as pd
import numpy as np
import rioxarray
from pathlib import Path
from geogif import dgif
import geojson
import stackstac
import requests

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

def get_mtl_metadata(items,filepath):
    paths=[]
    for count,item in enumerate(items):
        assets=items[count].assets.items()
        dict_assets=dict(assets)
        xml=dict_assets.get('mtl.xml')

        mtl_xml_url = xml.href
        response = requests.get(mtl_xml_url)

        if response.status_code == 200:
            filename=f'mtl_{item.id}.xml'
            print("##################################################### ", filename)
            with open(filepath/filename, 'wb') as f:
                f.write(response.content)
                paths.append(filepath/filename)
            print("----------------------------------------------------- ",paths)
        else:
            print("Failed to download:", response.status_code)
    return paths
def fetch_stac_items_for_bbox(
    user_defined_bands:list, user_defined_collection:str, geojson: dict, allow_caching: bool, cache_dir: Path, date_range:str, cloud_cover_percentage_value:int, progress_bar: Union[None, ProgressBar] = None, 
) -> Tuple:
    
    items = search_stac_for_items(user_defined_collection, geojson,date_range,cloud_cover_percentage_value)

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
        
        tif_paths,array=save_images_from_xarr(xx,cache_dir,user_defined_bands,user_defined_collection)

        if user_defined_collection=='landsat-c2-l2':
            mtl_paths = get_mtl_metadata(items,cache_dir)
            paths_to_data=tif_paths+mtl_paths

        else: 
            paths_to_data= tif_paths

        
        if progress_bar:
            progress_bar.step()
        print("######",paths_to_data)
        return paths_to_data, array, xx
    else:
        raise NoSTACItemFound("Could not find the desired STAC item for the given bounding box and date range.")

def search_stac_for_items(user_defined_collection, geojson,date_range,cloud_cover_percentage_value):
    bbox = _turn_geojson_into_bbox(geojson)
    
    catalog = pystac_client.Client.open(
        conf.PLANETARY_COMPUTER_API_URL,
        modifier=planetary_computer.sign_inplace,
    )

    search = catalog.search(
        collections=[user_defined_collection],
        bbox=bbox,
        datetime=date_range,
        query={
            "eo:cloud_cover": {"lt": cloud_cover_percentage_value},
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

def create_and_save_gif(geojson,geo_hash,user_defined_collection,user_defined_bands,output_file,date_range,cloud_cover_percentage_value,compress=True)->Path:
    gif_path_list=[]
    items=search_stac_for_items(user_defined_collection, geojson,date_range,cloud_cover_percentage_value)
    if not items:
        print("No items found to create a GIF.")
        return None
    
    bbox = _turn_geojson_into_bbox(geojson)
    
    ts=filter(user_defined_bands,10,items,bbox,perc_thresh=1) #check with band that is 30m if this 10m would work
    gif=dgif(ts,fps=0.5, date_bg=(34, 229, 235),date_color=(0, 0, 0),date_position="lr", date_format="%Y-%m-%d_%H:%M:%S", bytes=True).compute()#cmap="Greys",
    path=save_gif(gif)
    gif_path_list.append(path)
    

    return gif_path_list[0] if len(gif_path_list) == 1 else gif_path_list


def get_xml_metadata(items):

    assets=items[0].assets.items()
    dict_assets=dict(assets)
    xml_item=dict_assets.get('mtl.xml')

    mtl_xml_url = xml_item.href

    response = requests.get(mtl_xml_url)

    if response.status_code == 200:
        with open('mtl.xml', 'wb') as f:
            f.write(response.content)
        print("Download successful!")
    else:
        print("Failed to download:", response.status_code)


    
