from django import template
from django.conf import settings
from home.models import CompanyModel
from datetime import datetime

register = template.Library()


@register.filter
def div(value, arg):
    try:
        return round(float(value) / float(arg), 2)
    except (ZeroDivisionError, ValueError, TypeError):
        return 0


@register.filter
def getLogo(s):
    try:
        company = CompanyModel.objects.first()
        if company and company.company_logo:
            return settings.MEDIA_URL + str(company.company_logo)
        else:
            return "/static/logo/logo.png"
    except Exception:
        return "/static/logo/logo.png"


@register.filter
def today_date(d):
    return datetime.now().strftime("%Y-%m-%d")

@register.filter
def isExpire(d):
    try:
        if d < datetime.now().date():
            return '<span class="badge bg-danger">Expired</span>'
        else:
            return '<span class="badge bg-success">Valid</span>'
    except Exception:
        return "Error"  

@register.filter
def expireWithin(d):    
    try:
        if isinstance(d, str):
            try:
                d = datetime.strptime(d, "%Y-%m-%d").date()
            except ValueError:
                return "Invalid date"
        delta = (d - datetime.now().date()).days
        if delta < 0:
            return "Expired"
        elif delta == 0:
            return "Expires Today"
        else:
            return f"{delta} days"
    except Exception:
        return "Error"
