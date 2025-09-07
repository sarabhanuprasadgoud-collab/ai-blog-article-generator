from django.urls import path
from . import views

urlpatterns = [
    # Home / Dashboard
    path('', views.index, name='index'),

    # Authentication
    path('login/', views.user_login, name='login'),
    path('signup/', views.user_signup, name='signup'),
    path('logout/', views.user_logout, name='logout'),

    # Blog-related routes
    path('generate-blog/', views.generate_blog, name='generate-blog'),
    path('blog-list/', views.blog_list, name='blog-list'),
    path('blog-details/<int:pk>/',views.blog_details, name='blog-details'),
    path("blog-details/<int:pk>/delete/", views.blog_delete, name="blog-delete"),
]
