from django.shortcuts import redirect
from home.models import CompanyModel
import os
import json
from datetime import datetime
from django.http import HttpResponseForbidden
from django.contrib import messages

# myapp/middleware/license_check.py
import os, json
from datetime import datetime
from django.http import HttpResponseForbidden
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from license.license_public_key import PUBLIC_KEY

class IsCompanyFound:
    def __init__(self, get_response):
        self.get_response = get_response
        

    def __call__(self, request):
        # add middleware for certain paths
        if  request.path.startswith('/dashboard'):
            if CompanyModel.objects.all().count() > 0:
                return self.get_response(request)
            else:
                return redirect('home.add-company')
        else:
            return self.get_response(request)

LICENSE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "media", "license.key"))

class LicenseCheckMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response    
        # Load public key once at startup
        self.public_key = serialization.load_pem_public_key(PUBLIC_KEY)

    def __call__(self, request):
        # Check license before processing request
        if request.path.startswith('/upload-licence') or request.path == '/' or request.path.startswith('/add-company'):
            return self.get_response(request)
    
        if not os.path.exists(LICENSE_FILE):
            return redirect('home.upload-license')
        
        try:
            with open(LICENSE_FILE, "r") as f:
                license_data = json.load(f)
            
            company_ntn_cnic = license_data.get("company_ntn_cnic")
            issue = license_data.get("issue")
            expiry = license_data.get("expiry")
            chksignature = license_data.get("signature")

            if not company_ntn_cnic or not issue or not expiry or not chksignature:
                messages.error(request, "Invalid license file structure.")
                return redirect('home.upload-license')

            # Extract and remove signature
            signature = bytes.fromhex(license_data.pop("signature"))
            message = json.dumps(license_data, sort_keys=True).encode()

            # Verify signature
            self.public_key.verify(
                signature,
                message,
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            
            try:
                company = CompanyModel.objects.first()
                if company:
                    if company.company_ntn_cnic != company_ntn_cnic:
                        messages.error(request, "Company information does not match the license.")
                        return redirect('home.upload-license')
                    
                    expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
                    if expiry_date < datetime.today().date():
                        return redirect('home.upload-license')
                else:
                    messages.error(request, "Company information is not exists.")
                    return redirect('home.upload-license')

            except (ValueError, TypeError):
                messages.error(request, "License expiry date is invalid or missing.")
                return redirect('home.upload-license')
            
        except Exception as e:
            messages.error(request, f"Invalid license file: {str(e)}")
            return redirect('home.upload-license')

        # If valid, continue as normal
        response = self.get_response(request)
        return response
