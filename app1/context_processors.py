from django.contrib.auth import get_user_model
User = get_user_model()

from .models import UserProfile

def theme_context(request):
    current_theme = request.session.get('theme', 'light')
    return {
        'current_theme': current_theme
    }

def accessibility_settings(request):
    if request.user.is_authenticated:
        try:
            profile = UserProfile.objects.get(user=request.user)
            return {
                'user_theme': profile.theme,
                'user_text_size': profile.text_size,
            }
        except UserProfile.DoesNotExist:
            # Create profile if it doesn't exist
            profile = UserProfile.objects.create(user=request.user)
            return {
                'user_theme': profile.theme,
                'user_text_size': profile.text_size,
            }
    return {
        'user_theme': 'light',
        'user_text_size': 'normal',
    }