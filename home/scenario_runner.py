"""
scenario_runner.py   (put this file in the SAME folder as views.py)

Two separate jobs live here:

 A) SCENARIO TESTING (sandbox only)
    - SCENARIOS holds FBR's sample payload for all 28 scenarios (SN001-SN028).
    - scenarioAutoRun    -> posts pending scenarios to the FBR SANDBOX and marks them successful
    - scenarioPayload    -> shows the exact JSON for one scenario
    - scenarioPayloadAll -> downloads the JSON for all 28 scenarios

 B) REAL INVOICES (sandbox test invoices and live invoices)
    - build_invoice_payload -> turns an InvoiceModel (+ items) into the FBR payload
    - send_invoice_to_fbr   -> replaces the body of getFBRInvoice()
    - invoicePayloadPreview -> shows the payload of an invoice WITHOUT sending it
    - invoiceValidateFBR    -> asks FBR to validate an invoice WITHOUT creating it

Safety rules built in:
    * The scenario runner can only post to the sandbox URL.
    * Live invoices are validated with FBR first; nothing is posted if FBR says Invalid.
    * Live posts are never auto-retried (a timeout could hide a posted invoice = duplicate).
    * An invoice that already has an FBR invoice number is never posted twice.
"""
import json
import logging
import os
import re
import time
from datetime import date

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect

from .models import CompanyModel, InvoiceLogModel, InvoiceModeModel, InvoiceModel, ScenarioModel

logger = logging.getLogger(__name__)

FBR_BASE = "https://gw.fbr.gov.pk/di_data/v1/di/"
URL_POST_SB = FBR_BASE + "postinvoicedata_sb"
URL_POST_LIVE = FBR_BASE + "postinvoicedata"
URL_VALIDATE_SB = FBR_BASE + "validateinvoicedata_sb"
URL_VALIDATE_LIVE = FBR_BASE + "validateinvoicedata"
URL_HS_UOM = "https://gw.fbr.gov.pk/pdi/v2/HS_UOM"   # reference API: allowed UoM for an HS code
HS_UOM_ANNEXURE_ID = 3                                 # sales annexure id used in FBR's own example

REQUEST_TIMEOUT = 45        # seconds per FBR call
MAX_ATTEMPTS = 40           # max FBR calls per scenario
SCENARIO_TIME_BUDGET = 150  # seconds: a scenario run stops after this long
HS_TRY_LIMIT = 45           # how many candidate HS codes are tried when FBR says 0052
PETROLEUM_WORDS = ("motor spirit", "gasoline", "petrol", "high speed", "diesel", "kerosene", "furnace",
                   "jet", "aviation", "light diesel", "fuel", "naphtha")
VALIDATE_LIVE_FIRST = True  # live invoices are validated before they are posted

STD_RATE = "Goods at standard rate (default)"
THIRD_SCHEDULE = "3rd Schedule Goods"
REDUCED_RATE = "Goods at Reduced Rate"


# ===========================================================================
# A) SCENARIO SAMPLES (sandbox)
# ===========================================================================
def _buyer(ntn, reg_type, name="FERTILIZER MANUFAC IRS NEW"):
    return {"ntn": ntn, "type": reg_type, "name": name, "province": "Sindh", "address": "Karachi"}


def _item(**over):
    item = {
        "hsCode": "0101.2100",
        "productDescription": "TEST",
        "rate": "18%",
        "uoM": "Numbers, pieces, units",
        "quantity": 1,
        "totalValues": 0,
        "valueSalesExcludingST": 0,
        "fixedNotifiedValueOrRetailPrice": 0,
        "salesTaxApplicable": 0,
        "salesTaxWithheldAtSource": 0,
        "extraTax": 0,
        "furtherTax": 0,
        "sroScheduleNo": "",
        "fedPayable": 0,
        "discount": 0,
        "saleType": "",
        "sroItemSerialNo": "",
    }
    item.update(over)
    return item


def _sc(ntn, reg_type, variants=None, hs_prefix=None, **item):
    return {"buyer": _buyer(ntn, reg_type), "item": _item(**item), "variants": variants or [{}], "hs_prefix": hs_prefix}


