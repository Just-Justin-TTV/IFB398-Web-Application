# app1/context_processors.py
def theme_context(request):
    """
    Add theme context to all templates
    """
    current_theme = request.session.get('user_theme', 'light')
    return {
        'current_theme': current_theme,
        'user_theme': current_theme,
    }  

def accessibility_settings(request):
    """
    Add accessibility settings to templates
    """
    return {
        'user_theme': request.session.get('user_theme', 'light'),
        'user_text_size': 'normal',
    }