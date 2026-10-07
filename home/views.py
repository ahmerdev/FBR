from django.shortcuts import render, HttpResponse, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import authenticate, login, logout
from .models import *
from django.contrib.auth.models import User
from django.contrib import messages
from .form import *
from .scenario import scenario_list
from .scenario_runner import (
    scenarioAutoRun,
    scenarioPayload,
    scenarioPayloadAll,
    invoicePayloadPreview,
    invoiceValidateFBR,
    send_invoice_to_fbr,
    hsUomLookup,
    scenarioFormSample,
    sroLookup,
    hsList,
)
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.db import transaction
from datetime import date, datetime
import requests
import json
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
import calendar
from collections import OrderedDict
from django.template.loader import get_template
from xhtml2pdf import pisa
from io import BytesIO
import qrcode
from django.core.files.base import ContentFile
import base64
import openpyxl
import os
import csv
import io
from .utils import create_license_file
import json, os
from django.conf import settings

# Create your views here.


def uploadLicense(request):
    try:
        if request.method == "POST":
            if "license_file" not in request.FILES:
                messages.error(request, "No file uploaded!")
                return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))
            license_file = request.FILES["license_file"]
            if not license_file.name.endswith(".key"):
                messages.error(request, "Invalid file type! Please upload valid file.")
                return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))
            # Save the uploaded file to the desired location
            license_path = os.path.join(
                os.path.dirname(__file__), "..", "media/license.key"
            )
            with open(license_path, "wb+") as destination:
                for chunk in license_file.chunks():
                    destination.write(chunk)
            messages.success(request, "License uploaded successfully!")
            return redirect("home.dashboard")
        
        LICENSE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "media", "license.key"))
        if not os.path.exists(LICENSE_FILE):
            data = {}
            is_exists = False
            is_expired = True
        else:
            is_exists = True
            with open(LICENSE_FILE, "r") as f:
                license_data = json.load(f)
            license_data.pop("signature")
            data = license_data
            expiry_date = datetime.strptime(data.get("expiry"), "%Y-%m-%d").date()
            is_expired = expiry_date < date.today()
        return render(request, "uploadLicense.html" , {"is_expired":is_expired, "is_exists":is_exists , "data":data})
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


def customLogin(request):
    try:
        if request.method == "POST":
            form = AuthenticationForm(request, data=request.POST)
            if form.is_valid():
                username = form.cleaned_data.get("username")
                password = form.cleaned_data.get("password")
                user = authenticate(request, username=username, password=password)
                if (
                    user is not None and user.is_staff
                ):  # Ensure the user is a staff member
                    login(request, user)
                    return redirect("home.dashboard")
            else:
                return render(request, "custom-login.html", {"form": form})
        form = AuthenticationForm(request)
        return render(request, "custom-login.html", {"form": form})
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


def add_months(year, month, delta):
    total = year * 12 + (month - 1) + delta
    new_year = total // 12
    new_month = (total % 12) + 1
    return new_year, new_month


