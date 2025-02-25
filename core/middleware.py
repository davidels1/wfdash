from django.contrib.sessions.middleware import SessionMiddleware
from django.middleware.csrf import CsrfViewMiddleware

class CustomSessionMiddleware(SessionMiddleware):
    def process_request(self, request):
        try:
            super().process_request(request)
        except Exception:
            request.session.flush()

class CustomCsrfMiddleware(CsrfViewMiddleware):
    def process_view(self, request, callback, callback_args, callback_kwargs):
        if getattr(request, '_dont_enforce_csrf_checks', False):
            return None
        return super().process_view(request, callback, callback_args, callback_kwargs)