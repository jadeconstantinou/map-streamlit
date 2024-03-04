# mapa-streamlit 🌍

This app was built by using Fabien Gebhart's mapa repo https://github.com/fgebhart/mapa as a foundation to enable this app to be created with more functionalities such as requesting more data from different collections and different bands.


## Development & Contributions

Contributions are welcome! In case you would like to contribute to the
[mapa python package](https://pypi.org/project/mapa/), have a look at the
[mapa repository](https://github.com/fgebhart/mapa).

For setting up the development environment, clone this repo

```
git clone git@github.com:fgebhart/mapa-streamlit.git && cd mapa-streamlit
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
