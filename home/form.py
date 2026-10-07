from django import forms
from .models import *


class CustomerForm(forms.ModelForm):
    class Meta:
        model = CustomerModel
        fields = "__all__"
        widgets = {
            "address": forms.Textarea(attrs={"rows": 1}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({"class": "form-control"})

        self.fields["province"].choices = [("", "-- Select one --")] + list(
            self.fields["province"].choices
        )[1:]
        self.fields["register_type"].choices = [("", "-- Select one --")] + list(
            self.fields["register_type"].choices
        )[1:]


class HScodeForm(forms.ModelForm):
    class Meta:
        model = HScodeModel
        exclude = ['rate']
        widgets = {"code_description": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super(HScodeForm, self).__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({"class": "form-control"})


class ItemsForm(forms.ModelForm):
    class Meta:
        model = ItemModel
        fields = "__all__"
        widgets = {
            "product_slug": forms.TextInput(attrs={"readonly": "readonly"}),
            "product_description": forms.Textarea(attrs={"rows": "3"}),
            }   

    def __init__(self, *args, **kwargs):
        super(ItemsForm, self).__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({"class": "form-control"})
        self.fields["hs_code"].empty_label = "-- Select one --"
        self.fields["measurment_unit"].empty_label = "-- Select one --"


class MeasurmentUnitForm(forms.ModelForm):
    class Meta:
        model = MeasurmentUnitModel
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super(MeasurmentUnitForm, self).__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({"class":"form-control"})
