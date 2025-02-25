from django.urls import path
from . import views

app_name = 'users'

urlpatterns = [
    path('profile/', views.profile, name='profile'),
    path('change-mode/', views.change_mode, name='change_mode'),
    # ... other user-related URLs ...
]
