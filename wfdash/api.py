from django.http import JsonResponse
from django.db.models import Q
from django.contrib.auth.decorators import login_required
from .models import Company

@login_required
def company_search(request):
    """API endpoint for searching companies via Select2"""
    query = request.GET.get('q', '')
    if not query or len(query) < 2:
        return JsonResponse({'results': []})
    
    companies = Company.objects.filter(
        Q(company__icontains=query) | 
        Q(address__icontains=query)
    ).values('id', 'company', 'address')[:20]
    
    results = [
        {
            'id': c['id'], 
            'text': c['company'],  # Select2 expects 'text' as the display field
            'address': c['address']
        } 
        for c in companies
    ]
    
    return JsonResponse({'results': results})