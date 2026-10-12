from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def advertiser_home(request):
    return render(request, "console/advertiser_home.html")
