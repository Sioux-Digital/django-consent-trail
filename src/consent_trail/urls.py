from django.urls import path

from . import views

app_name = "consent_trail"

urlpatterns = [
    path("accept/", views.accept, name="accept"),
    path("my-consents/", views.my_consents, name="my_consents"),
    path("<slug:slug>/", views.document, name="document"),
]
