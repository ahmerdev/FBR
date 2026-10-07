from django.db import models
from django.contrib.auth import get_user_model

# Create your models here.


class BaseModel(models.Model):
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class CompanyModel(BaseModel):
    company_name = models.CharField(max_length=250)
    company_ntn_cnic = models.CharField(max_length=250)
    province = models.CharField(max_length=50)
    address = models.TextField()
    phone = models.CharField(max_length=20)
    email = models.CharField(max_length=50)
    sandbox_api = models.CharField(max_length=250, null=True, blank=True)
    live_api = models.CharField(max_length=250, null=True, blank=True)
    company_logo = models.ImageField(upload_to="company_logos/", null=True, blank=True)

    def __str__(self):
        return self.company_name


class CustomerModel(BaseModel):
    C_types = [
        ("Registered", "Registered"),
        ("Unregistered", "Unregistered"),
    ]
    Province = [
        ("Punjab", "Punjab"),
        ("KPK", "KPK"),
        ("Sindh", "Sindh"),
        ("Balochistan", "Balochistan"),
        ("AJK & GB", "AJK & GB"),
    ]

    company_name = models.CharField(max_length=250)
    company_ntn_cnic = models.CharField(max_length=250)
    province = models.CharField(max_length=50, choices=Province)
    address = models.TextField()
    register_type = models.CharField(max_length=50, choices=C_types)

    def __str__(self):
        return self.company_name


class HScodeModel(BaseModel):
    hs_code = models.CharField(max_length=100, unique=True)
    code_description = models.TextField()
    rate = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    def __str__(self):
        return self.hs_code


class MeasurmentUnitModel(BaseModel):
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=250)

    def __str__(self):
        return self.name


class ItemModel(BaseModel):
    product_name = models.CharField(max_length=250)
    product_slug = models.CharField(max_length=250, unique=True)
    hs_code = models.ForeignKey(
        HScodeModel, on_delete=models.CASCADE, related_name="items"
    )
    measurment_unit = models.ForeignKey(
        MeasurmentUnitModel, on_delete=models.CASCADE, related_name="items"
    )
    product_description = models.TextField(null=True, blank=True)
    product_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    tax_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    def __str__(self):
        return self.product_name


class ScenarioModel(BaseModel):
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField()
    sale_type = models.TextField(null=True, blank=True)
    is_success = models.BooleanField(null=True, blank=True, default=False)

    def __str__(self):
        return f"{self.code}, success status: {self.is_success}"


class InvoiceModeModel(BaseModel):
    is_live = models.BooleanField(default=False)

    def __str__(self):
        return f"Invoicing mode: {self.is_live}"


class InvoiceModel(BaseModel):
    User = get_user_model()

    invoiceRefNo = models.CharField(max_length=50, unique=True)
    customer = models.ForeignKey(
        CustomerModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
    )
    company = models.ForeignKey(
        CompanyModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
    )
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="invoices"
    )
    scenarioId = models.ForeignKey(
        ScenarioModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
    )
    invoiceDate = models.DateField()
    invoiceType = models.CharField(max_length=250)
    fbrInvoiceNumber = models.CharField(max_length=250, null=True, blank=True)
    is_test = models.BooleanField(default=True)
    fbr_integrate = models.BooleanField(default=False)
    with_holding_tax = models.DecimalField(
        max_digits=10, decimal_places=2, default=0.00
    )

    def with_holding_total(self):
        total = sum(item.totalValues for item in self.items.all())
        return round((self.with_holding_tax / 100) * total, 2)

    def totalValues(self):
        total = sum(item.totalValues for item in self.items.all())
        return round(total, 2)

    def totalRate(self):
        total = sum(item.salesTaxApplicable for item in self.items.all())
        return round(total, 2)

    def __str__(self):
        return f"Invoice {self.invoiceRefNo} for {self.customer.company_name} on {self.invoiceDate}"


class InvoiceItemModel(BaseModel):
    invoice = models.ForeignKey(
        InvoiceModel, on_delete=models.CASCADE, related_name="items"
    )
    product_code = models.CharField(max_length=150)
    product_description = models.TextField()
    hs_code = models.CharField(max_length=150)
    uom = models.CharField(max_length=50)
    unit_price = models.DecimalField(max_digits=30, decimal_places=2, default=0.00)
    rate = models.DecimalField(max_digits=30, decimal_places=2, default=0.00)
    quantity = models.IntegerField(default=1)
    totalValues = models.DecimalField(max_digits=30, decimal_places=2)
    valueSalesExcludingST = models.DecimalField(max_digits=30, decimal_places=2)
    salesTaxApplicable = models.DecimalField(max_digits=30, decimal_places=2)
    salesTaxWithheldAtSource = models.DecimalField(max_digits=30, decimal_places=2)
    sroScheduleNo = models.CharField(max_length=150, null=True, blank=True)
    sroItemSerialNo = models.CharField(max_length=150, null=True, blank=True)
    furtherTax = models.DecimalField(max_digits=30, decimal_places=2, default=0.00)
    discount = models.DecimalField(max_digits=30, decimal_places=2, default=0.00)
    fedPayable = models.DecimalField(max_digits=30, decimal_places=2, default=0.00)
    saleType = models.CharField(max_length=50)
    extraTax = models.DecimalField(max_digits=30, decimal_places=2, default=0.00)
    fbrInvoiceNumber = models.CharField(max_length=250, null=True, blank=True)

    def price(self):
        return round(self.valueSalesExcludingST/self.quantity, 2)

    def __str__(self):
        return f"Item {self.item.product_name} in Invoice {self.invoice.invoiceRefNo}"


class InvoiceLogModel(BaseModel):
    invoice = models.ForeignKey(
        InvoiceModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="logs",
    )
    log_message = models.TextField()
    log_type = models.CharField(
        max_length=50, default="info", null=True, blank=True
    )  # e.g., 'info', 'error', 'warning'
    is_success = models.BooleanField(default=False)

    def __str__(self):
        return (
            f"Log for Invoice {self.invoice.invoiceRefNo}: {self.log_message[:50]}..."
        )

class LicenseModel(BaseModel):
    company_ntn_cnic = models.CharField(max_length=250)
    issue= models.DateField()
    expiry= models.DateField() 
    user = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True, blank=True, related_name="licenses")
    license_file = models.CharField(null=True, blank=True, max_length=1000)

    def __str__(self):
        return f"License for {self.company_ntn_cnic} issued on {self.issue} expiring on {self.expiry}"