@login_required
def customDashboard(request):
    try:
        i_mode = InvoiceModeModel.objects.first()
        if not i_mode:
            i_mode = InvoiceModeModel.objects.create(is_live=False)
        # Get today's date
        today = timezone.localdate()  # safe for timezone-aware projects
        # start 11 months before current month so we get 12 months including current
        start_year, start_month = add_months(today.year, today.month, -11)
        start_date = date(start_year, start_month, 1)
        months = []
        for i in range(12):
            y, m = add_months(start_year, start_month, i)
            months.append((y, m))

        month_counts = OrderedDict((calendar.month_abbr[m], 0) for (y, m) in months)

        # query DB for counts grouped by month
        month_data = (
            InvoiceModel.objects.filter(
                invoiceDate__gte=start_date, is_test=not i_mode.is_live
            )
            .annotate(month=TruncMonth("invoiceDate"))
            .values("month")
            .annotate(count=Count("id"))
            .order_by("month")
        )

        # fill counts
        for entry in month_data:
            label = calendar.month_abbr[entry["month"].month]
            month_counts[label] = entry["count"]

        counts = InvoiceModel.objects.filter(is_test=not i_mode.is_live).aggregate(
            total_invoices=Count("id"),
            fbr_true=Count("id", filter=Q(fbr_integrate=True)),
            fbr_false=Count("id", filter=Q(fbr_integrate=False)),
        )
        customer = CustomerModel.objects.all().annotate(count=Count("id"))
        item = ItemModel.objects.all().annotate(count=Count("id"))
        sena = ScenarioModel.objects.all().annotate(count=Count("id"))
        return render(
            request,
            "dashboard.html",
            {
                "counts": counts,
                "sena": sena,
                "item": item,
                "customer": customer,
                "month_counts": json.dumps(month_counts),
            },
        )
    except Exception as e:

        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def addCompany(request):
    try:
        if CompanyModel.objects.filter(id=1).exists():
            return redirect("home.dashboard")

        if request.method == "POST":
            values = {
                key: value.strip()
                for key, value in request.POST.items()
                if key != "csrfmiddlewaretoken"
            }
            if "company_logo" in request.FILES:
                values["company_logo"] = request.FILES["company_logo"]
            CompanyModel.objects.create(**values)
            return redirect("home.dashboard")
        return render(request, "addCompany.html")
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def companyProfile(request):
    try:
        data = CompanyModel.objects.first()
        if request.method == "POST":
            if request.user.is_superuser:
                for key, value in request.POST.items():
                    if key != "csrfmiddlewaretoken":
                        setattr(data, key, value.strip())
                if "company_logo" in request.FILES:
                    data.company_logo = request.FILES["company_logo"]
                data.save()
                messages.success(request, "Data saved successfully!")
            else:
                messages.error(request, "Unathorized access!")
            return redirect("home.company-profile")
        return render(request, "companyProfile.html", {"data": data})
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def myProfile(request):
    try:
        data = request.user
        if request.method == "POST":
            user = data
            first_name = request.POST.get("first_name")
            last_name = request.POST.get("last_name")
            get_username = request.POST.get("username")
            password = request.POST.get("password")
            if user:
                user.first_name = first_name
                user.last_name = last_name
                user.username = get_username
                user.email = get_username
                if password:
                    user.set_password(password)
                user.save()
                messages.success(request, "Data saved successfully!")
            else:
                messages.error(request, "No user found for update!")
            return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))

        return render(request, "myProfile.html", {"data": data})
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def users(request):
    try:
        datalist = User.objects.all()
        return render(request, "users.html", {"datalist": datalist})
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def addEditUsers(request, username=None):
    try:
        if request.method == "POST":
            first_name = request.POST.get("first_name")
            last_name = request.POST.get("last_name")
            get_username = request.POST.get("username")
            password = request.POST.get("password")
            is_active = request.POST.get("is_active")
            try:
                uid = int(request.POST.get("uid"))
            except Exception as e:
                messages.error(request, "Invalid Data Found!")
                return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))

            if not request.user.is_superuser:
                if uid == 0 or request.user.id != uid:
                    messages.error(request, "Unauthorized request!")
                    return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))

            if uid == 0:
                User.objects.create_user(
                    first_name=first_name,
                    last_name=last_name,
                    username=get_username,
                    email=get_username,
                    password=password,
                    is_active=is_active,
                    is_staff=True,
                )
                messages.success(request, "Data saved successfully!")

            else:
                user = User.objects.get(id=uid)
                if user:
                    user.first_name = first_name
                    user.last_name = last_name
                    user.username = get_username
                    user.email = get_username
                    if password:
                        user.set_password(password)
                    user.is_active = is_active
                    user.save()
                    messages.success(request, "Data saved successfully!")
                else:
                    messages.error(request, "No user found for update!")
            return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))
        data = {}
        if username is not None:
            data = User.objects.get(username=username)
        return render(request, "addEditUsers.html", {"data": data})
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def deleteUsers(request, username):
    try:
        if request.user.is_superuser:
            u = User.objects.get(username=username)
            if u.is_superuser:
                messages.error(request, "Unauthorized request!")
            else:
                u.delete()
                messages.success(request, "Data deleted successfully!")
        else:
            messages.error(request, "Unauthorized request!")
        return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def checkUsername(request):
    try:
        username = request.GET.get("username")
        uid = request.GET.get("uid")
        if username:
            return HttpResponse(
                User.objects.exclude(id=uid).filter(username=username).exists()
            )
        else:
            return HttpResponse(False)
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def customers(request):
    try:
        datalist = CustomerModel.objects.all().order_by("-id")
        return render(request, "customers.html", {"datalist": datalist})
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def addEditCustomers(request, id=None):
    try:
        data = {} if id is None else CustomerModel.objects.get(id=id)
        if request.method == "POST":
            form = (
                CustomerForm(request.POST)
                if id is None
                else CustomerForm(request.POST, instance=data)
            )
            if form.is_valid():
                form.save()
                messages.success(request, "Data saved successfully!")
                return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))
            else:
                messages.error(request, "Something went wrong!")
        else:
            form = CustomerForm() if id is None else CustomerForm(instance=data)
        return render(request, "addEditCustomers.html", {"form": form})
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def deleteCustomers(request, id):
    try:
        cd = CustomerModel.objects.filter(id=id)
        if cd:
            cd.first().delete()
            messages.success(request, "Data deleted successfully!")
        else:
            messages.error(request, "No data found!")
        return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def FBRHscode(request):
    try:
        # opening and appending data from file static/fbr-hs-code.json
        with open("static/fbr-hs-code.json", "r") as file:
            json_data = json.load(file)
        return render(request, "FBRHscode.html", {"datalist": json_data})
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def hsCodes(request):
    try:
        obj_list = HScodeModel.objects.all()
        # paginator = Paginator(obj_list, 10)  # pagination of 10 items per record
        # pg_no = request.GET.get("page")
        # datalist = paginator.get_page(pg_no)
        return render(request, "hs-code.html", {"datalist": obj_list})
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def AddEdithsCodes(request, hs_code=None):
    try:
        data = {} if hs_code is None else HScodeModel.objects.get(hs_code=hs_code)
        if request.method == "POST":
            form = (
                HScodeForm(request.POST)
                if hs_code is None
                else HScodeForm(request.POST, instance=data)
            )
            if form.is_valid():
                form.save()
                messages.success(request, "Data saved successfully!")
                return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))
            else:
                messages.error(request, "Something went wrong!")
        else:
            form = HScodeForm() if hs_code is None else HScodeForm(instance=data)
        return render(request, "AddEdithsCodes.html", {"form": form})
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def deletehsCodes(request, hs_code=None):
    try:
        data = HScodeModel.objects.filter(hs_code=hs_code)
        if data:
            data.delete()
            messages.success(request, "Data delete successfully!")
        else:
            messages.error(request, "No record found")
        return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def listItems(request):
    try:
        datalist = ItemModel.objects.all().order_by("-id")
        return render(request, "listItem.html", {"datalist": datalist})
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def addEditItems(request, id=None):
    try:
        data = {} if id is None else ItemModel.objects.get(id=id)
        if request.method == "POST":
            form = (
                ItemsForm(request.POST)
                if id is None
                else ItemsForm(request.POST, instance=data)
            )
            if form.is_valid():
                form.save()
                messages.success(request, "Data saved successfully!")
                return redirect(request.META.get("HTTP_REFERER", "/fallback_url/"))
            else:
                messages.error(request, "Something went wrong!")
        else:
            form = ItemsForm() if id is None else ItemsForm(instance=data)

        return render(request, "addEditItems.html", {"form": form})
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def deleteItems(request, id=None):
    try:
        data = ItemModel.objects.filter(id=id)
        if data:
            data.delete()
            messages.success(request, "Data delete successfully!")
        else:
            messages.error(request, "No record found")
        return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def scenarioIndex(request):
    try:
        if request.method == "POST":
            code_list = request.POST.getlist("scenario_code")
            if code_list:
                for scenario in scenario_list:
                    if (scenario.code in code_list and not ScenarioModel.objects.filter(code=scenario.code).exists()):
                        ScenarioModel.objects.create(
                            code=scenario.code,
                            description=scenario.description,
                            sale_type=scenario.sale_type,
                        )
                messages.success(request, "Scenario has been added successfully!")
            else:
                messages.error(request, "No Scenario selected!")
            return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))
        datalist = ScenarioModel.objects.all()
        default_code = list(datalist.values_list("code", flat=True))
        return render(
            request,
            "scenarioIndex.html",
            {
                "scenario_datalist": scenario_list,
                "datalist": datalist,
                "default_code": default_code,
            },
        )
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def scenarioDelete(request, code):
    try:
        scenario = ScenarioModel.objects.get(code=code)
        if scenario:
            if scenario.is_success:
                messages.error(request, "Scenario can not be deleted!")
                return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))
            else:
                scenario.delete()
                messages.error(request, "Data deleted successfully!")
        else:
            messages.error(request, "No record found")

        return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def measurmentUnits(request):
    try:
        datalist = MeasurmentUnitModel.objects.all().order_by("-id")
        return render(request, "measurmentUnits.html", {"datalist": datalist})
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def measurmentUnitsAddEdit(request, id=None):
    try:
        data = {} if id is None else MeasurmentUnitModel.objects.get(id=id)
        if request.method == "POST":
            form = (
                MeasurmentUnitForm(request.POST)
                if id is None
                else MeasurmentUnitForm(request.POST, instance=data)
            )
            if form.is_valid():
                form.save()
                messages.success(request, "Data saved successfully!")
                return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))
            else:
                messages.error(request, "Something went wrong!")
        else:
            form = (
                MeasurmentUnitForm()
                if id is None
                else MeasurmentUnitForm(instance=data)
            )
        return render(request, "measurmentUnitsAddEdit.html", {"form": form})
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def measurmentUnitsDelete(request, id=None):
    try:
        data = MeasurmentUnitModel.objects.get(id=id)
        if data:
            data.delete()
            messages.success(request, "Data deleted successfully!")
        else:
            messages.error(request, "No Data found!")
        return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def InvoicesList(request, type=None):
    try:
        i_mode = InvoiceModeModel.objects.first()
        if not i_mode:
            i_mode = InvoiceModeModel.objects.create(is_live=False)
        tab = "a"
        if i_mode.is_live:
            datalist = InvoiceModel.objects.filter(is_test=False).order_by("-id")
        else:
            datalist = InvoiceModel.objects.filter(is_test=True).order_by("-id")

        title = "All Invoices"
        if type:
            if type == "integrate-pending":
                tab = "p"
                title = "FBR Integrate Pending Invoices"
                datalist = datalist.filter(fbr_integrate=False)
            elif type == "integrated":
                tab = "i"
                title = "FBR Integrated Invoices"
                datalist = datalist.filter(fbr_integrate=True)
            else:
                messages.error(request, "Invalid type provided!")

        if request.GET.get("filter"):
            fromDate = request.GET.get("fromDate")
            toDate = request.GET.get("toDate")
            type = request.GET.get("type")
            # filter the invoice model for the invoiceDate ranging between fromDate and toDate including both and also type for fbr_integrate
            if fromDate and toDate:
                datalist = datalist.filter(invoiceDate__range=[fromDate, toDate])
            if type:
                if type == "integrated":
                    datalist = datalist.filter(fbr_integrate=True)
                elif type == "integrate-pending":
                    datalist = datalist.filter(fbr_integrate=False)
            tab = "f"
            title = "Filtered Invoices"

        return render(
            request,
            "invoices.html",
            {"i_mode": i_mode, "datalist": datalist, "title": title, "tab": tab},
        )
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def viewInvoices(request, id):
    try:
        i_mode = InvoiceModeModel.objects.first()
        if not i_mode:
            i_mode = InvoiceModeModel.objects.create(is_live=False)
        data = InvoiceModel.objects.get(id=id)
        return render(request, "viewInvoices.html", {"i_mode": i_mode, "data": data})
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def printInvoices(request, id):
    try:

        data = InvoiceModel.objects.get(id=id)
        company = CompanyModel.objects.first()
        if company and company.company_logo:
            company_logo_url = request.build_absolute_uri(company.company_logo.url)
        else:
            company_logo_url = ""
        fbrLogo = request.build_absolute_uri("/static/logo/fb_logo.png")
        total = data.items.aggregate(total_sum=Sum("totalValues"))["total_sum"] or 0
        rate = (
            data.items.aggregate(total_rate=Sum("salesTaxApplicable"))["total_rate"]
            or 0
        )
        valueSalesExcludingST = (
            data.items.aggregate(total_qty=Sum("valueSalesExcludingST"))["total_qty"]
            or 0
        )
        qr_code_base64 = ""
        if data.fbrInvoiceNumber:
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(str(data.fbrInvoiceNumber))
            qr.make(fit=True)
            img = qr.make_image(fill="black", back_color="white")
            buffer = BytesIO()
            img.save(buffer, format="PNG")
            qr_code_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
            buffer.close()
        template = get_template("printInvoice.html")
        html = template.render(
            {
                "data": data,
                "company": company,
                "company_logo_url": company_logo_url,
                "total": total,
                "rate": rate,
                "valueSalesExcludingST": valueSalesExcludingST,
                "qr_code_base64": qr_code_base64,
                "fbrLogo": fbrLogo,
            }
        )

        response = HttpResponse(content_type="application/pdf")
        response["Content-Disposition"] = (
            f"inline; filename=invoice {data.invoiceRefNo}.pdf"
        )

        pisa_status = pisa.CreatePDF(html, dest=response, encoding="utf-8")

        if pisa_status.err:
            return HttpResponse("Error rendering PDF", status=500)
        return response
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def editInvoices(request, id):
    try:
        i_mode = InvoiceModeModel.objects.first()
        if not i_mode:
            messages.error(request, "Unathorized access!")
            return redirect("home.invoices")
        data = InvoiceModel.objects.get(id=id)
        if data.fbr_integrate == True:
            return redirect("home.invoices.view", id=data.id)

        if request.method == "POST":
            customer = request.POST.get("customer")
            invoiceRefNo = request.POST.get("invoiceRefNo")
            fbr_integrate = request.POST.get("fbr_integrate")
            scenarioId = request.POST.get("scenarioId", None)

            product_code=request.POST.getlist("product_code")
            product_description=request.POST.getlist("product_description")
            hs_code=request.POST.getlist("hs_code")
            uom=request.POST.getlist("uom")
            unit_price = request.POST.getlist("unit_price")

            rate = request.POST.getlist("rate")
            quantity = request.POST.getlist("quantity")
            totalValues = request.POST.getlist("totalValues")
            valueSalesExcludingST = request.POST.getlist("valueSalesExcludingST")
            salesTaxApplicable = request.POST.getlist("salesTaxApplicable")
            salesTaxWithheldAtSource = request.POST.getlist("salesTaxWithheldAtSource")
            sroScheduleNo = request.POST.getlist("sroScheduleNo")
            sroItemSerialNo = request.POST.getlist("sroItemSerialNo")
            furtherTax = request.POST.getlist("furtherTax")
            discount = request.POST.getlist("discount")
            fedPayable = request.POST.getlist("fedPayable")
            saleType = request.POST.getlist("saleType")
            extraTax = request.POST.getlist("extraTax")
            in_it_id = request.POST.getlist("in_it_id")

            invoiceDate = request.POST.get("invoiceDate", date.today())
            with transaction.atomic():
                data.invoiceRefNo = invoiceRefNo
                data.customer = CustomerModel.objects.get(id=customer)
                data.company = CompanyModel.objects.first()
                data.invoiceDate = invoiceDate
                data.fbr_integrate = fbr_integrate
                data.scenarioId_id = scenarioId
                data.user = request.user
                data.save()

                for i, hs in enumerate(hs_code):
                    itemid = in_it_id[i] if i < len(in_it_id) else None
                    if itemid:
                        InvoiceItemModel.objects.filter(id=itemid).update(
                            invoice=data,
                            product_code = product_code[i],
                            product_description = product_description[i],
                            hs_code = hs,
                            uom = uom[i],
                            unit_price = unit_price[i],
                            rate=rate[i],
                            quantity=quantity[i],
                            totalValues=totalValues[i],
                            valueSalesExcludingST=valueSalesExcludingST[i],
                            salesTaxApplicable=salesTaxApplicable[i],
                            salesTaxWithheldAtSource=salesTaxWithheldAtSource[i],
                            sroScheduleNo=sroScheduleNo[i],
                            sroItemSerialNo=sroItemSerialNo[i],
                            furtherTax=furtherTax[i],
                            discount=discount[i],
                            fedPayable=fedPayable[i],
                            saleType=saleType[i],
                            extraTax=extraTax[i],
                        )
                    else:
                        InvoiceItemModel.objects.create(
                            invoice=data,
                            product_code = product_code[i],
                            product_description = product_description[i],
                            hs_code = hs,
                            uom = uom[i],
                            unit_price = unit_price[i],
                            rate=rate[i],
                            quantity=quantity[i],
                            totalValues=totalValues[i],
                            valueSalesExcludingST=valueSalesExcludingST[i],
                            salesTaxApplicable=salesTaxApplicable[i],
                            salesTaxWithheldAtSource=salesTaxWithheldAtSource[i],
                            sroScheduleNo=sroScheduleNo[i],
                            sroItemSerialNo=sroItemSerialNo[i],
                            furtherTax=furtherTax[i],
                            discount=discount[i],
                            fedPayable=fedPayable[i],
                            saleType=saleType[i],
                            extraTax=extraTax[i],
                        )

            if int(data.fbr_integrate) == 1:
                # Call FBR API to create invoice
                fbrResponse = getFBRInvoice(data, is_test=False)
                if fbrResponse.get("status") == "success":
                    messages.success(request, "Invoice update successfully!")
                else:
                    data.fbr_integrate = False
                    data.save()
                    errors = fbrResponse.get("errors", [])
                    messages.error(request, f"Fbr Error: {', '.join(errors)}")
                    return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))
            else:
                messages.success(
                    request, "Invoice update successfully without FBR integration!"
                )

            return redirect("home.invoices.view", id=data.id)

        if (i_mode.is_live and not data.is_test) or (
            not i_mode.is_live and data.is_test
        ):
            customers = CustomerModel.objects.all()
            scenarios = ScenarioModel.objects.all()
            sale_type = ScenarioModel.objects.values_list("sale_type", flat=True)
            items = ItemModel.objects.all()
            uoms = MeasurmentUnitModel.objects.all()
            return render(
                request,
                "editInvoices.html",
                {
                    "i_mode": i_mode,
                    "data": data,
                    "customers": customers,
                    "scenarios": scenarios,
                    "sale_type": sale_type,
                    "items": items,
                    "uoms": uoms,
                },
            )
        else:
            messages.error(request, "Unauthorized access!")
            return redirect("home.invoices")
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def createLiveInvoices(request):
    try:
        i_mode = InvoiceModeModel.objects.first()
        if i_mode.is_live is False:
            messages.error(request, "Unathorized access!")
            return redirect("home.invoices")

        if request.method == "POST":
            customer = request.POST.get("customer")
            invoiceRefNo = request.POST.get("invoiceRefNo")
            fbr_integrate = request.POST.get("fbr_integrate")

            product_code=request.POST.getlist("product_code")
            product_description=request.POST.getlist("product_description")
            hs_code=request.POST.getlist("hs_code")
            uom=request.POST.getlist("uom")
            unit_price = request.POST.getlist("unit_price")

            rate = request.POST.getlist("rate")
            quantity = request.POST.getlist("quantity")
            totalValues = request.POST.getlist("totalValues")
            valueSalesExcludingST = request.POST.getlist("valueSalesExcludingST")
            salesTaxApplicable = request.POST.getlist("salesTaxApplicable")
            salesTaxWithheldAtSource = request.POST.getlist("salesTaxWithheldAtSource")
            sroScheduleNo = request.POST.getlist("sroScheduleNo")
            sroItemSerialNo = request.POST.getlist("sroItemSerialNo")
            furtherTax = request.POST.getlist("furtherTax")
            discount = request.POST.getlist("discount")
            fedPayable = request.POST.getlist("fedPayable")
            saleType = request.POST.getlist("saleType")
            extraTax = request.POST.getlist("extraTax")
            with_holding_tax = request.POST.get("with_holding_tax", 0)

            invoiceDate = request.POST.get("invoiceDate", date.today())
            invoiceType = "Sale Invoice"

            with transaction.atomic():
                invoice = InvoiceModel.objects.create(
                    invoiceRefNo=invoiceRefNo,
                    customer=CustomerModel.objects.get(id=customer),
                    company=CompanyModel.objects.first(),
                    invoiceDate=invoiceDate,
                    invoiceType=invoiceType,
                    fbr_integrate=fbr_integrate,
                    with_holding_tax=with_holding_tax,
                    is_test=False,
                    user=request.user,
                )
                for i, hs in enumerate(hs_code):
                    InvoiceItemModel.objects.create(
                        invoice=invoice,
                        product_code = product_code[i],
                        product_description = product_description[i],
                        hs_code = hs,
                        uom = uom[i],
                        unit_price = unit_price[i],
                        rate=rate[i],
                        quantity=quantity[i],
                        totalValues=totalValues[i],
                        valueSalesExcludingST=valueSalesExcludingST[i],
                        salesTaxApplicable=salesTaxApplicable[i],
                        salesTaxWithheldAtSource=salesTaxWithheldAtSource[i],
                        sroScheduleNo=sroScheduleNo[i],
                        sroItemSerialNo=sroItemSerialNo[i],
                        furtherTax=furtherTax[i],
                        discount=discount[i],
                        fedPayable=fedPayable[i],
                        saleType=saleType[i],
                        extraTax=extraTax[i],
                    )
            if invoice.fbr_integrate == True or invoice.fbr_integrate == '1':
                # Call FBR API to create invoice
                fbrResponse = getFBRInvoice(invoice, is_test=False)
                if fbrResponse.get("status") == "success":
                    messages.success(request, "Invoice created successfully!")
                else:
                    errors = fbrResponse.get("errors", [])
                    messages.error(request, f"Fbr Error: {', '.join(errors)}")
            else:
                messages.success(
                    request, "Invoice created successfully without FBR integration!"
                )

            return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))

        customers = CustomerModel.objects.all()
        scenarios = ScenarioModel.objects.filter(is_success=False)
        return render(
            request,
            "createLiveInvoices.html",
            {"i_mode": i_mode, "customers": customers, "scenarios": scenarios},
        )
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def createBulkInvoices(request):
    try:
        i_mode = InvoiceModeModel.objects.first()
        if i_mode.is_live is False:
            messages.error(request, "Unathorized access!")
            return redirect("home.invoices")
        if request.method == "POST":
            customer = request.POST.get("customer")
            invoiceRefNo = request.POST.get("invoiceRefNo")
            fbr_integrate = request.POST.get("fbr_integrate")

            item = request.POST.getlist("item")
            hs_code = request.POST.getlist("hs_code")
            uom = request.POST.getlist("uom")
            retailPrice = request.POST.getlist("retailPrice")
            rate = request.POST.getlist("rate")
            quantity = request.POST.getlist("quantity")
            totalValues = request.POST.getlist("totalValues")
            valueSalesExcludingST = request.POST.getlist("valueSalesExcludingST")
            salesTaxApplicable = request.POST.getlist("salesTaxApplicable")
            salesTaxWithheldAtSource = request.POST.getlist("salesTaxWithheldAtSource")
            sroScheduleNo = request.POST.getlist("sroScheduleNo")
            sroItemSerialNo = request.POST.getlist("sroItemSerialNo")
            furtherTax = request.POST.getlist("furtherTax")
            discount = request.POST.getlist("discount")
            fedPayable = request.POST.getlist("fedPayable")
            saleType = request.POST.getlist("saleType")
            extraTax = request.POST.getlist("extraTax")
            with_holding_tax = request.POST.get("with_holding_tax", 0)

            invoiceDate = request.POST.get("invoiceDate", date.today())
            invoiceType = "Sale Invoice"

            with transaction.atomic():
                invoice = InvoiceModel.objects.create(
                    invoiceRefNo=invoiceRefNo,
                    customer=CustomerModel.objects.get(id=customer),
                    company=CompanyModel.objects.first(),
                    invoiceDate=invoiceDate,
                    invoiceType=invoiceType,
                    fbr_integrate=fbr_integrate,
                    with_holding_tax=with_holding_tax,
                    is_test=False,
                    user=request.user,
                )
                for i,product_code  in enumerate(item):
                    InvoiceItemModel.objects.create(
                        invoice=invoice,
                        product_code = product_code,
                        product_description = product_code,
                        hs_code = hs_code[i],
                        uom = uom[i],
                        unit_price = retailPrice[i],
                        rate=rate[i],
                        quantity=quantity[i],
                        totalValues=totalValues[i],
                        valueSalesExcludingST=valueSalesExcludingST[i],
                        salesTaxApplicable=salesTaxApplicable[i],
                        salesTaxWithheldAtSource=salesTaxWithheldAtSource[i],
                        sroScheduleNo=sroScheduleNo[i],
                        sroItemSerialNo=sroItemSerialNo[i],
                        furtherTax=furtherTax[i],
                        discount=discount[i],
                        fedPayable=fedPayable[i],
                        saleType=saleType[i],
                        extraTax=extraTax[i],
                    )
            if invoice.fbr_integrate == True:
                # Call FBR API to create invoice
                fbrResponse = getFBRInvoice(invoice, is_test=False)
                if fbrResponse.get("status") == "success":
                    messages.success(request, "Invoice created successfully!")
                else:
                    errors = fbrResponse.get("errors", [])
                    messages.error(request, f"Fbr Error: {', '.join(errors)}")
            else:
                messages.success(
                    request, "Invoice created successfully without FBR integration!"
                )

            return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))
        else:
            customers = CustomerModel.objects.all()
            scenarios = ScenarioModel.objects.all()
            sale_type = ScenarioModel.objects.values_list("sale_type", flat=True)
            items = ItemModel.objects.all()
            return render(
                request,
                "createBulkInvoices.html",
                {
                    "i_mode": i_mode,
                    "customers": customers,
                    "scenarios": scenarios,
                    "sale_type": sale_type,
                    "items": items,
                },
            )

    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def getExcelContent(request):
    try:
        if request.method == "POST" and request.FILES.get("invoiceFile"):
            excel_file = request.FILES["invoiceFile"]
            filename = excel_file.name.lower()
            ext = os.path.splitext(filename)[1]
            if ext == ".csv":
                decoded_file = excel_file.read().decode("utf-8")
                csv_reader = csv.reader(io.StringIO(decoded_file))
                rows = list(csv_reader)
                if not rows or len(rows) < 2:
                    return JsonResponse(
                        {
                            "status": False,
                            "error": "CSV file must have at least one header row and one data row.",
                        },
                        status=400,
                    )
                headers = [str(h).strip().replace(" ", "_").lower() for h in rows[0]]
                data = []
                for row in rows[1:]:
                    row_dict = {
                        headers[i]: row[i] if i < len(row) else None
                        for i in range(len(headers))
                    }
                    data.append(row_dict)
                return JsonResponse({"status": True, "data": data}, safe=False)
            elif ext in [".xlsx", ".xls"]:
                wb = openpyxl.load_workbook(excel_file)
                ws = wb.active
                rows = list(ws.iter_rows(values_only=True))
                if not rows or len(rows) < 2:
                    return JsonResponse(
                        {
                            "status": False,
                            "error": "Excel file must have at least one header row and one data row.",
                        },
                        status=400,
                    )
                headers = [str(h).strip().replace(" ", "_").lower() for h in rows[0]]
                data = []
                for row in rows[1:]:
                    row_dict = {headers[i]: row[i] for i in range(len(headers))}
                    data.append(row_dict)
                # Iterate over data, create ItemModel, and collect id and product_name
                datalist = []
                for row in data:
                    if row.get("item_name"):
                        datalist.append(
                            {
                                "item_name" : row.get("item_name"),
                                "hs_code" : row.get("hs_code"),
                                "unit_of_measurment" : row.get("unit_of_measurment"),
                                "product_price": row.get("retail_price"),
                                "discount": row.get("discount", 0),
                                "extra_tax": row.get("extra_tax", 0),
                                "fed_payable": row.get("fed_payable", 0),
                                "further_tax": row.get("further_tax", 0),
                                "quantity": row.get("quantity"),
                                "sale_type": row.get("sale_type"),
                                "sales_tax_applicable": row.get("sales_tax_applicable"),
                                "sales_tax_withheld_at_source": row.get("sales_tax_withheld_at_source", 0),
                                "sro_item_serial_no": row.get("sro_item_serial_no"),
                                "sro_schedule_no": row.get("sro_schedule_no"),
                                "tax_rate": row.get("tax_rate", 0),
                                "total_values": row.get("total_values"),
                                "value_sales_excluding_st": row.get("value_sales_excluding_st", 0),
                            }
                        )
                scenario_list = ScenarioModel.objects.all()
                # Render the data to the template and return the HTML as a response
                html = render(
                    request,
                    "excelextractFile.html",
                    {"datalist": datalist, "scenario_list": scenario_list},
                ).content.decode("utf-8")
                return JsonResponse({"status": True, "html": html}, safe=False)
            else:
                return JsonResponse(
                    {"status": False, "error": "Unsupported file type."}, status=400
                )
        else:
            return JsonResponse(
                {"status": False, "error": "No file uploaded."}, status=400
            )
    except Exception as e:
        return JsonResponse({"status": False, "error": str(e)}, status=500)


