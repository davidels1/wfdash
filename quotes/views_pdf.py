from django.shortcuts import get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.contrib import messages
from .models import QuoteRequest
import os
from .views import generate_quote_pdf  # Import the base function


@login_required
def generate_cnl_quote_pdf(request, quote_id):
    """Generate a CNL-branded quote PDF"""
    # Get the quote
    quote = get_object_or_404(QuoteRequest, id=quote_id)

    # Set the letterhead to CNL
    quote.company_letterhead = "CNL"
    quote.save(update_fields=["company_letterhead"])

    # Use the existing function to generate the PDF
    return generate_quote_pdf(request, quote_id)


@login_required
def generate_isherwood_quote_pdf(request, quote_id):
    """Generate an Isherwood-branded quote PDF"""
    # Get the quote
    quote = get_object_or_404(QuoteRequest, id=quote_id)

    # Set the letterhead to ISHERWOOD
    quote.company_letterhead = "ISHERWOOD"
    quote.save(update_fields=["company_letterhead"])

    # Use the existing function to generate the PDF
    return generate_quote_pdf(request, quote_id)


@login_required
def preview_cnl_quote_pdf(request, quote_id):
    """Preview CNL-branded quote PDF without saving"""
    return generate_cnl_quote_pdf(request, quote_id)


@login_required
def preview_isherwood_quote_pdf(request, quote_id):
    """Preview Isherwood-branded quote PDF without saving"""
    return generate_isherwood_quote_pdf(request, quote_id)
