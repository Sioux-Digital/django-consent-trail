from django.urls import include, path

urlpatterns = [path("consent/", include("consent_trail.urls"))]