@login_required
def createTestInvoices(request):
    try:
        if request.method == "POST":
            customer = request.POST.get("customer")
            invoiceRefNo = request.POST.get("invoiceRefNo")
            scenarioId = request.POST.get("scenarioId")
            fbr_integrate = request.POST.get("fbr_integrate")
            with_holding_tax = request.POST.get("with_holding_tax", 0)

            product_code=request.POST.getlist("product_code")
            product_description=request.POST.getlist("product_description")
            hs_code=request.POST.getlist("hs_code")
            uom=request.POST.getlist("uom")
            unit_price = request.POST.getlist("unit_price")

            rate = request.POST.getlist("rate")
            quantity = request.POST.getlist("quantity")
            totalValues = request.POST.getlist("totalValues")
            valueSalesExcludingST = request.POST.getlist("valueSalesExcludingST")
            salesTaxApplicable = request.POST.getlist("salesTaxApplicable")
            salesTaxWithheldAtSource = request.POST.getlist("salesTaxWithheldAtSource")
            sroScheduleNo = request.POST.getlist("sroScheduleNo")
            sroItemSerialNo = request.POST.getlist("sroItemSerialNo")
            furtherTax = request.POST.getlist("furtherTax")
            discount = request.POST.getlist("discount")
            fedPayable = request.POST.getlist("fedPayable")
            saleType = request.POST.getlist("saleType")
            extraTax = request.POST.getlist("extraTax")

            invoiceDate = date.today()
            invoiceType = "Sale Invoice"

            with transaction.atomic():
                invoice = InvoiceModel.objects.create(
                    invoiceRefNo=invoiceRefNo,
                    customer=CustomerModel.objects.get(id=customer),
                    company=CompanyModel.objects.first(),
                    scenarioId=ScenarioModel.objects.get(id=scenarioId),
                    invoiceDate=invoiceDate,
                    invoiceType=invoiceType,
                    fbr_integrate=fbr_integrate,
                    with_holding_tax=with_holding_tax,
                    user=request.user,
                )
                for i,hs in enumerate(hs_code):
                    InvoiceItemModel.objects.create(
                        product_code = product_code[i],
                        product_description = product_description[i],
                        hs_code = hs,
                        uom = uom[i],
                        unit_price = unit_price[i],
                        invoice=invoice,
                        rate=rate[i],
                        quantity=quantity[i],
                        totalValues=totalValues[i],
                        valueSalesExcludingST=valueSalesExcludingST[i],
                        salesTaxApplicable=salesTaxApplicable[i],
                        salesTaxWithheldAtSource=salesTaxWithheldAtSource[i],
                        sroScheduleNo=sroScheduleNo[i],
                        sroItemSerialNo=sroItemSerialNo[i],
                        furtherTax=furtherTax[i],
                        discount=discount[i],
                        fedPayable=fedPayable[i],
                        saleType=saleType[i],
                        extraTax=extraTax[i],
                    )

            if invoice.fbr_integrate == True or invoice.fbr_integrate == '1':
                # Call FBR API to create invoice
                fbrResponse = getFBRInvoice(invoice, is_test=True)
                if fbrResponse.get("status") == "success":
                    messages.success(request, "Invoice created successfully!")
                else:
                    errors = fbrResponse.get("errors", [])
                    messages.error(request, f"Fbr Error: {', '.join(errors)}")
            else:
                messages.success(
                    request, "Invoice created successfully without FBR integration!"
                )

            return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))

        i_mode = InvoiceModeModel.objects.first()
        if not i_mode:
            i_mode = InvoiceModeModel.objects.create(is_live=False)
        customers = CustomerModel.objects.all()
        scenarios = ScenarioModel.objects.all()
        uoms = MeasurmentUnitModel.objects.all()
        return render(
            request,
            "createTestInvoices.html",
            {"i_mode": i_mode, "customers": customers, "scenarios": scenarios,'uoms':uoms},
        )
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def deleteTestInvoices(request, id=None):
    try:
        data = InvoiceModel.objects.get(id=id)
        if data:
            if data.is_test:
                data.delete()
                messages.success(request, "Data deleted successfully!")
            else:
                messages.error(request, "Unauthorized request!")
        else:
            messages.error(request, "No Data found!")
        return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def deleteInvoicesItem(request, id=None):
    try:
        data = InvoiceItemModel.objects.get(id=id)
        if data:
            data.delete()
            return JsonResponse(
                {"status": True, "message": "Data deleted successfully!"}
            )
        else:
            return JsonResponse({"status": False, "message": "No invoice item found!"})
    except Exception as e:
        return JsonResponse({"status": False, "message": str(e)})


