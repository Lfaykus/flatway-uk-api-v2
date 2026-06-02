from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
import psycopg2.extras
import requests
import base64
import os

app = FastAPI(title="Flatway Great Britain Property API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

DATABASE_URL = os.getenv("DATABASE_URL")
SCOTLAND_API_USER = os.getenv("SCOTLAND_API_USER", "b14e94f6-f76c-44eb-80f3-ef26d09229a8")
SCOTLAND_API_PASS = os.getenv("SCOTLAND_API_PASS", "a8b9767a-a267-4907-b5f7-419c58a4bdf0")

SCOTTISH_PREFIXES = {"EH","G","KA","PA","DD","AB","FK","KY","ML","PH","TD","DG","IV","KW","HS","ZE"}

def is_scottish_postcode(postcode: str) -> bool:
    prefix = postcode.strip().upper().split()[0]
    letters = "".join(filter(str.isalpha, prefix))
    return letters in SCOTTISH_PREFIXES

def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)

def land_registry_get(postcode: str):
    try:
        r = requests.get(
            "https://landregistry.data.gov.uk/data/ppi/transaction-record.json",
            params={"propertyAddress.postcode": postcode, "_pageSize": 5, "_sort": "-transactionDate"},
            timeout=10,
        )
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def scotland_search(postcode: str):
    try:
        token = base64.b64encode(f"{SCOTLAND_API_USER}:{SCOTLAND_API_PASS}".encode()).decode()
        r = requests.get(
            "https://api.epcdata.scot/ew-compatible",
            params={"postcode": postcode, "limit": "20"},
            headers={"Authorization": f"Basic {token}"},
            timeout=10,
        )
        return r.json().get("data", [])
    except:
        return []

def scotland_get(lmk_key: str):
    try:
        token = base64.b64encode(f"{SCOTLAND_API_USER}:{SCOTLAND_API_PASS}".encode()).decode()
        r = requests.get(
            "https://api.epcdata.scot/ew-compatible",
            params={"lmk-key": lmk_key},
            headers={"Authorization": f"Basic {token}"},
            timeout=10,
        )
        data = r.json().get("data", [])
        return data[0] if data else None
    except:
        return None

def format_scotland_property(s, certificate_number):
    postcode = s.get("postcode", "")
    coords = None
    if postcode:
        try:
            pc = requests.get(f"https://api.postcodes.io/postcodes/{postcode.replace(' ', '%20')}", timeout=10).json()
            if pc.get("status") == 200 and pc["result"].get("latitude"):
                coords = {"lat": pc["result"]["latitude"], "lon": pc["result"]["longitude"]}
        except:
            pass
    return {"property": {
        "certificate_number": certificate_number,
        "uprn": s.get("uprn"),
        "full_address": s.get("address", ""),
        "address_line_1": s.get("address1"),
        "postcode": postcode,
        "town": s.get("address3"),
        "local_authority": s.get("local-authority-label"),
        "constituency": s.get("constituency-label"),
        "country": "Scotland",
        "region": None,
        "coordinates": coords,
        "property_type": s.get("property-type"),
        "built_form": s.get("built-form"),
        "construction_age_band": s.get("construction-age-band"),
        "floor_area_sqm": float(s["total-floor-area"]) if s.get("total-floor-area") else None,
        "number_of_rooms": int(s["number-habitable-rooms"]) if s.get("number-habitable-rooms") else None,
        "number_of_heated_rooms": int(s["number-heated-rooms"]) if s.get("number-heated-rooms") else None,
        "tenure": s.get("tenure"),
        "epc_rating": s.get("current-energy-rating"),
        "epc_score": int(s["current-energy-efficiency"]) if s.get("current-energy-efficiency") else None,
        "epc_potential_rating": s.get("potential-energy-rating"),
        "epc_potential_score": int(s["potential-energy-efficiency"]) if s.get("potential-energy-efficiency") else None,
        "epc_inspection_date": s.get("inspection-date"),
        "epc_lodgement_date": s.get("lodgement-date"),
        "walls_description": s.get("walls-description"),
        "roof_description": s.get("roof-description"),
        "windows_description": s.get("windows-description"),
        "floor_description": s.get("floor-description"),
        "heating_type": s.get("mainheat-description"),
        "main_fuel": s.get("main-fuel"),
        "has_solar_panels": False,
        "has_solar_water_heating": s.get("solar-water-heating-flag") == "Y",
        "heating_cost_current": float(s["heating-cost-current"]) if s.get("heating-cost-current") else None,
        "hot_water_cost_current": float(s["hot-water-cost-current"]) if s.get("hot-water-cost-current") else None,
        "lighting_cost_current": float(s["lighting-cost-current"]) if s.get("lighting-cost-current") else None,
        "co2_emissions_current": float(s["co2-emissions-current"]) if s.get("co2-emissions-current") else None,
        "energy_consumption_current": float(s["energy-consumption-current"]) if s.get("energy-consumption-current") else None,
        "price_history": [],
    }}

