# filepath: c:\###PYTHONANY_WORKING\WFDASH\search\urls.py
from django.urls import path
from . import views

app_name = "search"  # Define the namespace for this app

urlpatterns = [
    path("ajax/", views.ajax_universal_search, name="ajax_universal_search"),
    # You could add other search-related URLs here later if needed
]
