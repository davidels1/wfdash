def is_mobile(request):
    """Detect if request is from a mobile device"""
    user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
    mobile_agents = ['mobile', 'android', 'iphone', 'ipad', 'ipod']
    return any(agent in user_agent for agent in mobile_agents)