# Values come from FBR's sandbox sample JSON pack. "variants" are alternative tweaks that are
# tried in order when FBR rejects the first one. Scenarios marked (*) are known to be picky on
# the FBR side - if one fails, read the FBR error on screen and adjust that entry.
SCENARIOS = {
    "SN001": _sc("2046004", "Registered", quantity=400, valueSalesExcludingST=1000,
                 salesTaxApplicable=180, extraTax="", saleType=STD_RATE),
    "SN002": _sc("1234567", "Unregistered", quantity=400, valueSalesExcludingST=1000,
                 salesTaxApplicable=180, extraTax="", saleType=STD_RATE),
    "SN003": _sc("3710505701479", "Unregistered", hsCode="7214.1010", uoM="MT",
                 valueSalesExcludingST=205000, salesTaxApplicable=36900,
                 saleType="Steel melting and re-rolling"),
    "SN004": _sc("3710505701479", "Unregistered", variants=[{}, {"hsCode": "7204.1010"}],  # (*)
                 hsCode="7204.4910", uoM="MT", valueSalesExcludingST=175000,
                 salesTaxApplicable=31500, saleType="Ship breaking"),
    "SN005": _sc("1000000000000", "Unregistered",  # (*) extraTax must be "" (not 0)
                 hsCode="0102.2930", rate="1%", valueSalesExcludingST=1000, salesTaxApplicable=10,
                 salesTaxWithheldAtSource=50.23, extraTax="", furtherTax=120.0,
                 sroScheduleNo="EIGHTH SCHEDULE Table 1", fedPayable=50.36, discount=56.36,
                 saleType=REDUCED_RATE, sroItemSerialNo="82"),
    "SN006": _sc("2046004", "Registered", hsCode="0102.2930", rate="Exempt",
                 valueSalesExcludingST=10, salesTaxWithheldAtSource=50.23, extraTax="",
                 furtherTax=120.0, sroScheduleNo="6th Schd Table I", fedPayable=50.36,
                 discount=56.36, saleType="Exempt goods", sroItemSerialNo="100"),
    "SN007": _sc("3710505701479", "Unregistered", rate="0%", quantity=100,
                 valueSalesExcludingST=100, sroScheduleNo="327(I)/2008",
                 saleType="Goods at zero-rate", sroItemSerialNo="1"),
    # FBR rejects valueSalesExcludingST = 0 (error 0300), so a real value is sent first.
    "SN008": _sc("3710505701479", "Unregistered",
                 variants=[
                     {},
                     {"totalValues": 0},
                     {"valueSalesExcludingST": 82, "totalValues": 100},
                     {"quantity": 100, "valueSalesExcludingST": 1000, "totalValues": 145,
                      "fixedNotifiedValueOrRetailPrice": 1000, "salesTaxApplicable": 180},
                 ],
                 quantity=1, totalValues=118, valueSalesExcludingST=100,
                 fixedNotifiedValueOrRetailPrice=100, salesTaxApplicable=18,
                 saleType=THIRD_SCHEDULE),
    "SN009": _sc("2046004", "Registered", variants=[{}, {"quantity": 1}],  # (*)
                 quantity=0, totalValues=2500, valueSalesExcludingST=2500,
                 salesTaxApplicable=450, saleType="Cotton ginners"),
    "SN010": _sc("1000000000000", "Unregistered", rate="17%", quantity=1000,
                 valueSalesExcludingST=100, salesTaxApplicable=17,
                 saleType="Telecommunication services"),
    "SN011": _sc("3710505701479", "Unregistered", hsCode="7214.9990", uoM="MT",  # (*)
                 totalValues=205000, valueSalesExcludingST=205000, salesTaxApplicable=36900,
                 saleType="Toll Manufacturing"),
    # (*) SN012: FBR now requires a "Petroleum Levy On" value (error 0129). The exact JSON name/format is NOT in the
    # documents I have, so this is an EXPERIMENT: the field name follows FBR's camelCase naming and three value
    # shapes are tried. Replace it with the field from FBR's newest technical document as soon as you have it.
    "SN012": _sc("1000000000000", "Unregistered",
                 variants=[{}, {"petroleumLevyOn": "Quantity"}, {"petroleumLevyOn": 100}],
                 productDescription="Petroleum Products", rate="1.43%", quantity=123, totalValues=132,
                 valueSalesExcludingST=100, salesTaxApplicable=1.43, salesTaxWithheldAtSource=2,
                 sroScheduleNo="1450(I)/2021", saleType="Petroleum Products",
                 sroItemSerialNo="4", petroleumLevyOn="Value", hs_prefix=("2710", "2711")),  # 2710 = petroleum oils, 2711 = LPG / gas
    "SN013": _sc("1000000000000", "Unregistered", rate="5%", quantity=123, totalValues=212,
                 valueSalesExcludingST=1000, salesTaxApplicable=50, salesTaxWithheldAtSource=11,
                 sroScheduleNo="1450(I)/2021", saleType="Electricity Supply to Retailers",
                 sroItemSerialNo="4"),
    "SN014": _sc("1000000000000", "Unregistered", quantity=123, valueSalesExcludingST=1000,
                 salesTaxApplicable=180, saleType="Gas to CNG stations"),
    "SN015": _sc("1000000000000", "Unregistered", quantity=123, valueSalesExcludingST=1234,
                 salesTaxApplicable=222.12, sroScheduleNo="NINTH SCHEDULE",
                 saleType="Mobile Phones", sroItemSerialNo="1(A)"),
    "SN016": _sc("1000000000078", "Unregistered", rate="5%", valueSalesExcludingST=100,  # (*)
                 salesTaxApplicable=5, saleType="Processing/Conversion of Goods"),
    "SN017": _sc("7000009", "Unregistered",  # (*) FBR checks the HS code against the sale type (0052)
                 variants=[{}, {"hsCode": "2202.1000"}, {"hsCode": "2402.2000"}],
                 rate="8%", valueSalesExcludingST=100,
                 salesTaxApplicable=8, saleType="Goods (FED in ST Mode)"),
    "SN018": _sc("1000000000056", "Unregistered", rate="8%", quantity=20,
                 valueSalesExcludingST=1000, salesTaxApplicable=80,
                 saleType="Services (FED in ST Mode)"),
    "SN019": _sc("1000000000000", "Unregistered", hsCode="0101.2900", rate="5%",
                 valueSalesExcludingST=100, salesTaxApplicable=5, sroScheduleNo="ICTO TABLE I",
                 saleType="Services", sroItemSerialNo="1(ii)(ii)(a)"),
    "SN020": _sc("1000000000000", "Unregistered", hsCode="0101.2900", rate="1%", quantity=122,
                 valueSalesExcludingST=1000, salesTaxApplicable=10,
                 sroScheduleNo="6th Schd Table III", saleType="Electric Vehicle",
                 sroItemSerialNo="20"),
    "SN021": _sc("1000000000000", "Unregistered", rate="Rs.3", quantity=12,  # (*) FBR's list: Rs.2 | Rs.3 | Rs.5 | Rs.10
                 valueSalesExcludingST=123, fixedNotifiedValueOrRetailPrice=3,
                 salesTaxApplicable=36, saleType="Cement /Concrete Block"),
    "SN022": _sc("1000000000000", "Unregistered",  # (*) rate text must match FBR's rate list
                 variants=[{}, {"rate": "18% along with rupees 60 per kilogram"}],
                 hsCode="3104.2000", rate="18% + Rs.60/kg",
                 uoM="KG", valueSalesExcludingST=100, fixedNotifiedValueOrRetailPrice=60,
                 salesTaxApplicable=78, sroScheduleNo="EIGHTH SCHEDULE Table 1",
                 saleType="Potassium Chlorate", sroItemSerialNo="56"),
    "SN023": _sc("1000000000000", "Unregistered", rate="Rs.200", quantity=123,  # (*) FBR's rate list says "Rs.200"
                 valueSalesExcludingST=234, fixedNotifiedValueOrRetailPrice=200,
                 salesTaxApplicable=24600, sroScheduleNo="581(1)/2024", saleType="CNG Sales",
                 sroItemSerialNo="Region-I"),
    "SN024": _sc("1000000000000", "Unregistered", rate="25%", quantity=123,
                 valueSalesExcludingST=1000, salesTaxApplicable=250,
                 sroScheduleNo="297(I)/2023-Table-I",
                 saleType="Goods as per SRO.297(|)/2023", sroItemSerialNo="12"),
    "SN025": _sc("1000000000078", "Unregistered", rate="0%", valueSalesExcludingST=100,
                 sroScheduleNo="EIGHTH SCHEDULE Table 1", saleType="Non-Adjustable Supplies",
                 sroItemSerialNo="81"),
    "SN026": _sc("1000000000078", "Registered", variants=[{}, {"extraTax": ""}],
                 quantity=123, valueSalesExcludingST=1000, salesTaxApplicable=180,
                 saleType=STD_RATE),
    "SN027": _sc("7000006", "Registered",
                 variants=[{}, {"totalValues": 0}, {"valueSalesExcludingST": 0, "totalValues": 0}],
                 quantity=1, totalValues=118, valueSalesExcludingST=100,
                 fixedNotifiedValueOrRetailPrice=100, salesTaxApplicable=18,
                 saleType=THIRD_SCHEDULE),
    "SN028": _sc("1000000000000", "Registered",
                 variants=[{}, {"totalValues": 0, "valueSalesExcludingST": 100,
                                "salesTaxApplicable": 1}],
                 rate="1%", totalValues=100, valueSalesExcludingST=99.01,
                 fixedNotifiedValueOrRetailPrice=100, salesTaxApplicable=0.99, extraTax="",
                 sroScheduleNo="EIGHTH SCHEDULE Table 1", saleType=REDUCED_RATE,
                 sroItemSerialNo="70"),
}


def _clean(value):
    return str(value or "").strip()


def build_payload(company, code, tmpl, buyer_type, variant, invoice_date=None):
    """Payload for one scenario, using the company's seller data."""
    buyer = tmpl["buyer"]
    item = dict(tmpl["item"])
    item.update(variant or {})
    return {
        "invoiceType": "Sale Invoice",
        "invoiceDate": invoice_date or date.today().strftime("%Y-%m-%d"),
        "sellerNTNCNIC": _clean(company.company_ntn_cnic),
        "sellerBusinessName": _clean(company.company_name),
        "sellerProvince": _clean(company.province),
        "sellerAddress": _clean(company.address),
        "buyerNTNCNIC": buyer["ntn"],
        "buyerBusinessName": buyer["name"],
        "buyerProvince": buyer["province"],
        "buyerAddress": buyer["address"],
        "buyerRegistrationType": buyer_type,
        "invoiceRefNo": "",
        "scenarioId": code,
        "items": [item],
    }