# def getFBRInvoice(invoice, is_test):
#     try:
#         return {"status": "success", "errors": ""}

#         if is_test or not InvoiceModeModel.objects.first().is_live:
#             api_url = invoice.company.sandbox_api
#             url = "https://gw.fbr.gov.pk/di_data/v1/di/postinvoicedata_sb"

#         else:
#             api_url = invoice.company.live_api
#             url = "https://gw.fbr.gov.pk/di_data/v1/di/postinvoicedata"

#         in_items = []
#         items_ids = []
#         for item in invoice.items.all():
#             rate_value = float(item.rate)
#             rate_formatted = (
#                 f"{int(rate_value)}%" if rate_value.is_integer() else f"{rate_value}%"
#             )
#             salesTaxWithheldAtSource = (
#                 float(item.salesTaxWithheldAtSource) / 100 * float(item.salesTaxApplicable)
#             )
#             pen_item = {
#                     "hsCode": item.hs_code,
#                     "productDescription": "-",
#                     "rate": rate_formatted,
#                     "uoM": item.uom,
#                     "quantity": item.quantity,
#                     "totalValues": float(item.totalValues),
#                     "valueSalesExcludingST": float(item.valueSalesExcludingST),
#                     "fixedNotifiedValueOrRetailPrice": float(item.unit_price),
#                     "salesTaxApplicable": float(item.salesTaxApplicable),
#                     "salesTaxWithheldAtSource": salesTaxWithheldAtSource,
#                     "extraTax": float(item.extraTax),
#                     "furtherTax": float(item.furtherTax),
#                     "sroScheduleNo": item.sroScheduleNo,
#                     "fedPayable": float(item.fedPayable),
#                     "discount": float(item.discount),
#                     "saleType": item.saleType.strip(),
#                     "sroItemSerialNo": item.sroItemSerialNo,
#                 }
#             in_items.append(pen_item)
#             items_ids.append(item.id)
#         try:
#             DT = invoice.invoiceDate.strftime("%Y-%m-%d")
#         except Exception as e:
#             DT = invoice.invoiceDate
#         fireData = {
#             "invoiceType": invoice.invoiceType,
#             "invoiceDate": DT,
#             "sellerNTNCNIC": invoice.company.company_ntn_cnic,
#             "sellerBusinessName": invoice.company.company_name,
#             "sellerProvince": invoice.company.province,
#             "sellerAddress": invoice.company.address,
#             "buyerNTNCNIC": invoice.customer.company_ntn_cnic,
#             "buyerBusinessName": invoice.customer.company_name,
#             "buyerProvince": invoice.customer.province,
#             "buyerAddress": invoice.customer.address,
#             "buyerRegistrationType": invoice.customer.register_type,
#             "invoiceRefNo": invoice.invoiceRefNo,
#             "items": in_items,
#         }
#         # Add scenarioId only if condition is met
#         if is_test or not InvoiceModeModel.objects.first().is_live:
#             fireData["scenarioId"] = invoice.scenarioId.code

