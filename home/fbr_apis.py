import requests
import json
from .models import HScodeModel, MeasurmentUnitModel, CompanyModel


def loadHs_code():
    data = CompanyModel.objects.first()
    if data:
        token = data.sandbox_api.strip()
        url = "https://gw.fbr.gov.pk/pdi/v1/itemdesccode"
        headers = {
            "Authorization": f"Bearer {token}",
        }
        payload = {}
        response = requests.request("GET", url, headers=headers, data=payload)
        try:
            json_response = json.loads(response.text)
            for item in json_response:
                hs_code = item.get("hS_CODE")
                description = item.get("description")
                _, ins = HScodeModel.objects.get_or_create(
                    hs_code=hs_code, defaults={"code_description": description}
                )
                if ins:
                    print(f"hs code: {hs_code} created \n")
                else:
                    print(f"hs code: {hs_code} exists \n")
            print("operation complete")
        except Exception as e:
            print(str(e))
    else:
        print('company bearer token is not found')



def loadMeasurmentUnits():
    data = CompanyModel.objects.first()
    if data:
        token = data.sandbox_api.strip()
        url = "https://gw.fbr.gov.pk/pdi/v1/uom"
        headers = {
            "Authorization": f"Bearer {token}",
        }
        payload = {}
        response = requests.request("GET", url, headers=headers, data=payload)
        json_response = json.loads(response.text)
        try:
            for item in json_response:
                uoM_ID = item.get("uoM_ID") #not used by now
                description = item.get("description")
                _, ins = MeasurmentUnitModel.objects.get_or_create(
                    code=description, defaults={"name": description}
                )
                if ins:
                    print(f"uOM: {description} created")
                else:
                    print(f"uOM: {description} exists")
        except Exception as e:
            print(str(e))
    else:
        print('company bearer token is not found')

