class TenantMiddleware:
    """
    Sets `request.business` to the logged-in user's Business, or None.

    The tenant always comes from the authenticated user on the server, never
    from a URL, form field or cookie the browser could change.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        request.business = None
        if user is not None and user.is_authenticated and user.is_business_user:
            request.business = user.business
        return self.get_response(request)