# ===========================================================================
# Shared: one call to FBR
# ===========================================================================
def _post(token, payload, url):
    """One call to an FBR endpoint. Never raises."""
    out = {"ok": False, "fatal": False, "transient": False, "invoice_no": "",
           "item_numbers": [], "error": "", "raw": ""}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        out.update(fatal=True, error=f"Could not connect to FBR (check internet / static IP whitelist): {exc}")
        return out

    out["raw"] = (resp.text or "")[:4000]

    if resp.status_code in (401, 403):
        body = (resp.text or "").strip().replace("\n", " ")[:200]
        try:  # show FBR's own code + message instead of raw JSON
            vr = (resp.json() or {}).get("validationResponse") or {}
            if vr.get("error"):
                body = f"{vr.get('errorCode', '')} {vr['error']}".strip()
        except ValueError:
            pass
        out.update(fatal=True, error=(
            f"FBR rejected access (HTTP {resp.status_code}). Sandbox token is wrong/expired "
            f"or this machine's public IP is not whitelisted. FBR said: {body or 'no message'}"))
        return out

    try:
        data = resp.json()
    except ValueError:
        # FBR sometimes sends slightly broken JSON. Read what we can from the raw text.
        text = re.sub(r"\s+", " ", (resp.text or "").strip())
        if re.search(r'"status"\s*:\s*"Valid"', text):
            m = re.search(r'"invoiceNumber"\s*:\s*"([^"]+)"', text)
            out.update(ok=True, invoice_no=m.group(1) if m else "")
            return out
        rejected = bool(re.search(r'"status"\s*:\s*"Invalid"', text))
        out.update(
            transient=not rejected,  # a real rejection is not a glitch
            error=f"FBR reply could not be parsed (HTTP {resp.status_code}). Reply: {text[:600] or 'empty'}",
        )
        return out

    if not isinstance(data, dict):
        out["error"] = f"Unexpected FBR reply: {str(data)[:200]}"
        return out

    validation = data.get("validationResponse") or {}
    if validation.get("status") == "Valid":
        out.update(ok=True, invoice_no=str(data.get("invoiceNumber", "")),
                   item_numbers=[str(s.get("invoiceNo", "")) for s in validation.get("invoiceStatuses") or []])
        return out

    errors = []
    if validation.get("error"):
        errors.append(f"{validation.get('errorCode', '')} {validation['error']}".strip())
    for st in validation.get("invoiceStatuses") or []:
        if st.get("error"):
            errors.append(f"{st.get('errorCode', '')} {st['error']}".strip())
    if not errors:
        errors.append(json.dumps(data)[:300])

    message = " | ".join(errors)
    out.update(
        error=message,
        transient=str(validation.get("errorCode", "")) == "500" or "expected time" in message.lower(),
    )
    return out


def hs_allowed_uoms(token, hs_code, annexure_id=HS_UOM_ANNEXURE_ID):
    """Units FBR allows for an HS code (reference API HS_UOM). Returns [] when FBR gives no answer."""
    try:
        r = requests.get(URL_HS_UOM, headers={"Authorization": f"Bearer {token}"},
                         params={"hs_code": hs_code, "annexure_id": annexure_id}, timeout=20)
        if r.status_code != 200:
            return []
        data = r.json()
        return [str(x.get("description", "")).strip() for x in data if isinstance(x, dict) and x.get("description")]
    except Exception:
        return []


def _uom_hints(token, payload):
    hints, seen = [], set()
    for n, item in enumerate(payload.get("items", []), start=1):
        hs = item.get("hsCode")
        if not hs or hs in seen:
            continue
        seen.add(hs)
        allowed = hs_allowed_uoms(token, hs)
        if allowed and _clean(item.get("uoM")).lower() not in [a.lower() for a in allowed]:
            hints.append(f"Item {n}: HS {hs} allows only: {', '.join(allowed)} (invoice has '{item.get('uoM')}')")
    return hints


def _sro_hints(token, payload, with_items=False):
    """0077: list valid SRO/Schedule numbers. 0078: list valid Item Sr. Nos. for the schedule given."""
    hints, seen = [], set()
    province = _clean(payload.get("sellerProvince"))
    for n, item in enumerate(payload.get("items", []), start=1):
        rate = _clean(item.get("rate"))
        sale = _clean(item.get("saleType"))
        sro = _clean(item.get("sroScheduleNo"))
        if rate.replace(" ", "") == "18%" and not sro:
            continue  # nothing is required for this item
        key = (sale, rate, sro if with_items else "")
        if key in seen:
            continue
        seen.add(key)

        info = sro_options(token, sale, rate, province, with_items=with_items)
        schedules = info.get("sro_schedules", [])

        if with_items and sro:
            mine = [x for x in schedules if x["desc"].lower() == sro.lower()]
            if mine and mine[0]["items"]:
                serials = mine[0]["items"]
                used = _clean(item.get("sroItemSerialNo"))
                if used and used in serials:
                    hints.append(f"Item {n}: your serial '{used}' IS in FBR's list for '{sro}', so check spaces/brackets "
                                 "or the sale type and rate instead.")
                else:
                    state = f"your serial '{used}' is NOT in FBR's list" if used else "the serial is empty"
                    shown = ", ".join(serials[:40])
                    more = f" ... ({len(serials)} in total; open /sro-lookup?items=1 for all)" if len(serials) > 40 else ""
                    hints.append(f"Item {n}: {state}. Valid 'sro Item Serial No' for '{sro}': {shown}{more}")
                continue

        names = [x["desc"] for x in schedules]
        if names:
            hints.append(f"Item {n} ({sale}, rate {rate}): valid SRO/Schedule No: {' | '.join(names)}"
                         " - open /sro-lookup?items=1 (with sale_type and rate) to see the item serial numbers")
        else:
            hints.append(f"Item {n} ({sale}, rate {rate}): FBR gave no SRO list; enter the SRO/Schedule "
                         "and Item Serial from the Sales Tax Act schedule that applies to this rate")
    return hints


def _with_hints(token, payload, error):
    """Add plain-English help to some FBR errors: 0099 (UoM) and 0077/0078 (SRO)."""
    error = error or ""
    extra = []
    if "0099" in error:
        extra += _uom_hints(token, payload)
    if "0090" in error:
        for n, item in enumerate(payload.get("items", []), start=1):
            if _is_fixed_type(item.get("saleType")):
                extra.append(f"Item {n} ({item.get('saleType')}): the system sent "
                             f"fixedNotifiedValueOrRetailPrice = {item.get('fixedNotifiedValueOrRetailPrice')} "
                             "- it must be the item's printed retail price (greater than 0). "
                             "That value comes from the 'Retail price' box.")
    if "0046" in error:
        extra += _rate_hints(token, payload)
    if "0077" in error or "0078" in error:
        extra += _sro_hints(token, payload, with_items="0078" in error)
    return error + (" >>> " + " ; ".join(extra) if extra else "")


