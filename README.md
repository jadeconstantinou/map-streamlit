# mapa-streamlit 🌍

Download Sentinel 2 and Landsat data!!

This app was built by using the mapa repo https://github.com/fgebhart/mapa by Fabien Gebhart as a foundation to enable the creation of this app with functionalities such as requesting more data from different collections and different bands.



For setting up the development environment, clone this repo

```
git clone https://github.com/jadeconstantinou/map-streamlit.git && cd mapa-streamlit
```

and run the following commands to install the requirements (in case you don't have poetry install, you can do so with
`pip install poetry`):

```
poetry install
poetry shell
```

To run the tests, run:

```
pytest tests/
```

To run the streamlit app, run:

```
streamlit run app.py
```
