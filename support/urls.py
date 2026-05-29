"""Public support URLs."""

from django.urls import path

from support.views import ContactInquiryCreateView

app_name = "support"

urlpatterns = [
    path("contact/", ContactInquiryCreateView.as_view(), name="contact-inquiry"),
]