REF_V1 = "https://gw.fbr.gov.pk/pdi/v1/"
REF_V2 = "https://gw.fbr.gov.pk/pdi/v2/"


def _ref_get(token, url, params=None):
    """GET a FBR reference API. Returns a list, or None if FBR did not answer properly."""
    try:
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=20)
        if r.status_code != 200:
            return None
        data = r.json()
        return data if isinstance(data, list) else None
    except Exception:
        return None


def sro_options(token, sale_type, rate_text, province, with_items=False, on_date=None):
    """
    Valid SRO/Schedule numbers (and, optionally, item serial numbers) FBR lists for a sale type + rate.
    Follows FBR's reference APIs: provinces -> transtypecode -> SaleTypeToRate -> SroSchedule -> SROItem.
    Never raises; returns whatever it could find.
    """
    out = {"sale_type": sale_type, "rate": rate_text, "province": province, "sro_schedules": [], "notes": []}
    on_date = on_date or date.today()

    provinces = _ref_get(token, REF_V1 + "provinces") or []
    prov_id = next((p.get("stateProvinceCode") for p in provinces
                    if _clean(p.get("stateProvinceDesc")).lower() == _clean(province).lower()), None)
    if prov_id is None:
        out["notes"].append(f"Province '{province}' not found in FBR's province list: "
                            + ", ".join(_clean(p.get('stateProvinceDesc')) for p in provinces))
        return out

    trans = _ref_get(token, REF_V1 + "transtypecode") or []
    tid = next((t.get("transactioN_TYPE_ID") for t in trans
                if _clean(t.get("transactioN_DESC")).lower() == _clean(sale_type).lower()), None)
    if tid is None:
        out["notes"].append(f"Sale type '{sale_type}' not found in FBR's transaction type list.")
        return out

    rates = []
    for fmt in ("%d-%b-%Y", "%d-%b%Y"):  # FBR's document prints the date format inconsistently
        rates = _ref_get(token, REF_V2 + "SaleTypeToRate",
                         {"date": on_date.strftime(fmt), "transTypeId": tid, "originationSupplier": prov_id}) or []
        if rates:
            date_fmt = fmt
            break
    if not rates:
        out["notes"].append("FBR returned no rates for this sale type.")
        return out

    want = _clean(rate_text).replace(" ", "").lower()
    match = [r for r in rates if _clean(r.get("ratE_DESC")).replace(" ", "").lower() == want]
    if not match:
        out["notes"].append("Rate not in FBR's list for this sale type. Valid rates: "
                            + " | ".join(_clean(r.get("ratE_DESC")) for r in rates))
        return out

    schedules = _ref_get(token, REF_V1 + "SroSchedule",
                         {"rate_id": match[0].get("ratE_ID"), "date": on_date.strftime(date_fmt),
                          "origination_supplier_csv": prov_id}) or []
    for sro in schedules[:15]:
        entry = {"id": sro.get("srO_ID"), "desc": _clean(sro.get("srO_DESC")), "items": []}
        if with_items:
            items = _ref_get(token, REF_V2 + "SROItem",
                             {"date": on_date.strftime("%Y-%m-%d"), "sro_id": sro.get("srO_ID")}) or []
            entry["items"] = [_clean(i.get("srO_ITEM_DESC")) for i in items[:1000]]
        out["sro_schedules"].append(entry)
    if not schedules:
        out["notes"].append("FBR lists no SRO/Schedule for this sale type and rate.")
    return out


def valid_rates(token, sale_type, province, on_date=None):
    """Rates FBR accepts for a sale type (reference API SaleTypeToRate). [] when FBR gives no answer."""
    on_date = on_date or date.today()
    provinces = _ref_get(token, REF_V1 + "provinces") or []
    prov_id = next((p.get("stateProvinceCode") for p in provinces
                    if _clean(p.get("stateProvinceDesc")).lower() == _clean(province).lower()), None)
    trans = _ref_get(token, REF_V1 + "transtypecode") or []
    tid = next((t.get("transactioN_TYPE_ID") for t in trans
                if _clean(t.get("transactioN_DESC")).lower() == _clean(sale_type).lower()), None)
    if prov_id is None or tid is None:
        return []
    for fmt in ("%d-%b-%Y", "%d-%b%Y"):
        rates = _ref_get(token, REF_V2 + "SaleTypeToRate",
                         {"date": on_date.strftime(fmt), "transTypeId": tid, "originationSupplier": prov_id}) or []
        if rates:
            return [{"id": r.get("ratE_ID"), "desc": _clean(r.get("ratE_DESC"))} for r in rates if r.get("ratE_DESC")]
    return []


def ref_hs_codes(token, prefix, limit=40):
    """(HS code, description) pairs from FBR's reference list (itemdesccode) that start with `prefix`, e.g. '2710'."""
    rows = _ref_get(token, REF_V1 + "itemdesccode") or []
    out, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        values = [str(v).strip() for v in row.values() if v is not None]
        code = next((v for v in values if re.fullmatch(r"\d{4}\.\d{4}", v)), "")
        if not code.startswith(prefix) or code in seen:
            continue
        desc = max((v for v in values if v != code and not v.isdigit()), key=len, default="")
        seen.add(code)
        out.append((code, desc))
        if len(out) >= limit:
            break
    return out


def _rate_variant(desc, item):
    """Item numbers that fit a rate text such as '5%', 'Rs.3 per kg' or '18% along with rupees 60 per kilogram'."""
    qty = _num(item.get("quantity")) or 1
    value = _num(item.get("valueSalesExcludingST"))
    out = {"rate": desc}
    pct = re.search(r"([\d.]+)\s*%", desc)
    amt = re.search(r"(?:rs\.?|rupees)\s*([\d.]+)", desc, re.I)
    tax = 0.0
    if pct:
        tax += value * float(pct.group(1)) / 100
    if amt:
        tax += float(amt.group(1)) * qty
        out["fixedNotifiedValueOrRetailPrice"] = float(amt.group(1))
    if pct or amt:
        out["salesTaxApplicable"] = round(tax, 2)
    return out


def _rate_hints(token, payload):
    hints, seen = [], set()
    for n, item in enumerate(payload.get("items", []), start=1):
        sale = _clean(item.get("saleType"))
        if sale in seen:
            continue
        seen.add(sale)
        rates = valid_rates(token, sale, _clean(payload.get("sellerProvince")))
        if rates:
            hints.append(f"Item {n} ({sale}): FBR accepts these rates: {' | '.join(r['desc'] for r in rates)} "
                         f"(invoice has '{item.get('rate')}')")
    return hints


