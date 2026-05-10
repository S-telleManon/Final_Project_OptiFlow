# import openrouteservice

# client = openrouteservice.Client(key="YOUR_ORS_KEY")


# def geocode(address):

#     if not address:
#         return None, None

#     try:
#         res = client.pelias_search(text=address)

#         features = res.get("features", [])

#         if len(features) == 0:
#             print("No geocoding result for:", address)
#             return None, None

#         coords = features[0]["geometry"]["coordinates"]

#         lon = coords[0]
#         lat = coords[1]

#         return lat, lon

#     except Exception as e:
#         print("Geocoding error:", address, "->", e)
#         return None, None

import requests

def geocode(address):
    try:
        url = "https://nominatim.openstreetmap.org/search"

        params = {
            "q": address,
            "format": "json",
            "limit": 1
        }

        headers = {
            "User-Agent": "OptiFlow-System"
        }

        r = requests.get(url, params=params, headers=headers)
        data = r.json()

        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])

        return None, None

    except Exception as e:
        print("Geocoding error:", address, "->", e)
        return None, None