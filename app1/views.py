from django.http import HttpResponse
from django.shortcuts import render

def helloworld(request):
    return render(request, "helloworld.html")