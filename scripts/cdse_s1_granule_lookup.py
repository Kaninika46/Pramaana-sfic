"""Query Copernicus Data Space Ecosystem (CDSE) OData catalogue for Sentinel-1 GRD
granules intersecting Ghatal (22.6654 N, 87.7218 E), 10-28 September 2024."""

import json
import sys
import urllib.parse
import urllib.request

FILTER = (
    "Collection/Name eq 'SENTINEL-1' "
    "and OData.CSC.Intersects(area=geography'SRID=4326;POINT(87.7218 22.6654)') "
    "and ContentDate/Start gt 2024-09-10T00:00:00.000Z "
    "and ContentDate/Start lt 2024-09-28T23:59:59.000Z "
    "and contains(Name,'GRD')"
)
params = {
    "$filter": FILTER,
    "$orderby": "ContentDate/Start asc",
    "$top": "50",
    "$expand": "Attributes",
}
url = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products?" + urllib.parse.urlencode(
    params, quote_via=urllib.parse.quote
)

with urllib.request.urlopen(url, timeout=60) as resp:
    data = json.load(resp)

out = []
for p in data.get("value", []):
    attrs = {a["Name"]: a.get("Value") for a in p.get("Attributes", [])}
    out.append(
        {
            "name": p["Name"],
            "id": p["Id"],
            "start_utc": p["ContentDate"]["Start"],
            "end_utc": p["ContentDate"]["End"],
            "platform": attrs.get("platformSerialIdentifier"),
            "orbit_direction": attrs.get("orbitDirection"),
            "relative_orbit": attrs.get("relativeOrbitNumber"),
            "absolute_orbit": attrs.get("orbitNumber"),
            "mode": attrs.get("operationalMode"),
            "polarisation": attrs.get("polarisationChannels"),
            "product_type": attrs.get("productType"),
        }
    )

print(json.dumps(out, indent=2))
json.dump(
    {"query_url": url, "granules": out},
    open(sys.argv[1], "w", encoding="utf-8"),
    indent=2,
)