#         path = os.path.join(settings.BASE_DIR, "fbr_payload.txt")
#         with open(path, "w", encoding="utf-8") as f:
#             json.dump(fireData, f, ensure_ascii=False, indent=2)
            
#         headers = {
#             "Authorization": f"Bearer {api_url}",
#             "Content-Type": "application/json",
#         }
#         # Send POST request
#         response = requests.post(url, headers=headers, json=fireData, timeout=60)
#         res_json = response.json()  # Convert response to dict

#         # Validate the response
#         validation = res_json.get("validationResponse", {})
#         response.raise_for_status()
#         status = validation.get("status")

#         if status == "Valid":
#             invoiceNumber = res_json.get("invoiceNumber", "")
#             invoice.fbrInvoiceNumber = invoiceNumber
#             invoice.save()
#             invoice_statuses = validation.get("invoiceStatuses", [])
#             for index, item_id in enumerate(items_ids):
#                 itemInvoiceNumber = invoice_statuses[index].get("invoiceNo", "")
#                 item = InvoiceItemModel.objects.get(id=item_id)
#                 item.fbrInvoiceNumber = itemInvoiceNumber
#                 item.save()

#             if is_test:
#                 scenarioId = invoice.scenarioId
#                 ScenarioModel.objects.filter(id=scenarioId.id).update(is_success=True)

