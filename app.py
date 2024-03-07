import datetime
import logging
import os
from typing import List

import folium
import numpy as np
import pandas as pd
import streamlit as st
from folium.plugins import Draw
from mapa_streamlit import convert_bbox_to_tif
from mapa_streamlit.caching import get_hash_of_geojson
from mapa_streamlit.stac import create_and_save_gif, fetch_stac_items_for_bbox, get_band_metadata
from mapa_streamlit.utils import TMPDIR
from streamlit_folium import st_folium
import plotly.graph_objects as go


from mapa_streamlit.cleaning import run_cleanup_job
from mapa_streamlit.settings import (
    BTN_LABEL_CREATE_TIF,
    BTN_LABEL_DOWNLOAD_GIFS,
    BTN_LABEL_DOWNLOAD_TIFS,
    DEFAULT_TILING_FORMAT,
    DISK_CLEANING_THRESHOLD,
    MAP_CENTER,
    MAP_ZOOM,
    MAX_ALLOWED_AREA_SIZE,
    TilingSelect,
    
)
from mapa_streamlit.verification import selected_bbox_in_boundary, selected_bbox_too_large

log = logging.getLogger(__name__)
log.setLevel(os.getenv("MAPA_STREAMLIT_LOG_LEVEL", "DEBUG"))


def _show_map(center: List[float], zoom: int) -> folium.Map:
    m = folium.Map(
        location=center,
        zoom_start=zoom,
        control_scale=True,
        tiles="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
        attr='Map data: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, <a href="http://viewfinderpanoramas.org">SRTM</a> | Map style: &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA</a>)',  # noqa: E501
    )
    Draw(
        export=False,
        position="topleft",
        draw_options={
            "polyline": False,
            "poly": False,
            "circle": False,
            "polygon": False,
            "marker": False,
            "circlemarker": False,
            "rectangle": True,
        },
    ).add_to(m)
    return m


def _compute_tif(geometry: dict, progress_bar: st.progress,user_defined_collection,user_defined_bands) -> None:
    geo_hash = get_hash_of_geojson(geometry)
    mapa_cache_dir = TMPDIR()
    run_cleanup_job(path=mapa_cache_dir, disk_cleaning_threshold=DISK_CLEANING_THRESHOLD)
    path = mapa_cache_dir / geo_hash
    progress_bar.progress(0)
    convert_bbox_to_tif(
        user_defined_collection=user_defined_collection, 
        user_defined_bands=user_defined_bands,
        bbox_geometry=geometry,
        output_file=path,
        progress_bar=progress_bar,
        split_area_in_tiles=DEFAULT_TILING_FORMAT if tiling_option is None else tiling_option,
    )
    # it is important to spawn this success message in the sidebar, because state will get lost otherwise
    st.sidebar.success("Successfully requested tif file!")


def _check_area_and_compute_tif(folium_output: dict, geo_hash: str, progress_bar: st.progress) -> None:
    user_defined_collection=st.session_state.selected_collection
    user_defined_bands=st.session_state.selected_bands
    all_drawings_dict = {
        get_hash_of_geojson(draw["geometry"]): draw["geometry"] for draw in folium_output["all_drawings"]
    }
    geometry = all_drawings_dict[geo_hash]
    if selected_bbox_too_large(geometry, threshold=MAX_ALLOWED_AREA_SIZE):
        st.sidebar.warning(
            "Selected region is too large, fetching data for this area would consume too many resources. "
            "Please select a smaller region."
        )
    elif not selected_bbox_in_boundary(geometry):
        st.sidebar.warning(
            "Selected rectangle is not within the allowed region of the world map. Do not scroll too far to the left or "
            "right. Ensure to use the initial center view of the world for drawing your rectangle."
        )
    else:
        _compute_tif(geometry, progress_bar,user_defined_collection, user_defined_bands)

