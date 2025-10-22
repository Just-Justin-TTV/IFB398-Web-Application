# app1/context_processors.py

def theme_context(request):
    """
    Add theme context to all templates.
    
    This context processor retrieves the user's selected theme from the session.
    If no theme is set in the session, it defaults to 'light'.
    The returned context can be used in templates to apply the current theme.
    """
    # Retrieve the current theme from the session; default to 'light' if not set
    current_theme = request.session.get('user_theme', 'light')
    
    # Return context dictionary containing the current theme
    return {
        'current_theme': current_theme,  # Theme used in templates
        'user_theme': current_theme,     # Duplicate key for backward compatibility
    }


def accessibility_settings(request):
    """
    Add accessibility settings to templates.
    
    This context processor provides user accessibility preferences such as theme and text size.
    Currently, text size is set to 'normal' by default.
    """
    return {
        'user_theme': request.session.get('user_theme', 'light'),  # User-selected theme
        'user_text_size': 'normal',                                # Default text size for accessibility
    }