#             errRetn = {"status": "success", "errors": ""}

#         else:
#             if "errorCode" in validation:
#                 errRetn = {"status": "error", "errors": [validation.get("error")]}
#             else:
#                 # Collect error messages (if available)
#                 invoice_statuses = validation.get("invoiceStatuses", [])
#                 errors = [
#                     item.get("error") for item in invoice_statuses if "error" in item
#                 ]
#                 errRetn = {"status": "error", "errors": errors}

#             invoice.fbr_integrate = False
#             invoice.save()
#             # return redirect("home.invoices.edit", id=invoice.id)

#         InvoiceLogModel.objects.create(invoice=invoice, log_message=str(res_json))

#         return errRetn

#     except Exception as e:
#         return {"status": "error", "errors": [f"exception error: {str(e)}"]}


def getFBRInvoice(invoice, is_test):
    return send_invoice_to_fbr(invoice, is_test)


@login_required
def itemsReport(request):
    try:
        items = ItemModel.objects.all()
        invoices = []
        i_mode = InvoiceModeModel.objects.first()
        env_mode = True if not i_mode.is_live else False
        fbrInt = request.GET.getlist("fbr_integrate")
        if request.GET.get("item"):
            invoices = InvoiceItemModel.objects.filter(
                item__id=request.GET.get("item"),
                invoice__is_test=env_mode,
            ).order_by("-id")
            if fbrInt:
                invoices = invoices.filter(
                    invoice__fbr_integrate__in=[
                        bool(int(val)) for val in fbrInt if val in ["0", "1"]
                    ]
                )
            if request.GET.get("date_from") and request.GET.get("date_to"):
                fromDate = request.GET.get("date_from")
                toDate = request.GET.get("date_to")
                invoices = invoices.filter(
                    invoice__invoiceDate__range=[fromDate, toDate]
                )

        return render(
            request,
            "itemsReport.html",
            {"items": items, "invoices": invoices, "fbrInt": fbrInt},
        )
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def customersReport(request):
    try:
        customers = CustomerModel.objects.all()
        invoices = []
        i_mode = InvoiceModeModel.objects.first()
        env_mode = True if not i_mode.is_live else False
        fbrInt = request.GET.getlist("fbr_integrate")
        if request.GET.get("customer"):
            invoices = InvoiceModel.objects.filter(
                customer__id=request.GET.get("customer"),
                is_test=env_mode,
            ).order_by("-id")
            if fbrInt:
                invoices = invoices.filter(
                    fbr_integrate__in=[
                        bool(int(val)) for val in fbrInt if val in ["0", "1"]
                    ]
                )
            if request.GET.get("date_from") and request.GET.get("date_to"):
                fromDate = request.GET.get("date_from")
                toDate = request.GET.get("date_to")
                invoices = invoices.filter(invoiceDate__range=[fromDate, toDate])

        return render(
            request,
            "customersReport.html",
            {"customers": customers, "invoices": invoices, "fbrInt": fbrInt},
        )
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")
    
