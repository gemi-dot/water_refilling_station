from django.urls import path
from . import views

urlpatterns = [
    path('customers/', views.customer_list, name='customer_list'),
    path('customers/add/', views.customer_add, name='customer_add'),
    path('customers/edit/<int:pk>/', views.customer_edit, name='customer_edit'),
    path('customers/delete/<int:pk>/', views.customer_delete, name='customer_delete'),

    path('', views.home, name='home'),
    path('transactions/', views.transaction_list, name='transaction_list'),  # <-- list view
    path('transactions/add/', views.add_transaction, name='add_transaction'),
    path('transactions/edit/<int:pk>/', views.edit_transaction, name='edit_transaction'),
    path('transactions/<int:pk>/', views.transaction_detail, name='transaction_detail'),
    path('transactions/delete/<int:pk>/', views.delete_transaction, name='delete_transaction'),


    path('inventory/', views.inventory_list, name='inventory_list'),
    path('inventory/add/', views.inventory_add, name='inventory_add'),
    #path('inventory/edit/<int:pk>/', views.inventory_edit, name='inventory_edit'),

    path('inventory/edit/<int:pk>/', views.inventory_edit, name='inventory_edit'),


    path('inventory/delete/<int:pk>/', views.inventory_delete, name='inventory_delete'),


    path('reports/daily/', views.daily_report, name='daily_report'),


    path('reports/monthly/', views.monthly_report, name='monthly_report'),


]





