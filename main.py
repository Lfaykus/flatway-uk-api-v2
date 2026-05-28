from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
import psycopg2.extras
import requests
import os

app = FastAPI(title="Flatway UK Property Search v2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

DATABASE_URL = os.getenv("DATABASE_URL")

def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)

def land_registry_get(postcode: str):
    try:
        r = requests.get(
            "https://landregistry.data.gov.uk/data/ppi/transaction-record.json",
            params={
                "propertyAddress.postcode": postcode,
                "_pageSize": 5,
                "_sort": "-transactionDate"
            },
            timeout=10,
        )
        return r.json()
    except Exception as e:
        return {"error": str(e)}

@app.get("/")
def root():
    return {"status": "Flatway UK Property API v2 running"}

@app.get("/autocomplete")
def autocomplete(q: str = Query(..., description="Address or postcode")):
    if not q or len(q) < 3:
        return {"suggestions": [], "type": "address"}

    q_clean = q.strip().upper()

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT DISTINCT ON (postcode, address1)
            certificate_number, address1, address2, address3,
            posttown, postcode, uprn
        FROM epc_certificates
        WHERE postcode ILIKE %s OR address1 ILIKE %s
        ORDER BY postcode, address1, lodgement_date DESC
        LIMIT 8
    """, (f"{q_clean}%", f"{q_clean}%"))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    suggestions = []
    for row in rows:
        parts = [p for p in [row["address1"], row["address2"], row["address3"], row["posttown"], row["postcode"]] if p]
        suggestions.append({
            "label": ", ".join(parts),
            "certificate_number": row["certificate_number"],
            "uprn": row["uprn"],
            "postcode": row["postcode"],
            "type": "address",
        })

    return {"suggestions": suggestions, "type": "address"}

@app.get("/property/{certificate_number}")
def get_property(certificate_number: str):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM epc_certificates
        WHERE certificate_number = %s
    """, (certificate_number,))

    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Property not found")

    postcode = row.get("postcode", "")

    coords = None
    if postcode:
        try:
            r = requests.get(
                f"https://api.postcodes.io/postcodes/{postcode.replace(' ', '%20')}",
                timeout=10
            )
            pc = r.json()
            if pc.get("status") == 200:
                result = pc.get("result", {})
                if result.get("latitude"):
                    coords = {"lat": result["latitude"], "lon": result["longitude"]}
        except:
            pass

    price_history = []
    if postcode:
        lr_data = land_registry_get(postcode)
        if lr_data and "result" in lr_data:
            for item in lr_data["result"].get("items", [])[:5]:
                price_history.append({
                    "date": item.get("transactionDate", {}).get("value"),
                    "price": item.get("pricePaid"),
                    "tenure": item.get("estateType", {}).get("prefLabel", [{}])[0].get("_value"),
                    "property_type": item.get("propertyType", {}).get("prefLabel", [{}])[0].get("_value"),
                })

    return {"property": {
        "certificate_number": certificate_number,
        "uprn": row.get("uprn"),
        "full_address": ", ".join(filter(None, [
            row.get("address1"), row.get("address2"),
            row.get("address3"), row.get("posttown"), postcode
        ])),
        "address_line_1": row.get("address1"),
        "postcode": postcode,
        "town": row.get("posttown"),
        "local_authority": row.get("local_authority_label"),
        "constituency": row.get("constituency_label"),
        "country": row.get("country"),
        "region": row.get("region"),
        "coordinates": coords,
        "property_type": row.get("property_type"),
        "built_form": row.get("built_form"),
        "construction_age_band": row.get("construction_age_band"),
        "floor_area_sqm": row.get("total_floor_area"),
        "number_of_rooms": row.get("number_habitable_rooms"),
        "number_of_heated_rooms": row.get("number_heated_rooms"),
        "tenure": row.get("tenure"),
        "epc_rating": row.get("current_energy_rating"),
        "epc_score": row.get("current_energy_efficiency"),
        "epc_potential_rating": row.get("potential_energy_rating"),
        "epc_potential_score": row.get("potential_energy_efficiency"),
        "epc_inspection_date": str(row.get("inspection_date")) if row.get("inspection_date") else None,
        "epc_lodgement_date": str(row.get("lodgement_date")) if row.get("lodgement_date") else None,
        "walls_description": row.get("walls_description"),
        "roof_description": row.get("roof_description"),
        "windows_description": row.get("windows_description"),
        "floor_description": row.get("floor_description"),
        "heating_type": row.get("mainheat_description"),
        "main_fuel": row.get("main_fuel"),
        "has_solar_panels": row.get("photo_supply", 0) > 0 if row.get("photo_supply") is not None else None,
        "has_solar_water_heating": row.get("solar_water_heating_flag") == "Y",
        "heating_cost_current": row.get("heating_cost_current"),
        "hot_water_cost_current": row.get("hot_water_cost_current"),
        "lighting_cost_current": row.get("lighting_cost_current"),
        "co2_emissions_current": row.get("co2_emissions_current"),
        "energy_consumption_current": row.get("energy_consumption_current"),
        "price_history": price_history,
    }}

@app.get("/search/address")
def search_by_address(q: str = Query(..., description="Address or postcode")):
    conn = get_conn()
    cur = conn.cursor()

    q_clean = q.strip().upper()

    cur.execute("""
        SELECT DISTINCT ON (postcode, address1)
            certificate_number, address1, address2, address3,
            posttown, postcode, uprn, current_energy_rating
        FROM epc_certificates
        WHERE postcode ILIKE %s OR address1 ILIKE %s OR address ILIKE %s
        ORDER BY postcode, address1, lodgement_date DESC
        LIMIT 20
    """, (f"{q_clean}%", f"{q_clean}%", f"%{q_clean}%"))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        raise HTTPException(status_code=404, detail="No results found")

    results = []
    for row in rows:
        parts = [p for p in [row["address1"], row["address2"], row["address3"], row["posttown"], row["postcode"]] if p]
        results.append({
            "certificate_number": row["certificate_number"],
            "full_address": ", ".join(parts),
            "postcode": row["postcode"],
            "uprn": row["uprn"],
            "epc_rating": row["current_energy_rating"],
        })

    return {"count": len(results), "properties": results}
