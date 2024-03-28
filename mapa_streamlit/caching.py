import json
from hashlib import md5

def get_hash_of_geojson(bbox_geojson: dict) -> str:
    return md5(json.dumps(bbox_geojson, sort_keys=True).encode()).hexdigest()


