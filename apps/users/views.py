from django.shortcuts import render, redirect, get_object_or_404
from apps.users.models import Profile
from apps.users.forms import ProfileForm, QuillFieldForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password
from django.contrib import messages

# Create your views here.



@login_required(login_url='/accounts/login-v1/')
def profile(request):
    return render(request, 'users/profile.html', {
        'segment': 'profile'
    })


def upload_avatar(request):
    profile = get_object_or_404(Profile, user=request.user)
    if request.method == 'POST':
        profile.avatar = request.FILES.get('avatar')
        profile.save()
        messages.success(request, 'Avatar uploaded successfully')
    return redirect(request.META.get('HTTP_REFERER'))


def change_password(request):
    user = request.user
    if request.method == 'POST':
        new_password = request.POST.get('new_password')
        confirm_new_password = request.POST.get('confirm_new_password')

        if new_password == confirm_new_password:
            if check_password(request.POST.get('current_password'), user.password):
                user.set_password(new_password)
                user.save()
                messages.success(request, 'Password changed successfully')
            else:
                messages.error(request, "Old password doesn't match!")
        else:
            messages.error(request, "Password doesn't match!")

    return redirect(request.META.get('HTTP_REFERER'))


@login_required
def change_mode(request):
    # Get current mode from session or default to 'light'
    current_mode = request.session.get('color_mode', 'light')
    
    # Toggle the mode
    new_mode = 'dark' if current_mode == 'light' else 'light'
    request.session['color_mode'] = new_mode
    
    # Redirect back to previous page
    return redirect(request.META.get('HTTP_REFERER', '/'))