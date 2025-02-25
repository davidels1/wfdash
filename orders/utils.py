def is_mobile(request):
    """Check if request is from mobile device"""
    return any(x in request.META.get('HTTP_USER_AGENT', '').lower() 
              for x in ['mobile', 'android', 'iphone', 'ipad'])