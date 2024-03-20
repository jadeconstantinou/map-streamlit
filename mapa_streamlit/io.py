from pystac import ItemCollection

def are_stac_items_planetary_computer(item_collection: ItemCollection) -> bool:
    if not item_collection.items:
        return False
    
    absolute_href = item_collection.items[0].get_self_href()
    return (
        True
        if absolute_href and "planetarycomputer.microsoft.com" in absolute_href
        else False
    )