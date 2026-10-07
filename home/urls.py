from django.urls import path
from home import views as home_views

urlpatterns = [
    path("", home_views.customDashboard, name="home.dashboard"),
    path("company-profile", home_views.companyProfile, name="home.company-profile"),

    path("my-profile", home_views.myProfile, name="home.my-profile"),

    path("users", home_views.users, name="home.users"),
    path("add-edit-user", home_views.addEditUsers, name="home.add-edit-users"),
    path("add-edit-user/<username>", home_views.addEditUsers, name="home.users.edit"),
    path("delete-user/<username>", home_views.deleteUsers, name="home.users.delete"),
    path("check-username", home_views.checkUsername, name="home.check-username"),

    path("customers", home_views.customers, name="home.customers"),
    path("add-edit-customers", home_views.addEditCustomers, name="home.customers.new"),
    path("add-edit-customers/<id>", home_views.addEditCustomers, name="home.customers.edit"),
    path("delete-customers/<id>", home_views.deleteCustomers, name="home.customers.delete"),

    path("hs-code", home_views.hsCodes, name="home.hs-code"),
    path("add-edit-hs-code", home_views.AddEdithsCodes, name="home.hs-code.create"),
    path("add-edit-hs-code/<hs_code>", home_views.AddEdithsCodes, name="home.hs-code.edit"),
    path("delete-hs-code/<hs_code>", home_views.deletehsCodes, name="home.hs-code.delete"),
    path("fbr-hs-codes", home_views.FBRHscode, name="home.hs-code.fbr-ref"),

    path("items", home_views.listItems, name="home.items"),
    path("add-edit-items", home_views.addEditItems, name="home.items.new"),
    path("add-edit-items/<id>", home_views.addEditItems, name="home.items.edit"),
    path("delete-items/<id>", home_views.deleteItems, name="home.items.delete"),

    path("scenario", home_views.scenarioIndex, name="home.scenario"),
    path("scenario/delete/<code>", home_views.scenarioDelete, name="home.scenario.delete"),
    path("scenario/auto-run", home_views.scenarioAutoRun, name="home.scenario.autorun"),
    path("scenario/payload/<code>", home_views.scenarioPayload, name="home.scenario.payload"),
    path("scenario/payloads", home_views.scenarioPayloadAll, name="home.scenario.payloads"),
    path("invoices/payload/<id>", home_views.invoicePayloadPreview, name="home.invoices.payload"),
    path("invoices/validate/<id>", home_views.invoiceValidateFBR, name="home.invoices.validate"),
    path("hs-uom", home_views.hsUomLookup, name="home.hs-uom"),
    path("scenario/sample/<code>", home_views.scenarioFormSample, name="home.scenario.sample"),
    path("sro-lookup", home_views.sroLookup, name="home.sro-lookup"),
    path("hs-list", home_views.hsList, name="home.hs-list"),

    path("measurment-units", home_views.measurmentUnits, name="home.measurment-units"),
    path("measurment-units/add-edit", home_views.measurmentUnitsAddEdit, name="home.measurment-units.create"),
    path("measurment-units/add-edit/<id>", home_views.measurmentUnitsAddEdit, name="home.measurment-units.edit"),
    path("measurment-units/delete/<id>", home_views.measurmentUnitsDelete, name="home.measurment-units.delete"),

    path("invoices", home_views.InvoicesList, name="home.invoices"),
    path("invoices/<str:type>", home_views.InvoicesList, name="home.invoices"),
    path("invoices/view/<id>", home_views.viewInvoices, name="home.invoices.view"),
    path("invoices/edit/<id>", home_views.editInvoices, name="home.invoices.edit"),
    path("invoices/print/<id>", home_views.printInvoices, name="home.invoices.print"),
    path("invoices/test-invoice/create", home_views.createTestInvoices, name="home.invoices.create-test"),
    path("invoices/test-invoice/delete/<id>", home_views.deleteTestInvoices, name="home.invoices.delete-test"),
    path("invoices/delete-inv-item/<id>", home_views.deleteInvoicesItem, name="home.invoices.item.delete"),

    path("invoices/live-invoice/create", home_views.createLiveInvoices, name="home.invoices.create-live"),
    path("invoices/live-invoice/create-bulk", home_views.createBulkInvoices, name="home.invoices.create-bulk-live"),
    path("get-the-excel-content", home_views.getExcelContent, name="home.invoices.get-excel-content"),

    path("change-inv-mode", home_views.changeInvoicesMode, name="home.change-invoice-mode"),
    path("license-summary", home_views.licenseSummary, name="home.com-license"),

    path("report/items", home_views.itemsReport, name="report.items"),
    path("report/customers", home_views.customersReport, name="report.customers"),

    path('get-ajax-items', home_views.getAjaxItems, name='home.get-ajax-items'),
    path('logout/', home_views.logout, name='logout'),
]
