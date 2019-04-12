class Result(dict):
    """
    The class to structure the response xml string from the cmr API
    """
    _location = None

    def getDownloadUrl(self):
        """
        :return:
        """
        return self._location

    def getDescription(self):
        """

        :return:
        """
        return self['Granule']['GranuleUR'].ljust(70) + 'Updated ' + self['Granule']['LastUpdate'] + ' (' + self['collection-concept-id'] + ')'

class Granule(Result):
    def __init__(self, metaResult, awsAccessKey, awsAccessSecret):

        self._awsKey = awsAccessKey
        self._awsSecret = awsAccessSecret

        for k in metaResult:
            self[k] = metaResult[k]

        # Retrieve downloadable url
        try:
            self._location = self['Granule']['OnlineAccessURLs']['OnlineAccessURL']['URL']
            self._downloadname = self._location.split("/")[-1]
        except KeyError:
            self._location = None

        # Retrieve OPeNDAPUrl
        try:
            urls = self['Granule']['OnlineResources']['OnlineResource']
            self._OPeNDAPUrl = filter(lambda x: x["Type"] == "OPeNDAP", urls)['URL']
            self._BrowseUrl = filter(lambda x: x["Type"] == "BROWSE", urls)['URL']
        except :
            self._OPeNDAPUrl = None
            self._BrowseUrl = None

    def getOPeNDAPUrl(self):
        return self._OPeNDAPUrl
