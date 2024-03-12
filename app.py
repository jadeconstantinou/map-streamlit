import datetime
import logging
import os
import time
from typing import List

import folium
from matplotlib import pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
from folium.plugins import Draw
from mapa_streamlit import convert_bbox_to_tif
from mapa_streamlit.caching import get_hash_of_geojson
from mapa_streamlit.stac import create_and_save_gif, fetch_stac_items_for_bbox, get_band_metadata
from mapa_streamlit.utils import GIFTMPDIR, TMPDIR
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


def _compute_tif(geometry: dict, progress_bar: st.progress,user_defined_collection,user_defined_bands,date_range) -> None:
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
        date_range=date_range,
        split_area_in_tiles= "1x1",
    )
    st.sidebar.success("Successfully requested tif file!")


def _check_area_and_compute_tif(folium_output: dict, geo_hash: str, progress_bar: st.progress,date_range:str) -> None:
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
        _compute_tif(geometry, progress_bar,user_defined_collection, user_defined_bands,date_range)

def _compute_gif(folium_output: dict, geo_hash: str,date_range:str):
    
    user_defined_collection=st.session_state.selected_collection
    user_defined_bands=st.session_state.selected_bands

    all_drawings_dict = {
        get_hash_of_geojson(draw["geometry"]): draw["geometry"] for draw in folium_output["all_drawings"]
    }
    geometry = all_drawings_dict[geo_hash]
    path= TMPDIR()

    geo_hash = get_hash_of_geojson(geometry)
    mapa_cache_dir = GIFTMPDIR()
    run_cleanup_job(path=mapa_cache_dir, disk_cleaning_threshold=DISK_CLEANING_THRESHOLD)
    path = mapa_cache_dir / geo_hash

    create_and_save_gif(geometry,geo_hash,user_defined_collection,user_defined_bands,path,date_range)
    
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
            data=gif_bytes,
            file_name="gif.zip",
            on_click=_compute_gif,
            mime="application/zip",
            kwargs={"folium_output": output, "geo_hash": geo_hash, "date_range":date_range},
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



def create_histogram(paths, array, tif_selectbox, selected_bands):
    if len(selected_bands)==1:
        print(array.shape)
        print("name: ", tif_selectbox)
        filenames = [path.name for path in paths]
        data_distributions = array.squeeze(axis=-1)  
        histogram_traces = []
        for filename, distribution_data in zip(filenames, data_distributions):
            if filename == tif_selectbox:
                histogram_trace = go.Histogram(x=distribution_data.flatten(), name=filename, histnorm='probability')
                histogram_traces.append(histogram_trace)
        if histogram_traces:  
            layout = go.Layout(title='Pixel Value Distribution Plot', xaxis=dict(title='Pixel Value'), yaxis=dict(title='Frequency'))
            fig = go.Figure(data=histogram_traces, layout=layout)
            st.plotly_chart(fig)
        else:
            st.write(f"No histogram data found for '{tif_selectbox}'.")
        
    if len(selected_bands)>1:
            print("name: ", tif_selectbox)
            filenames = [path.name for path in paths]
            filenames = list(dict.fromkeys(filenames))
            histogram_traces = []
            for filename, distribution_data in zip(filenames, array):
                if filename == tif_selectbox:
                    for i in range(len(selected_bands)):
                        distribution_array = distribution_data[i]
                        histogram_trace = go.Histogram(x=distribution_array.flatten(), name=f'{filename} - {selected_bands[i]}', histnorm='probability')
                        histogram_traces.append(histogram_trace)
            if histogram_traces:  
                layout = go.Layout(title='Pixel Value Distribution Plot', xaxis=dict(title='Pixel Value'), yaxis=dict(title='Frequency'))
                fig = go.Figure(data=histogram_traces, layout=layout)
                st.plotly_chart(fig)
            else:
                st.write(f"No histogram data found for '{tif_selectbox}'.")
        


def plot_images(create_histogram, geo_hash, date_range,folium_output,user_defined_collection ,user_defined_bands):


    all_drawings_dict = {
            get_hash_of_geojson(draw["geometry"]): draw["geometry"] for draw in folium_output["all_drawings"]
        }
    geometry = all_drawings_dict[geo_hash]

    paths, array,xx = fetch_stac_items_for_bbox(
            user_defined_bands,
            user_defined_collection,
            geometry,
            allow_caching=True,
            cache_dir=TMPDIR(),
            date_range=date_range,
            progress_bar=None
        )

    filenames = [path.name for path in paths]
    filenames = list(dict.fromkeys(filenames))
    tif_selectbox = st.selectbox("Choose an option", filenames)
    if tif_selectbox:
        st.write(f"You have chosen: {tif_selectbox}")
        create_histogram(paths,array,tif_selectbox,user_defined_bands)
            
        if len(user_defined_bands)==1:
            bands_str = ", ".join(map(str, user_defined_bands))
            for arr in xx[bands_str]:
                fig, ax = plt.subplots()
                date_time=pd.to_datetime(arr.time.values).to_pydatetime().strftime("%Y-%m-%d_%H-%M-%S")+".tif"
                if date_time in tif_selectbox:
                    ax.set_title(date_time)
                    im = ax.imshow(arr)
                    plt.colorbar(im)
                    st.pyplot(fig)
        
                        
        if len(user_defined_bands) > 1:
            print(user_defined_bands)
               
                
            if user_defined_bands==['B02', 'B03', 'B04']:
                user_defined_bands.reverse()
                band_values_list = [xx[band].values for band in user_defined_bands]
            else:
                band_values_list = [xx[band].values for band in user_defined_bands]

            if len(user_defined_bands) == 2:
                empty_band = np.empty_like(band_values_list[0])
                empty_band.fill(np.nan)
                stacked_image = np.stack(band_values_list + [empty_band], axis=-1)

            if len(user_defined_bands)==3:
                stacked_image = np.stack(band_values_list, axis=-1)
                
                
            arr_normalized = stacked_image / 10000
            datetimes = pd.to_datetime(xx.time.values.astype('datetime64[s]')).strftime("%Y-%m-%d_%H-%M-%S")

            for i, date_time in enumerate(datetimes):
                if date_time in tif_selectbox:
                    fig, ax = plt.subplots()
                    ax.imshow(arr_normalized[i])
                    ax.set_title(f"{date_time}")
                    st.pyplot(fig)


