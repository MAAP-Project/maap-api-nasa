def proxied_url(request, base_url=False):
    http_x_forwarded_host = 'HTTP_X_FORWARDED_HOST'

    # If running in a container, use the environ header for determining the host
    if http_x_forwarded_host in request.environ:
        return "https://{}{}".format(request.environ[http_x_forwarded_host], '' if base_url else request.full_path)
    else:
        return request.base_url if base_url else request.url