def _compute_gif(folium_output: dict, geo_hash: str):
    
    user_defined_collection=st.session_state.selected_collection
    user_defined_bands=st.session_state.selected_bands

    all_drawings_dict = {
        get_hash_of_geojson(draw["geometry"]): draw["geometry"] for draw in folium_output["all_drawings"]
    }
    geometry = all_drawings_dict[geo_hash]
    path= TMPDIR()

    # geo_hash = get_hash_of_geojson(geometry)
    # mapa_cache_dir = TMPDIR()
    # run_cleanup_job(path=mapa_cache_dir, disk_cleaning_threshold=DISK_CLEANING_THRESHOLD)
    # path = mapa_cache_dir / geo_hash

    create_and_save_gif(geometry,user_defined_collection,user_defined_bands,path)
    #print("THIS PATH IN COMPUTE_PATH,", path)
    #return path
    st.sidebar.success("Successfully zipped gif file!")

def _download_tifs_btn(data: str, disabled: bool) -> None:
    st.sidebar.download_button(
        label=BTN_LABEL_DOWNLOAD_TIFS,
        data=data,
        file_name=f'{datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}_streamlit.zip',
        disabled=disabled,
    )

def _download_gifs_btn(gif_bytes: str, disabled: bool) -> None:
    st.sidebar.download_button(
            label=BTN_LABEL_DOWNLOAD_GIFS,
            #key="make_gif",
            data=gif_bytes,
            file_name="gif.zip",
            on_click=_compute_gif,
            mime="application/zip",
            kwargs={"folium_output": output, "geo_hash": geo_hash},
            disabled=False if geo_hash else True,
        )
        

def _get_active_drawing_hash(state, drawings: List[str]) -> str:
    # update state initially
    if "drawings" not in state:
        state.drawings = []
    if "active_drawing" not in state:
        state.active_drawing = None

    old_drawings = state.drawings
    for d in drawings:
        if d not in old_drawings:
            active_drawing = d
            state.drawings = drawings
            state.active_drawing = active_drawing
            log.debug(f"🎨  found new active_drawing: {active_drawing}")
            return active_drawing
    else:
        log.debug(f"💾  no new drawing found, returning last active drawing from state: {state.active_drawing}")
        return state.active_drawing


collection_data = {
    'sentinel-2-l2a':("AOT","B01","B02","B03","B04","B05","B06","B07","B08","B09","B11","B12","B8A","SCL","WVP","visual"),
    'landsat-c2-l2':("qa","red","blue","drad","emis","emsd","trad","urad","atran","cdist","green","nir08","lwir11","swir16","swir22","coastal","qa_pixel","qa_radsat","qa_aerosol","cloud_qa","lwir","atmos_opacity"),
}


def create_table():
    user_defined_collection=st.session_state.selected_collection
    user_defined_bands=st.session_state.selected_bands
    folium_output=output

    all_drawings_dict = {
        get_hash_of_geojson(draw["geometry"]): draw["geometry"] for draw in folium_output["all_drawings"]
    }
    geometry = all_drawings_dict[geo_hash]
    
    _,xx=fetch_stac_items_for_bbox(user_defined_bands,
    user_defined_collection,
    geometry,
    allow_caching=True,
    cache_dir=TMPDIR(),
    progress_bar=None)

    # Assuming data_array is your numpy array with shape (1, 4, 134, 141)
    data_array = xx.to_array().to_numpy()
    data_array = np.expand_dims(data_array, axis=0)

    # Extract data for each distribution
    data_distributions = data_array.squeeze(axis=0)  # Remove the singleton dimension

    # Create histogram traces for each distribution
    histogram_traces = []
    for i, distribution_data in enumerate(data_distributions):
        histogram_trace = go.Histogram(x=distribution_data.flatten(), name=f'Distribution {i+1}', histnorm='probability')
        histogram_traces.append(histogram_trace)

    # Create layout for the plot
    layout = go.Layout(title='Pixel Value Distribution Plot', xaxis=dict(title='Value'), yaxis=dict(title='Probability'))

    # Create the figure
    fig = go.Figure(data=histogram_traces, layout=layout)

    # Show the plot
    fig.show()