# ===========================================================================
# A) Scenario runner (sandbox only)
# ===========================================================================
def run_scenario(company, code):
    """Try to clear one scenario on the FBR sandbox. Only ever posts to the sandbox URL."""
    tmpl = SCENARIOS.get(code)
    if tmpl is None:
        return {"code": code, "ok": False, "skipped": True, "fatal": False, "invoice_no": "",
                "error": "no auto template for this scenario - create it manually from Create Test Invoice"}

    token = _clean(company.sandbox_api)
    base_type = tmpl["buyer"]["type"]
    other_type = "Registered" if base_type == "Unregistered" else "Unregistered"
    variants = tmpl.get("variants") or [{}]

    queue = [(v, base_type) for v in variants]
    flipped = False
    uom_fixed = False
    serial_fixed = False
    rate_fixed = False
    hs_fixed = False
    hs_tried = []
    hs_left = []
    attempts = 0
    last_error = ""
    errors_seen = []
    i = 0

    deadline = time.monotonic() + SCENARIO_TIME_BUDGET
    while i < len(queue) and attempts < MAX_ATTEMPTS and time.monotonic() < deadline:
        variant, buyer_type = queue[i]
        i += 1
        payload = build_payload(company, code, tmpl, buyer_type, variant)

        res = _post(token, payload, URL_POST_SB)
        attempts += 1
        retries = 0
        while res["transient"] and retries < 2 and attempts < MAX_ATTEMPTS:  # FBR timeout / glitch
            time.sleep(3)
            res = _post(token, payload, URL_POST_SB)
            attempts += 1
            retries += 1

        logger.info("FBR sandbox %s attempt %s (%s) -> %s",
                    code, attempts, buyer_type, "Valid" if res["ok"] else res["error"])

        if res["ok"]:
            return {"code": code, "ok": True, "fatal": False, "invoice_no": res["invoice_no"], "error": ""}

        last_error = res["error"]
        if last_error not in errors_seen:
            errors_seen.append(last_error)
        if res["fatal"]:
            return {"code": code, "ok": False, "fatal": True, "invoice_no": "", "error": last_error}

        # 0052 "HS code does not match the sale type" -> try HS codes from the scenario's chapter (e.g. 2710).
        # Each candidate gets FBR's own description for it (FBR also checks the product description)
        # and a unit FBR allows for that HS code.
        if not hs_fixed and "0052" in last_error and tmpl.get("hs_prefix"):
            hs_fixed = True
            current = _clean(payload["items"][0]["hsCode"])
            pairs = [(c, d) for c, d in ref_hs_codes(token, tmpl["hs_prefix"], limit=300) if c != current]
            # codes whose FBR description names a well-known petroleum product go first
            pairs.sort(key=lambda cd: not any(w in cd[1].lower() for w in PETROLEUM_WORDS))
            for pos, (code_, desc_) in enumerate(pairs[:HS_TRY_LIMIT]):
                extra_fields = {"hsCode": code_}
                if desc_:
                    extra_fields["productDescription"] = desc_[:120]
                allowed_ = hs_allowed_uoms(token, code_)
                if allowed_:
                    extra_fields["uoM"] = allowed_[0]
                queue.insert(i + pos, (dict(variant, **extra_fields), buyer_type))
            hs_tried = [c for c, _ in pairs[:HS_TRY_LIMIT]]
            hs_left = [c for c, _ in pairs[HS_TRY_LIMIT:]]

        # 0046 "Rate not valid for this sale type" -> try the rates FBR lists for it (numbers re-fitted)
        if not rate_fixed and "0046" in last_error:
            rate_fixed = True
            item = dict(payload["items"][0])
            tried = _clean(item["rate"]).replace(" ", "").lower()
            rupee_style = bool(re.search(r"rs|rupee", tried))
            cands = [r["desc"] for r in valid_rates(token, _clean(item["saleType"]), _clean(payload["sellerProvince"]))
                     if r["desc"].replace(" ", "").lower() != tried]
            cands.sort(key=lambda d: (bool(re.search(r"rs|rupee", d, re.I)) != rupee_style))  # same style first
            for pos, desc in enumerate(cands[:4]):
                queue.insert(i + pos, (dict(variant, **_rate_variant(desc, item)), buyer_type))

        # 0078 "Item Sr. No. invalid/missing for this SRO" -> try a few serials FBR lists for that schedule
        if not serial_fixed and "0078" in last_error:
            serial_fixed = True
            item = payload["items"][0]
            info = sro_options(token, _clean(item["saleType"]), _clean(item["rate"]),
                               _clean(payload["sellerProvince"]), with_items=True)
            mine = [x for x in info.get("sro_schedules", [])
                    if x["desc"].lower() == _clean(item["sroScheduleNo"]).lower()]
            serials = [x for x in (mine[0]["items"] if mine else []) if x != _clean(item["sroItemSerialNo"])]
            serials.sort(key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else 0, x))  # plain numbers first
            for pos, serial in enumerate(serials[:3]):
                queue.insert(i + pos, (dict(variant, sroItemSerialNo=serial), buyer_type))

        # 0099 "UoM not allowed for this HS code" -> retry once with a unit FBR allows for it
        if not uom_fixed and "0099" in last_error:
            uom_fixed = True
            item = payload["items"][0]
            allowed = hs_allowed_uoms(token, item["hsCode"])
            if allowed and allowed[0] != item["uoM"]:
                queue.insert(i, (dict(variant, uoM=allowed[0]), buyer_type))

        # "Registration type does not match buyer's profile" -> try the other type once
        if not flipped and "registration type" in last_error.lower():
            flipped = True
            queue.extend((v, other_type) for v in variants)

    earlier = [e[:250] for e in errors_seen if e != last_error]
    if hs_tried and "0052" in last_error:
        last_error += " || HS codes tried: " + ", ".join(hs_tried)
        if hs_left:
            last_error += f" || {len(hs_left)} more HS codes exist in FBR's list (not tried): " + ", ".join(hs_left[:30])
    if earlier:
        last_error += " || Other errors seen on earlier attempts: " + " ;; ".join(earlier)
    return {"code": code, "ok": False, "fatal": False, "invoice_no": "", "error": last_error}


@login_required
def scenarioAutoRun(request):
    """POST only. Optional POST list `codes` = run only those scenarios."""
    back = request.META.get("HTTP_REFERER", "/fallback-url/")
    try:
        if request.method != "POST":
            messages.error(request, "Invalid request method!")
            return redirect(back)

        company = CompanyModel.objects.first()
        if not company or not _clean(company.sandbox_api):
            messages.error(request, "Please save the Sandbox API token in Company Profile first!")
            return redirect(back)

        pending = ScenarioModel.objects.filter(is_success=False)
        codes = request.POST.getlist("codes")
        if codes:
            pending = pending.filter(code__in=codes)
        pending = list(pending.order_by("code"))

        if not pending:
            messages.info(request, "No pending scenario found.")
            return redirect(back)

        done, failed = [], []
        for sc in pending:
            res = run_scenario(company, sc.code)
            if res["ok"]:
                ScenarioModel.objects.filter(id=sc.id).update(is_success=True)
                done.append(f"{sc.code} (FBR Inv# {res['invoice_no']})")
            else:
                failed.append(f"{sc.code}: {res['error']}")
                if res.get("fatal"):
                    break  # token / network problem: no point trying the rest

        if done:
            messages.success(
                request,
                "Scenario successful: " + ", ".join(done)
                + ". The status on the IRIS portal may take a few minutes to update.",
            )
        for line in failed:
            messages.error(request, f"FBR Error - {line}")

        return redirect(back)
    except Exception as exc:
        messages.error(request, f"Something went wrong! {exc}")
        return redirect(back)


def _pretty(data, filename=None):
    resp = JsonResponse(data, json_dumps_params={"indent": 2}, safe=False)
    if filename:
        resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


