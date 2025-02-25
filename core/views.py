from django.shortcuts import render
from django.views.decorators.csrf import requires_csrf_token

@requires_csrf_token
def csrf_failure(request, reason=""):
    context = {
        'reason': reason,
        'referrer': request.META.get('HTTP_REFERER', '')
    }
    return render(request, 'csrf_failure.html', context)