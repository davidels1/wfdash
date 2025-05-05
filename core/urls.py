"""
URL configuration for core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.conf.urls.i18n import i18n_patterns
from home import views as home_views  # Changed import
from wfdash import views as wfdash_views  # Changed import
from django.views.static import serve


handler404 = 'home.views.handler404'
handler403 = 'home.views.handler403'
handler500 = 'home.views.handler500'


urlpatterns = [
    path('admin/', admin.site.urls),  # Make sure this line exists
    path('', include('home.urls')),
    path("api/", include("apps.api.urls")),
    path('accounts/', include('allauth.urls')),
    path('', include('apps.file_manager.urls')),
    path('tasks/', include('apps.tasks.urls')),
    path('charts/', include('apps.charts.urls')),
    path("tables/", include("apps.tables.urls")),
    path('users/', include('apps.users.urls')),
    path('i18n/', include('django.conf.urls.i18n')),
    path('wfdash/', include('wfdash.urls')),
    path('quotes/', include('quotes.urls')),
    path('orders/', include('orders.urls')),
    path('drivers/', include('driver_list.urls')),
    path('', include('pwa.urls')),
    path('stock/', include('stock_management.urls')),
    path('dashboard/', include(('dashboard.urls', 'dashboard'), namespace='dashboard')),
    path('stock-orders/', include('stock_orders.urls', namespace='stock_orders')),
    path('portal/', include('customer_portal.urls', namespace='customer_portal')),
    path('delivery/', include('delivery_notes.urls', namespace='delivery_notes')),
    path('delivery-notes/', include('delivery_notes.urls', namespace='delivery_notes')),
    path("rep/", include("rep_portal.urls", namespace="rep_portal")),
    path("search/", include("search.urls", namespace="search")),
    
    path('repairs/', include('repairs.urls', namespace='repairs')),

    path(
        "internal_stock/", include("internal_stock.urls", namespace="internal_stock")
    ),  # Add this line




    re_path(r'^media/(?P<path>.*)$', serve,{'document_root': settings.MEDIA_ROOT}),
    re_path(r'^static/(?P<path>.*)$', serve,{'document_root': settings.STATIC_ROOT}),

    # Debug toolbar
    path("__debug__/", include("debug_toolbar.urls")),
    path('save-subscription/', home_views.save_subscription, name='save_subscription'),
    path('send-test-notification/', home_views.send_test_notification, name='send_test_notification'),
    path('offline/', home_views.offline_view, name='offline'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)


urlpatterns += i18n_patterns(
    path('i18n/', home_views.i18n_view, name="i18n_view")  # Correct import for i18n_view
)

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)