@login_required
def scenarioPayload(request, code):
    """Shows the exact JSON that is sent to FBR for one scenario (add ?download=1 to save it)."""
    company = CompanyModel.objects.first()
    tmpl = SCENARIOS.get(code)
    if company is None:
        return JsonResponse({"error": "Add the company profile first."}, status=400)
    if tmpl is None:
        return JsonResponse({"error": f"No payload template for {code}."}, status=404)
    payload = build_payload(company, code, tmpl, tmpl["buyer"]["type"], (tmpl.get("variants") or [{}])[0])
    return _pretty(payload, f"{code}.json" if request.GET.get("download") else None)


@login_required
def scenarioPayloadAll(request):
    """Downloads the JSON payload of every scenario in one file."""
    company = CompanyModel.objects.first()
    if company is None:
        return JsonResponse({"error": "Add the company profile first."}, status=400)
    data = {
        code: build_payload(company, code, tmpl, tmpl["buyer"]["type"], (tmpl.get("variants") or [{}])[0])
        for code, tmpl in SCENARIOS.items()
    }
    return _pretty(data, "fbr_scenario_payloads.json")


# ===========================================================================
# B) Real invoices (sandbox test invoices + live invoices)
# ===========================================================================
FIXED_VALUE_TYPES = {"3rd schedule goods", "cement /concrete block", "potassium chlorate", "cng sales"}


RUPEE_RATE_TYPES = {"cement /concrete block", "cng sales"}


def _is_rupee_type(sale_type):
    """Sale types taxed in rupees per unit (e.g. 'Rs.3'). For these the Tax Rate box holds the rupee amount."""
    return re.sub(r"\s+", " ", _clean(sale_type).lower()) in RUPEE_RATE_TYPES


POTASSIUM_RATE = "18% along with rupees 60 per kilogram"  # the only rate FBR lists for Potassium chlorate


def _is_potassium(sale_type):
    return re.sub(r"\s+", " ", _clean(sale_type).lower()).startswith("potassium chlorate")


def _is_fixed_type(sale_type):
    """Sale types where FBR needs the Retail price / fixed value (case and extra spaces do not matter)."""
    v = re.sub(r"\s+", " ", _clean(sale_type).lower())
    return v in FIXED_VALUE_TYPES or v.startswith("3rd schedule")


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _rate_text(raw):
    """18 / '18' / '18%' -> '18%'; 1.43 -> '1.43%'; 'Exempt' / 'Rs.3 per unit' stay as typed."""
    s = _clean(raw)
    if s == "":
        return "0%"
    try:
        f = float(s.rstrip("%"))
    except ValueError:
        return s
    return f"{int(f)}%" if f.is_integer() else f"{f}%"


def _digits_ok(value, lengths=(7, 13)):
    v = _clean(value)
    return v.isdigit() and len(v) in lengths


def _reg_type(value):
    return {"registered": "Registered", "unregistered": "Unregistered"}.get(_clean(value).lower(), "")


def _is_sandbox(is_test):
    mode = InvoiceModeModel.objects.first()
    return bool(is_test) or not (mode and mode.is_live)


def build_invoice_payload(invoice, sandbox):
    """
    Returns (payload, problems, items).
    `problems` = plain-English reasons FBR would reject this invoice; nothing is sent when it is not empty.
    """
    company, customer = invoice.company, invoice.customer
    items = list(invoice.items.all().order_by("id"))
    problems = []

    if not _digits_ok(company.company_ntn_cnic):
        problems.append("Company NTN/CNIC must be exactly 7 digits (NTN) or 13 digits (CNIC), digits only.")
    buyer_ntn = _clean(customer.company_ntn_cnic)
    if buyer_ntn and not _digits_ok(buyer_ntn, (7, 9, 13)):
        problems.append(f"Customer NTN/CNIC must be 7, 9 or 13 digits, digits only (found '{buyer_ntn}') (FBR error 0002).")
    buyer_type = _reg_type(customer.register_type)
    if not buyer_type:
        problems.append("Customer registration type must be Registered or Unregistered (FBR error 0053).")
    if buyer_type == "Registered" and not buyer_ntn:
        problems.append("A Registered customer needs an NTN/CNIC (FBR error 0009).")
    if buyer_ntn and buyer_ntn == _clean(company.company_ntn_cnic):
        problems.append("Buyer and seller NTN/CNIC are the same; FBR does not allow self-invoicing (error 0058).")
    if not items:
        problems.append("Invoice has no items.")

    rows = []
    for n, it in enumerate(items, start=1):
        sale_type = _clean(it.saleType)
        value_ex = _num(it.valueSalesExcludingST)
        if value_ex <= 0:
            problems.append(f"Item {n}: 'Value of sales excluding ST' must be greater than 0 (FBR error 0300).")
        if not sandbox:
            sample_text = (_clean(getattr(it, "product_description", "")), _clean(getattr(it, "product_code", "")))
            if re.match(r"^SN\d{3} sample item$", sample_text[0]) or re.match(r"^SN\d{3}-ITEM$", sample_text[1]):
                problems.append(f"Item {n} is scenario SAMPLE data ('{sample_text[0] or sample_text[1]}'). "
                                "Never send sample data to LIVE FBR - enter the real product details.")
        if not _clean(it.hs_code):
            problems.append(f"Item {n}: HS code is missing.")
        if not sale_type:
            problems.append(f"Item {n}: sale type is missing.")

        rate_txt = _rate_text(it.rate)
        rupee = _is_rupee_type(sale_type)
        potassium = _is_potassium(sale_type)
        amount = _num(it.rate)
        if potassium:
            # FBR lists a single rate for this sale type: 18% of the value + Rs.60 per kg
            rate_txt = POTASSIUM_RATE
            amount = 60.0
            expected = 0.18 * value_ex + 60 * _num(it.quantity)
            if abs(_num(it.salesTaxApplicable) - expected) > max(0.05, 0.005 * expected):
                problems.append(f"Item {n}: for '{sale_type}' the sales tax must be 18% of {value_ex:g} + Rs.60 x "
                                f"quantity = {expected:.2f} (found {_num(it.salesTaxApplicable):g}) (FBR error 0105).")
        elif rupee:
            rate_txt = f"Rs.{amount:g}"  # Tax Rate box = rupees per unit for cement / CNG; FBR's list says "Rs.3"
            if amount <= 0:
                problems.append(f"Item {n}: for '{sale_type}' enter the rupee amount per unit in 'Tax Rate' (e.g. 3 for Rs.3).")
            elif abs(_num(it.salesTaxApplicable) - amount * _num(it.quantity)) > 0.05:
                problems.append(f"Item {n}: for '{sale_type}' the sales tax must be Rs.{amount:g} x quantity "
                                f"= {amount * _num(it.quantity):g} (found {_num(it.salesTaxApplicable):g}) (FBR error 0105).")
        if sale_type.lower() == "exempt goods":
            rate_txt = "Exempt"  # the Tax Rate box only holds numbers (0); FBR's rate list calls it "Exempt"
        tax = _num(it.salesTaxApplicable)
        wh_pct = _num(it.salesTaxWithheldAtSource)
        if not (abs(wh_pct) < 0.0001 or abs(wh_pct - 100) < 0.0001):
            problems.append(f"Item {n}: 'Sales tax withheld at source' must be 0% or 100% (FBR error 0008).")
        if rate_txt == "5%" and value_ex > 20000:
            problems.append(f"Item {n}: rate 5% is not allowed when the value is above 20,000 (FBR error 0079).")
        if _is_fixed_type(sale_type) and not rupee and not potassium and _num(it.unit_price) <= 0:
            problems.append(f"Item {n}: '{sale_type}' needs the Retail price / fixed value (FBR error 0090).")
        if rate_txt.endswith("%") and not _is_fixed_type(sale_type):
            try:
                pct = float(rate_txt[:-1])
            except ValueError:
                pct = None
            if pct is not None and abs(tax - value_ex * pct / 100) > max(0.05, 0.005 * tax):
                problems.append(f"Item {n}: sales tax {tax:g} does not match {rate_txt} of {value_ex:g} "
                                f"(should be {value_ex * pct / 100:.2f}) (FBR error 0104).")

        extra = _num(it.extraTax)
        # The item form stores "withheld at source" as a percentage of the sales tax.
        withheld = _num(it.salesTaxWithheldAtSource) / 100 * _num(it.salesTaxApplicable)
        fixed = amount if (rupee or potassium) else (_num(it.unit_price) if _is_fixed_type(sale_type) else 0.0)
        description = (_clean(getattr(it, "product_description", ""))
                       or _clean(getattr(it, "product_code", "")) or "-")

        rows.append({
            "hsCode": _clean(it.hs_code),
            "productDescription": description,
            "rate": rate_txt,
            "uoM": _clean(it.uom),
            "quantity": _num(it.quantity),
            "totalValues": _num(it.totalValues),
            "valueSalesExcludingST": value_ex,
            "fixedNotifiedValueOrRetailPrice": fixed,
            "salesTaxApplicable": _num(it.salesTaxApplicable),
            "salesTaxWithheldAtSource": withheld,
            "extraTax": "" if extra == 0 else extra,  # FBR wants "" (not 0) for reduced-rate goods
            "furtherTax": _num(it.furtherTax),
            "sroScheduleNo": _clean(it.sroScheduleNo),
            "fedPayable": _num(it.fedPayable),
            "discount": _num(it.discount),
            "saleType": sale_type,
            "sroItemSerialNo": _clean(it.sroItemSerialNo),
        })

    try:
        invoice_date = invoice.invoiceDate.strftime("%Y-%m-%d")
    except Exception:
        invoice_date = str(invoice.invoiceDate)

    invoice_type = _clean(invoice.invoiceType) or "Sale Invoice"
    payload = {
        "invoiceType": invoice_type,
        "invoiceDate": invoice_date,
        "sellerNTNCNIC": _clean(company.company_ntn_cnic),
        "sellerBusinessName": _clean(company.company_name),
        "sellerProvince": _clean(company.province),
        "sellerAddress": _clean(company.address),
        "buyerNTNCNIC": buyer_ntn,
        "buyerBusinessName": _clean(customer.company_name),
        "buyerProvince": _clean(customer.province),
        "buyerAddress": _clean(customer.address),
        "buyerRegistrationType": buyer_type or _clean(customer.register_type),
        # FBR only needs a reference number on Debit/Credit notes (the original FBR invoice no.)
        "invoiceRefNo": "" if invoice_type == "Sale Invoice" else _clean(invoice.invoiceRefNo),
    }
    if sandbox:
        scenario = getattr(invoice, "scenarioId", None)
        if scenario is None:
            problems.append("Select a scenario for sandbox/test invoices.")
        else:
            payload["scenarioId"] = scenario.code
    payload["items"] = rows
    return payload, problems, items


