def business(request):
    """Makes the current tenant available to every template as `business`."""
    return {"business": getattr(request, "business", None)}