# def toggle_instructions():
#     st.session_state.show_instructions = not st.session_state.show_instructions


def date_range_selector():
    today = datetime.datetime.now()
    this_year = today.year

    five_years_ago = this_year - 5
    five_years_ago_jan_1 = datetime.date(five_years_ago, 1, 1)

    d = st.date_input(
            "Select your time range",
            (five_years_ago_jan_1, today),  
            five_years_ago_jan_1,  
            today,  
            format="DD.MM.YYYY",
        )
    
    return d

if __name__ == "__main__":
    st.set_page_config(
        page_title="mapa",
        page_icon="🌍",
        layout="wide",
        initial_sidebar_state="expanded",      
    )


    st.markdown(
        """
        #  Open Data Explorer
        """,
        unsafe_allow_html=True,
    )
    st.write("\n")
    if 'show_instructions' not in st.session_state:
        st.session_state.show_instructions = False

    # Button to toggle instructions visibility
    if st.button('Instructions'):
        toggle_instructions()

    # Instructions section
    if st.session_state.show_instructions:
        st.markdown(
            f"""
             1. Zoom to your region of interest on the map &nbsp; 🌍 &nbsp;
             2. Click the black square on the map to draw a polygon
             3. Select date range, collection and up to 3 bands in the sidebar dropdown menus. If you need more information about the bands, scroll down on the sidebar to find a band metadata table
             3. Click on <kbd>{BTN_LABEL_CREATE_TIF}</kbd>
             4. Wait for the computation to finish
             5. Below the map, view the 'Requested tif information' to view images and their pixel value distribution
             5. Click on <kbd>{BTN_LABEL_DOWNLOAD_TIFS}</kbd> or <kbd>{BTN_LABEL_DOWNLOAD_GIFS}</kbd> 
            
             """,
            unsafe_allow_html=True,)

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

        d = date_range_selector()
        date_range=str('/'.join(map(str, d)))
        

        if 'selected_collection' not in st.session_state:
            st.session_state.selected_collection = st.selectbox('Select a collection', (collection_data.keys()))
        if 'selected_bands' not in st.session_state:
            st.session_state.selected_bands = st.multiselect('Select bands', collection_data[st.session_state.selected_collection])
        else:
            selected_collection= st.selectbox('Select a collection', (collection_data.keys()))
            st.session_state.selected_collection =selected_collection

            if st.session_state.selected_collection != 'select':
                selected_bands = st.multiselect('Select bands', collection_data[selected_collection])
                st.session_state.selected_bands = selected_bands


        find_tifs_button=st.button(
            BTN_LABEL_CREATE_TIF,
            key="find_tifs_button",
            #on_click=lambda: trigger_functions(output, geo_hash, progress_bar),
            on_click=_check_area_and_compute_tif, 
            kwargs={"folium_output": output, "geo_hash": geo_hash, "progress_bar": progress_bar, "date_range":date_range},
            disabled=False if geo_hash else True,
        )

        output_tifs_file = TMPDIR() / f"{geo_hash}.zip"
        if output_tifs_file.is_file():
            with open(output_tifs_file, "rb") as fp:
                _download_tifs_btn(fp, False)
        else:
            _download_tifs_btn(b"None", True)


        output_gifs_file = GIFTMPDIR() / f"{geo_hash}.zip"
        download_enabled = False
        if output_gifs_file.is_file():
            download_enabled = True
            with open(output_gifs_file, "rb") as fp:
                gif_bytes = fp.read()
                if download_enabled:
                    time.sleep(4)
                    _download_gifs_btn(gif_bytes,False)         
        else:
            _download_gifs_btn(b"None", True)


        st.sidebar.markdown("---")

    with st.sidebar.container():
        st.write(
             """
             # Metadata
             Please view the table below for more information about your band selection
             """
         )
                
        if 'selected_collection' not in st.session_state:
            selected_collection = st.table(get_band_metadata(selected_collection))
        else:
            selected_collection= st.table(get_band_metadata(selected_collection))
           

   
  
  #Outside of the sidebar  
    if 'tif_button_clicked' not in st.session_state:
        st.session_state.tif_button_clicked = False

    if find_tifs_button:
        st.session_state.tif_button_clicked = True

    if st.session_state.tif_button_clicked:
        st.markdown(
        """
        # Requested tif information
        Please use the dropdown box to investigate your queried data.
        """,
        unsafe_allow_html=True,
    )
        
        plot_images(create_histogram, geo_hash, date_range,output,st.session_state.selected_collection, st.session_state.selected_bands)

        
        


                
                

                