@login_required
def licenseSummary(request):
    try:
        LICENSE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "media", "license.key"))
        if not os.path.exists(LICENSE_FILE):
            data = {}
        else:
            with open(LICENSE_FILE, "r") as f:
                license_data = json.load(f)
            license_data.pop("signature")
            data = license_data
        return render(request, "licenseSummary.html", {"data": data})
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def changeInvoicesMode(request):
    try:
        if request.method != "POST":
            messages.error(request, "Invalid request method!")
        else:
            user = request.user
            if not user.is_superuser:
                messages.error(request, "Unauthorized request!")
                return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))
            else:
                # Check if the POST["password"] matches the superuser password
                password = request.POST.get("password")
                if not user.check_password(password):
                    messages.error(request, "Invalid password!")
                    return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))
                # Check if all scenarios are successful
                is_success_list = ScenarioModel.objects.values_list(
                    "is_success", flat=True
                )
                if ScenarioModel.objects.exists():
                    if all(is_success_list):
                        inv = InvoiceModeModel.objects.first()
                        mode = inv.is_live
                        # if the mode is true then change it to false and vice versa
                        if mode:
                            inv.is_live = False
                        else:
                            inv.is_live = True
                        inv.save()
                        messages.success(request, "Invoicing mode changed successfully!")
                    else:
                        messages.error(
                            request,
                            "Selected scenario is not success yet! Please try test mode first.",
                        )
                else:
                    messages.error(
                        request,
                        "You haven't selected any scenario yet.",
                    )
        return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def getAjaxItems(request):
    try:
        sale_type = ScenarioModel.objects.values_list("sale_type", flat=True)
        uoms = MeasurmentUnitModel.objects.values_list("code", flat=True)
        return JsonResponse(
            {"sale_type": list(sale_type), "uoms": list(uoms)}, safe=False
        )
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def logout(request):
    try:
        logout(request)
        return redirect("/")
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def downloadLicenseAd(request, id):
    try:
        data = LicenseModel.objects.get(id=id)
        return render(request, "download_license.html" ,{"data":data})
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def license_history(request):
    try:
        licenses = LicenseModel.objects.all().order_by("-id")
        return render(request, "license_history.html", {"datalist": licenses})  
    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")