@app.get("/")
def root():
    return {"status": "Flatway Great Britain Property API running"}

@app.get("/autocomplete")
def autocomplete(q: str = Query(..., description="Address or postcode")):
    if not q or len(q) < 3:
        return {"suggestions": [], "type": "address"}
    q_clean = q.strip().upper()
    if is_scottish_postcode(q_clean):
        rows = scotland_search(q_clean)
        suggestions = [{"label": r.get("address", ""), "certificate_number": r.get("lmk-key"), "uprn": r.get("uprn"), "postcode": r.get("postcode"), "type": "address"} for r in rows[:8]]
        return {"suggestions": suggestions, "type": "address"}
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""SELECT certificate_number, address1, address2, address3, posttown, postcode, uprn FROM epc_certificates WHERE lower(postcode) LIKE %s OR lower(address1) LIKE %s LIMIT 8""", (q_clean.lower() + "%", q_clean.lower() + "%"))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    suggestions = []
    for row in rows:
        parts = [p for p in [row["address1"], row["address2"], row["address3"], row["posttown"], row["postcode"]] if p]
        suggestions.append({"label": ", ".join(parts), "certificate_number": row["certificate_number"], "uprn": row["uprn"], "postcode": row["postcode"], "type": "address"})
    return {"suggestions": suggestions, "type": "address"}

@app.get("/property/{certificate_number}")
def get_property(certificate_number: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM epc_certificates WHERE certificate_number = %s", (certificate_number,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        s = scotland_get(certificate_number)
        if not s:
            raise HTTPException(status_code=404, detail="Property not found")
        return format_scotland_property(s, certificate_number)
    postcode = row.get("postcode", "")
    coords = None
    if postcode:
        try:
            r = requests.get(f"https://api.postcodes.io/postcodes/{postcode.replace(' ', '%20')}", timeout=10)
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
                tenure = item.get("estateType")
                if isinstance(tenure, dict):
                    tenure = tenure.get("prefLabel", [{}])[0].get("_value")
                prop_type = item.get("propertyType")
                if isinstance(prop_type, dict):
                    prop_type = prop_type.get("prefLabel", [{}])[0].get("_value")
                price_history.append({"date": item.get("transactionDate"), "price": item.get("pricePaid"), "tenure": tenure, "property_type": prop_type})
    return {"property": {
        "certificate_number": certificate_number,
        "uprn": row.get("uprn"),
        "full_address": ", ".join(filter(None, [row.get("address1"), row.get("address2"), row.get("address3"), row.get("posttown"), postcode])),
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
    q_clean = q.strip().upper()
    if is_scottish_postcode(q_clean):
        rows = scotland_search(q_clean)
        if not rows:
            raise HTTPException(status_code=404, detail="No results found")
        results = [{"certificate_number": r.get("lmk-key"), "full_address": r.get("address", ""), "postcode": r.get("postcode"), "uprn": r.get("uprn"), "epc_rating": r.get("current-energy-rating")} for r in rows]
        return {"count": len(results), "properties": results}
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""SELECT certificate_number, address1, address2, address3, posttown, postcode, uprn, current_energy_rating FROM epc_certificates WHERE lower(postcode) LIKE %s OR lower(address1) LIKE %s LIMIT 20""", (q_clean.lower() + "%", q_clean.lower() + "%"))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        raise HTTPException(status_code=404, detail="No results found")
    results = []
    for row in rows:
        parts = [p for p in [row["address1"], row["address2"], row["address3"], row["posttown"], row["postcode"]] if p]
        results.append({"certificate_number": row["certificate_number"], "full_address": ", ".join(parts), "postcode": row["postcode"], "uprn": row["uprn"], "epc_rating": row["current_energy_rating"]})
    return {"count": len(results), "properties": results}
