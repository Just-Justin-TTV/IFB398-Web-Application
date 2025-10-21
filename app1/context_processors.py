def theme_context(request):
    """Makes theme available in ALL templates"""
    return {
        'current_theme': request.session.get('theme', 'light')
    }