def trigger_functions(folium_output, geo_hash, progress_bar):
    _check_area_and_compute_tif(folium_output, geo_hash, progress_bar)
    create_table()

if __name__ == "__main__":
    st.set_page_config(
        page_title="mapa",
        page_icon="🌍",
        layout="wide",
        initial_sidebar_state="expanded",      
    )


    st.markdown(
        """
        # &nbsp; 🌍 &nbsp; Open data download app 
        Follow the instructions in the sidebar on the left to create and download tifs.
        """,
        unsafe_allow_html=True,
    )
    st.write("\n")
    m = _show_map(center=MAP_CENTER, zoom=MAP_ZOOM)
    output = st_folium(m, key="init", width=1000, height=600)


    geo_hash = None
    if output:
        if output["all_drawings"] is not None:
            # get latest modified drawing
            all_drawings = [get_hash_of_geojson(draw["geometry"]) for draw in output["all_drawings"]]
            geo_hash = _get_active_drawing_hash(state=st.session_state, drawings=all_drawings)
    st.write("\n")
    # ensure progress bar resides at top of sidebar and is invisible initially
    progress_bar = st.sidebar.progress(0)
    progress_bar.empty()






    # Getting Started container
    with st.sidebar.container():
        if 'selected_collection' not in st.session_state:
            st.session_state.selected_collection = st.selectbox('Select a collection', (collection_data.keys()))
        if 'selected_bands' not in st.session_state:
            st.session_state.selected_bands = st.multiselect('Select bands', collection_data[st.session_state.selected_collection])
        else:
            selected_collection= st.selectbox('Select a collection', (collection_data.keys()))
            st.session_state.selected_collection =selected_collection

            if st.session_state.selected_collection != 'select':
                st.session_state.selected_bands = st.multiselect('Select bands', collection_data[selected_collection])

        st.markdown(
            f"""
            # Getting Started
            1. Zoom to your region of interest
            2. Click the black square on the map
            3. Draw a rectangle on the map
            4. Click on <kbd>{BTN_LABEL_CREATE_TIF}</kbd>
            """,
            unsafe_allow_html=True,
        )
        st.button(
            BTN_LABEL_CREATE_TIF,
            key="find_tifs",
            on_click=lambda: trigger_functions(output, geo_hash, progress_bar),
            #on_click=_check_area_and_compute_tif, 
            #kwargs={"folium_output": output, "geo_hash": geo_hash, "progress_bar": progress_bar},
            disabled=False if geo_hash else True,
        )

                

        st.markdown(
            f"""
            5. Wait for the computation to finish
            6. Click on <kbd>{BTN_LABEL_DOWNLOAD_TIFS}</kbd>
            or <kbd>{BTN_LABEL_DOWNLOAD_GIFS}</kbd>
            """,
            unsafe_allow_html=True,
        )

        
        output_tifs_file = TMPDIR() / f"{geo_hash}.zip"
        if output_tifs_file.is_file():
            with open(output_tifs_file, "rb") as fp:
                _download_tifs_btn(fp, False)
        else:
            _download_tifs_btn(b"None", True)

     
            
        
        output_gifs_file = TMPDIR() / "gif.zip"
        if output_gifs_file.is_file():
            with open(output_gifs_file, "rb") as fp:
                gif_bytes = fp.read()
                
                _download_gifs_btn(gif_bytes,False)
                
        else:
            _download_gifs_btn(b"None", True)


        st.sidebar.markdown("---")

     # Customization container
    with st.sidebar.container():
        st.write(
             """
             # Metadata
             Please view the table below for more information about your band selection
             """
         )
        
        selected_collection=st.session_state.selected_collection 
        
        if 'selected_collection' not in st.session_state:
            selected_collection = st.table(get_band_metadata(selected_collection))
        else:
            selected_collection= st.table(get_band_metadata(selected_collection))
           

        tiling_option = st.selectbox(
            label=TilingSelect.label,
            options=TilingSelect.options,
            help=TilingSelect.help,
        )

 

        