@login_required
def createLicenseAd(request):
    try:
        user = request.user

        if not user.is_superuser:
            messages.error(request, "Unauthorized request!")
            return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))

        if request.method == "POST":
            company_ntn_cnic = request.POST.get("company_ntn_cnic")
            issue = request.POST.get("issue")
            expiry = request.POST.get("expiry")

            if not company_ntn_cnic or not issue or not expiry:
                messages.error(request, "All fields are required!")
                return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))

            try:
                # Validate date format
                issue_date = datetime.strptime(issue, "%Y-%m-%d").date()
                expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
                if issue_date >= expiry_date:
                    messages.error(
                        request, "Issue date must be earlier than expiry date."
                    )
                    return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))
                else:
                    res = create_license_file(
                        company_ntn_cnic,
                        issue_date.strftime("%Y-%m-%d"),
                        expiry_date.strftime("%Y-%m-%d"),
                    )
                    if res[0]:
                        lins = LicenseModel.objects.create(
                            company_ntn_cnic=company_ntn_cnic,
                            issue=issue_date,
                            expiry=expiry_date,
                            user=request.user,
                            license_file=res[1],
                        )
                        return redirect("home.download_license" , lins.id)
                    else:
                        messages.error(request, res[1])
                return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))

            except ValueError:
                messages.error(request, "Invalid date format. Use YYYY-MM-DD.")
                return redirect(request.META.get("HTTP_REFERER", "/fallback-url/"))

        return render(request, "createLicenseAd.html", {})

    except Exception as e:
        return HttpResponse(f"Something went wrong! {str(e)}")
