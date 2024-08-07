"""
flask_cas.cas_urls

Functions for creating urls to access CAS.
"""

try:
    from urllib import quote
    from urllib import urlencode
    from urlparse import urljoin
except ImportError:
    from urllib.parse import quote
    from urllib.parse import urljoin
    from urllib.parse import urlencode


def create_url(base, path=None, *query):
    """ Create a url.

    Creates a url by combining base, path, and the query's list of
    key/value pairs. Escaping is handled automatically. Any
    key/value pair with a value that is None is ignored.

    Keyword arguments:
    base -- The left most part of the url (ex. http://localhost:5000).
    path -- The path after the base (ex. /foo/bar).
    query -- A list of key value pairs (ex. [('key', 'value')]).

    Example usage:
    >>> create_url(
    ...     'http://localhost:5000',
    ...     'foo/bar',
    ...     ('key1', 'value'),
    ...     ('key2', None),     # Will not include None
    ...     ('url', 'http://example.com'),
    ... )
    'http://localhost:5000/foo/bar?key1=value&url=http%3A%2F%2Fexample.com'
    """
    url = base
    # Add the path to the url if it's not None.
    if path is not None:
        url = urljoin(url, quote(path))
    # Remove key/value pairs with None values.
    query = filter(lambda pair: pair[1] is not None, query)
    # Add the query string to the url
    url = urljoin(url, '?{0}'.format(urlencode(list(query))))
    return url


def create_cas_login_url(cas_url, cas_route, service, renew=None, gateway=None):
    """ Create a CAS login URL .

    Keyword arguments:
    cas_url -- The url to the CAS (ex. https://auth.maap.gov)
    cas_route -- The route where the CAS lives on server (ex. /cas)
    service -- (ex.  http://localhost:5000/login)
    renew -- "true" or "false"
    gateway -- "true" or "false"

    Example usage:
    >>> create_cas_login_url(
    ...     'https://auth.maap.gov',
    ...     '/cas',
    ...     'http://localhost:5000',
    ... )
    'https://auth.maap.gov/cas?service=http%3A%2F%2Flocalhost%3A5000'
    """
    return create_url(
        cas_url,
        cas_route,
        ('service', service),
        ('renew', renew),
        ('gateway', gateway),
    )


def create_cas_validate_url(cas_url, service, ticket, renew=None):
    """ Create a CAS validate URL.
    Keyword arguments:
    cas_url -- The url to the CAS (ex. http://sso.pdx.edu)
    service -- (ex.  http://localhost:5000/login)
    ticket -- (ex. 'ST-58274-x839euFek492ou832Eena7ee-cas')
    renew -- "true" or "false"
    Example usage:
    >>> create_cas_validate_url(
    ...     'https://auth.maap.gov',
    ...     'http://localhost:5000/login',
    ...     'ST-58274-x839euFek492ou832Eena7ee-cas'
    ... )
    'https://auth.maap.gov/cas/validate?service=http%3A%2F%2Flocalhost%3A5000%2Flogin&ticket=ST-58274-x839euFek492ou832Eena7ee-cas'
    """
    return create_url(
        cas_url,
        '/cas/validate',
        ('service', service),
        ('ticket', ticket),
        ('renew', renew),
    )


def create_cas_proxy_url(cas_url, service, pgt):
    """ Create a CAS proxy URL .

    Keyword arguments:
    cas_url -- The url to the CAS (ex. https://auth.maap.gov)
    service -- (ex.  http://localhost:5000/login)
    pgt -- Proxy Granting Ticket (ex.  PGT-25-0PsmxLE116FbmfZEAO2UV0Wxu4Bb5rz1BCWOoidCKa-nkUTcjfVVbyCOc...)

    Example usage:
    >>> create_cas_proxy_url(
    ...     'https://auth.maap.gov',
    ...     'http://localhost:5000',
    ...     'PGT-25-0PsmxLE116FbmfZEAO2UV0Wxu4Bb5rz1BCWOoidCKa-nkUTcjfVVbyCOc',
    ... )
    'https://auth.maap.gov/cas/proxy?targetService=http%3A%2F%2Flocalhost%3A5000&pgt=PGT-25-0PsmxLE116FbmfZEAO2UV0Wxu4Bb5rz1BCWOoidCKa-nkUTcjfVVbyCOc'
    """
    return create_url(
        cas_url,
        '/cas/proxy',
        ('targetService', service),
        ('pgt', pgt),
    )


def create_cas_proxy_validate_url(cas_url, service, ticket):
    """ Create a CAS proxy Validate URL .

    Keyword arguments:
    cas_url -- The url to the CAS (ex. https://auth.maap.gov)
    service -- (ex.  http://localhost:5000/login)
    ticket -- Proxy Ticket (ex.  PT-32-GHExXMJ6XGrE-qF21...)

    Example usage:
    >>> create_cas_proxy_validate_url(
    ...     'https://auth.maap.gov',
    ...     'http://localhost:5000',
    ...     'PT-32-GHExXMJ6XGrE-qF21',
    ... )
    'https://auth.maap.gov/cas/p3/proxyValidate?service=http%3A%2F%2Flocalhost%3A5000&ticket=PT-32-GHExXMJ6XGrE-qF21'
    """
    return create_url(
        cas_url,
        '/cas/p3/proxyValidate',
        ('service', service),
        ('ticket', ticket),
    )


def create_cas_logout_url(cas_url, cas_route, service=None):
    """ Create a CAS logout URL.

    Keyword arguments:
    cas_url -- The url to the CAS (ex. http://sso.pdx.edu)
    cas_route -- The route where the CAS lives on server (ex. /cas/logout)
    url -- (ex.  http://localhost:5000/login)

    Example usage:
    >>> create_cas_logout_url(
    ...     'http://sso.pdx.edu',
    ...     '/cas/logout',
    ...     'http://localhost:5000',
    ... )
    'http://sso.pdx.edu/cas/logout?service=http%3A%2F%2Flocalhost%3A5000'
    """
    return create_url(
        cas_url,
        cas_route,
        ('service', service),
    )


def create_cas_validate_url(cas_url, cas_route, service, ticket,
                            renew=None):
    """ Create a CAS validate URL.

    Keyword arguments:
    cas_url -- The url to the CAS (ex. http://sso.pdx.edu)
    cas_route -- The route where the CAS lives on server (ex. /cas/serviceValidate)
    service -- (ex.  http://localhost:5000/login)
    ticket -- (ex. 'ST-58274-x839euFek492ou832Eena7ee-cas')
    renew -- "true" or "false"

    Example usage:
    >>> create_cas_validate_url(
    ...     'http://sso.pdx.edu',
    ...     '/cas/serviceValidate',
    ...     'http://localhost:5000/login',
    ...     'ST-58274-x839euFek492ou832Eena7ee-cas'
    ... )
    'http://sso.pdx.edu/cas/serviceValidate?service=http%3A%2F%2Flocalhost%3A5000%2Flogin&ticket=ST-58274-x839euFek492ou832Eena7ee-cas'
    """
    return create_url(
        cas_url,
        cas_route,
        ('service', service),
        ('ticket', ticket),
        ('renew', renew),
    )