def _dump_payload(payload):
    """Keep the last payload on disk (fbr_payload.txt in the project folder) for debugging."""
    try:
        with open(os.path.join(settings.BASE_DIR, "fbr_payload.txt"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def send_invoice_to_fbr(invoice, is_test):
    """Drop-in replacement for getFBRInvoice(). Returns {"status": "success"|"error", "errors": ...}."""
    try:
        if _clean(getattr(invoice, "fbrInvoiceNumber", "")):
            return {"status": "success", "errors": ""}  # already posted: never post twice

        sandbox = _is_sandbox(is_test)
        company = invoice.company
        token = _clean(company.sandbox_api if sandbox else company.live_api)
        if not token:
            which = "Sandbox" if sandbox else "Live"
            return {"status": "error", "errors": [f"{which} API token is missing in Company Profile."]}

        payload, problems, items = build_invoice_payload(invoice, sandbox)
        if problems:
            return {"status": "error", "errors": problems}
        _dump_payload(payload)

        # Live: ask FBR to validate first, so a bad invoice never gets posted.
        if not sandbox and VALIDATE_LIVE_FIRST:
            check = _post(token, payload, URL_VALIDATE_LIVE)
            if not check["ok"] and not check["transient"]:
                return {"status": "error", "errors": [_with_hints(token, payload, check["error"])]}

        post_url = URL_POST_SB if sandbox else URL_POST_LIVE
        res = _post(token, payload, post_url)
        if sandbox:  # sandbox glitches are safe to retry; live posts are NOT (possible duplicate)
            retries = 0
            while res["transient"] and retries < 2:
                time.sleep(3)
                res = _post(token, payload, post_url)
                retries += 1

        try:
            InvoiceLogModel.objects.create(invoice=invoice, log_message=res["raw"] or res["error"])
        except Exception:
            pass

        if res["ok"]:
            invoice.fbrInvoiceNumber = res["invoice_no"]
            invoice.save()
            for idx, item in enumerate(items):
                if idx < len(res["item_numbers"]):
                    item.fbrInvoiceNumber = res["item_numbers"][idx]
                    item.save()
            if sandbox and getattr(invoice, "scenarioId_id", None):
                ScenarioModel.objects.filter(id=invoice.scenarioId_id).update(is_success=True)
            return {"status": "success", "errors": ""}

        if res["transient"] and not sandbox:
            return {"status": "error", "errors": [
                "FBR did not confirm this invoice (timeout or unreadable reply). It may or may not have "
                "been posted - check the IRIS portal before trying again. " + res["error"]]}

        invoice.fbr_integrate = False
        invoice.save()
        return {"status": "error", "errors": [_with_hints(token, payload, res["error"])]}
    except Exception as exc:
        return {"status": "error", "errors": [f"exception error: {exc}"]}


@login_required
def invoicePayloadPreview(request, id):
    """Shows the payload of an invoice exactly as it would be sent. Sends NOTHING to FBR."""
    try:
        invoice = InvoiceModel.objects.get(id=id)
        sandbox = _is_sandbox(invoice.is_test)
        payload, problems, _ = build_invoice_payload(invoice, sandbox)
        return _pretty({
            "environment": "sandbox" if sandbox else "live",
            "problems_that_would_block_sending": problems,
            "payload": payload,
        })
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=500)


@login_required
def invoiceValidateFBR(request, id):
    """Asks FBR to validate the invoice. Nothing is posted and no FBR invoice number is created."""
    back = request.META.get("HTTP_REFERER", "/fallback-url/")
    try:
        invoice = InvoiceModel.objects.get(id=id)
        sandbox = _is_sandbox(invoice.is_test)
        company = invoice.company
        token = _clean(company.sandbox_api if sandbox else company.live_api)
        if not token:
            messages.error(request, "API token is missing in Company Profile.")
            return redirect(back)

        payload, problems, _ = build_invoice_payload(invoice, sandbox)
        if problems:
            messages.error(request, "Fix before sending: " + " | ".join(problems))
            return redirect(back)

        res = _post(token, payload, URL_VALIDATE_SB if sandbox else URL_VALIDATE_LIVE)
        if res["ok"]:
            messages.success(request, "FBR says this invoice is VALID. (Nothing was posted.)")
        else:
            messages.error(request, f"FBR validation failed - {_with_hints(token, payload, res['error'])}")
        return redirect(back)
    except Exception as exc:
        messages.error(request, f"Something went wrong! {exc}")
        return redirect(back)


@login_required
def hsUomLookup(request):
    """Open /hs-uom?hs_code=5904.9000 to see which units FBR allows for that HS code."""
    hs = _clean(request.GET.get("hs_code"))
    if not hs:
        return JsonResponse({"error": "Use it like this: ?hs_code=5904.9000"}, status=400)
    company = CompanyModel.objects.first()
    mode = InvoiceModeModel.objects.first()
    live = bool(mode and mode.is_live)
    token = _clean(company.live_api if live else company.sandbox_api) if company else ""
    if not token:
        return JsonResponse({"error": "API token is missing in Company Profile."}, status=400)
    annexure = _clean(request.GET.get("annexure_id")) or HS_UOM_ANNEXURE_ID
    allowed = hs_allowed_uoms(token, hs, annexure)
    return _pretty({
        "hs_code": hs,
        "environment": "live" if live else "sandbox",
        "allowed_uom": allowed,
        "note": "" if allowed else "FBR returned no units (unknown HS code, other annexure_id, or token problem).",
    })


# ===========================================================================
# Create-Test-Invoice form helper: fills the item row from the chosen scenario
# ===========================================================================
def scenario_form_values(code):
    """Form-friendly values (same numbers as the scenario's payload). None if there is no template."""
    tmpl = SCENARIOS.get(code)
    if tmpl is None:
        return None
    item = dict(tmpl["item"])
    item.update((tmpl.get("variants") or [{}])[0])

    qty = _num(item["quantity"])
    qty = qty if qty > 0 else 1
    value = _num(item["valueSalesExcludingST"])
    tax = _num(item["salesTaxApplicable"])
    fixed = _num(item["fixedNotifiedValueOrRetailPrice"])
    sale_type = _clean(item["saleType"]).lower()

    rate_text = _clean(item["rate"])
    try:
        rate_num = float(rate_text.rstrip("%"))
    except ValueError:
        rate_num = None  # text rates such as "Exempt" do not fit the numeric Tax Rate box

    withheld = _num(item["salesTaxWithheldAtSource"])
    # The form stores withheld tax as a percentage; FBR wants it to be 0 or equal to the sales tax.
    withheld_pct = 100 if tax > 0 and abs(withheld - tax) < 0.005 else 0

    notes = []
    m = re.search(r"rs\.?\s*([\d.]+)", rate_text, re.I)
    if _is_rupee_type(sale_type) and m:
        rate_num = float(m.group(1))
        notes.append(f"{item['saleType']}: the Tax Rate box holds RUPEES per unit here (Rs.{rate_num:g}), not a percentage. "
                     f"Sales tax = {rate_num:g} x quantity.")
    if _is_potassium(sale_type):
        rate_num = 18
        notes.append("Potassium chlorate: sales tax = 18% of the value + Rs.60 per kg. The system sends FBR's only rate for it "
                     f"('{POTASSIUM_RATE}'); leave Tax Rate at 18.")
    if rate_text.lower() == "exempt":
        rate_num = 0  # keep the box at 0; the system sends "Exempt" to FBR for the Exempt goods sale type
        notes.append("Exempt goods: leave Tax Rate at 0. The system sends the rate to FBR as 'Exempt'.")
    if rate_num is None:
        notes.append(f"This scenario's rate is text ('{rate_text}'), but the Tax Rate box only accepts numbers. "
                     "Use the Run Test button on the Scenarios page for this scenario.")
    if code in ("SN026", "SN027", "SN028"):
        notes.append("FBR: scenarios 26, 27 and 28 work only if the seller is registered as a retailer in the sales tax profile.")

    return {
        "code": code,
        "buyer_type": tmpl["buyer"]["type"],
        "rate_text": rate_text,
        "notes": notes,
        "fields": {
            "product_code": f"{code}-ITEM",
            "product_description": f"{code} sample item",
            "hs_code": _clean(item["hsCode"]),
            "uom": _clean(item["uoM"]),
            "unit_price": fixed if _is_fixed_type(sale_type) else round(value / qty, 4),
            "rate": rate_num,
            "quantity": qty,
            "totalValues": _num(item["totalValues"]) or round(value + tax, 2),
            "valueSalesExcludingST": value,
            "salesTaxApplicable": tax,
            "salesTaxWithheldAtSource": withheld_pct,
            "extraTax": _num(item["extraTax"]),
            "furtherTax": _num(item["furtherTax"]),
            "sroScheduleNo": _clean(item["sroScheduleNo"]),
            "fedPayable": _num(item["fedPayable"]),
            "discount": _num(item["discount"]),
            "sroItemSerialNo": _clean(item["sroItemSerialNo"]),
        },
    }


@login_required
def scenarioFormSample(request, code):
    """JSON used by the Create Test Invoice page to fill the item fields for a scenario."""
    data = scenario_form_values(code)
    if data is None:
        return JsonResponse({"error": f"No sample values for {code}. Enter the item by hand."}, status=404)
    return JsonResponse(data)


@login_required
def sroLookup(request):
    """
    /sro-lookup?sale_type=Goods at Reduced Rate&rate=1%   (add &items=1 to also list item serial numbers)
    Shows the SRO/Schedule numbers FBR accepts for a sale type + rate.
    """
    sale_type = _clean(request.GET.get("sale_type"))
    rate = _clean(request.GET.get("rate"))
    if not sale_type or not rate:
        return JsonResponse({"error": "Use it like this: ?sale_type=Goods at Reduced Rate&rate=1%"}, status=400)
    company = CompanyModel.objects.first()
    mode = InvoiceModeModel.objects.first()
    live = bool(mode and mode.is_live)
    token = _clean(company.live_api if live else company.sandbox_api) if company else ""
    if not token:
        return JsonResponse({"error": "API token is missing in Company Profile."}, status=400)
    data = sro_options(token, sale_type, rate, _clean(company.province), with_items=bool(request.GET.get("items")))
    data["environment"] = "live" if live else "sandbox"
    return _pretty(data)


@login_required
def hsList(request):
    """/hs-list?prefix=2710  -> every HS code (and description) FBR lists that starts with the prefix."""
    prefix = _clean(request.GET.get("prefix"))
    if not prefix:
        return JsonResponse({"error": "Use it like this: ?prefix=2710"}, status=400)
    company = CompanyModel.objects.first()
    mode = InvoiceModeModel.objects.first()
    live = bool(mode and mode.is_live)
    token = _clean(company.live_api if live else company.sandbox_api) if company else ""
    if not token:
        return JsonResponse({"error": "API token is missing in Company Profile."}, status=400)
    pairs = ref_hs_codes(token, prefix, limit=1000)
    return _pretty({"prefix": prefix, "count": len(pairs),
                    "hs_codes": [{"hs_code": c, "description": d} for c, d in pairs]})