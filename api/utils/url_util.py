def proxied_url(request):
    return "https://{}{}".format(request.environ['HTTP_X_FORWARDED_HOST'], request.full_path)
