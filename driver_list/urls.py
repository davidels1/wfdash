from django.urls import path
from . import views

app_name = 'driver_list'

urlpatterns = [
    path('pool/', views.collection_pool, name='collection_pool'),
    path('assigned/', views.assigned_collections, name='assigned_collections'),
    path('assign/<int:collection_id>/', views.assign_driver, name='assign_driver'),
    path('update/<int:collection_id>/', views.update_collection_status, name='update_status'),
    path('bulk-assign/', views.bulk_assign_driver, name='bulk_assign_driver'),
    path('completed-collections/', views.completed_collections, name='completed_collections'),
    path('activate-collection/<int:collection_id>/', views.activate_collection, name='activate_collection'),
]