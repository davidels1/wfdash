from PIL import Image, ImageEnhance, ImageFilter
import io
import os
from django.core.files.base import ContentFile
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.utils import timezone
from .models import DeliveryNote
from .forms import UploadSignatureForm
from .image_utils import enhance_document_image
from .pdf_utils import generate_delivery_pdf


def enhance_document_image(document_file):
    """
    Simple and robust document image enhancement with strong effects
    """
    try:
        # Save original position
        original_position = document_file.tell()
        document_file.seek(0)

        # Create a solid temporary copy of the file
        temp_copy = io.BytesIO(document_file.read())

        # Reset the file position for any further operations
        document_file.seek(original_position)

        # Open image from the in-memory copy
        img = Image.open(temp_copy)

        # Convert to RGB if needed
        if img.mode != "RGB":
            img = img.convert("RGB")

        # Print dimensions for debugging
        width, height = img.size
        print(f"Processing image: {width}x{height}")

        # Apply VERY strong enhancements for clearly visible results

        # 1. Very strong contrast (makes text much darker)
        contrast = ImageEnhance.Contrast(img)
        img = contrast.enhance(2.5)  # Extremely high contrast

        # 2. Increase brightness to make paper whiter
        brightness = ImageEnhance.Brightness(img)
        img = brightness.enhance(1.6)  # Very bright

        # 3. Increase color saturation slightly
        color = ImageEnhance.Color(img)
        img = color.enhance(1.2)

        # 4. Apply multiple sharpening passes
        for _ in range(2):
            img = img.filter(ImageFilter.SHARPEN)

        # 5. Save with high quality
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=95)
        buffer.seek(0)

        # Create new filename with enhanced suffix
        original_name = os.path.basename(document_file.name)
        filename_parts = os.path.splitext(original_name)
        new_name = f"{filename_parts[0]}_enhanced{filename_parts[1]}"

        print(f"Enhanced image created: {new_name}")

        # Return as ContentFile
        return ContentFile(buffer.getvalue(), name=new_name)

    except Exception as e:
        print(f"Document enhancement error: {str(e)}")
        # If enhancement fails, reset file position and return original
        try:
            document_file.seek(0)
        except:
            pass
        return document_file


@login_required
def upload_signed_document(request, pk):
    delivery = get_object_or_404(DeliveryNote, pk=pk)

    if request.method == "POST":
        form = UploadSignatureForm(request.POST, request.FILES, instance=delivery)
        if form.is_valid():
            try:
                # Get values from the form
                signed_document = request.FILES.get("signed_document")
                signed_by = form.cleaned_data["signed_by"]
                customer_order_number = form.cleaned_data.get(
                    "customer_order_number", ""
                )

                # Only enhance if it's an image file
                if signed_document:
                    file_ext = os.path.splitext(signed_document.name)[1].lower()

                    print(f"Received file: {signed_document.name} ({file_ext})")
                    print(f"File size: {signed_document.size} bytes")

                    if file_ext in [".jpg", ".jpeg", ".png"]:
                        try:
                            # Import the enhancement function directly here for clarity
                            from .image_utils import enhance_document_image

                            print("Starting image enhancement...")
                            enhanced_document = enhance_document_image(signed_document)
                            print(
                                f"Enhancement complete, new file size: {enhanced_document.size} bytes"
                            )

                            # Store original and enhanced files for comparison
                            delivery.signed_document = enhanced_document

                            # Debug message
                            print(
                                f"Enhanced document assigned to delivery: {enhanced_document.name}"
                            )
                        except Exception as enhance_error:
                            print(f"Image enhancement error: {str(enhance_error)}")
                            # Fall back to original if enhancement fails
                            delivery.signed_document = signed_document
                    else:
                        # For non-image files, use as-is
                        delivery.signed_document = signed_document

                # Update other fields
                delivery.signed_by = signed_by
                delivery.customer_order_number = customer_order_number
                delivery.signature_date = timezone.now()
                delivery.status = "signed"

                # Set digital_signature to empty string to avoid NULL issues
                if not delivery.digital_signature:
                    delivery.digital_signature = ""

                delivery.save()
                print(
                    f"Delivery saved with signed document: {delivery.signed_document.name}"
                )

                # Generate a new PDF without including the signature image
                # (since it's a separate file)
                generate_delivery_pdf(request, pk, include_signature=False)

                messages.success(
                    request,
                    f"Signed document uploaded successfully. Signed by: {signed_by or 'Unknown'}",
                )
                return redirect("delivery_notes:detail", pk=delivery.pk)

            except Exception as e:
                import traceback

                print(f"Error uploading document: {str(e)}")
                print(traceback.format_exc())
                messages.error(request, f"Error uploading document: {str(e)}")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")

    # For GET request, show the upload form
    context = {"form": UploadSignatureForm(), "delivery": delivery}
    return render(request, "delivery_notes/upload_signature.html", context)
