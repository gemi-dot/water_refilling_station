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


]
