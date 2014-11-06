"""
HTTP-based download of files.
"""

import re
import requests
import logging
from contextlib import closing
import feedparser
from lxml import etree
from urlparse import urljoin

from . import DataSource, fetch_file, RemoteFetchException


_log = logging.getLogger(__name__)


def filename_from_url(url):
    """
    Get the filename component of the URL

    >>> filename_from_url('http://example.com/somefile.zip')
    'somefile.zip'
    >>> filename_from_url('http://oceandata.sci.gsfc.nasa.gov/Ancillary/LUTs/modis/utcpole.dat')
    'urcpole.dat'
    """
    return url.split('/')[-1]


def _fetch_file(target_dir, target_name, reporter, url, override_existing=False, filename_transform=None):
    """
    Fetch the given URL to the target folder.

    :type target_dir: str
    :type target_name: str
    :type reporter: FetchReporter
    :type url: str
    """

    def do_fetch(t):
        """Fetch data to filename t"""
        with closing(requests.get(url, stream=True)) as res:
            if res.status_code != 200:
                body = res.text
                _log.debug('Received text %r', res.text)
                reporter.file_error(url, "Status code %r" % res.status_code, body)
                return

            with open(t, 'wb') as f:
                for chunk in res.iter_content(4096):
                    if chunk:
                        f.write(chunk)
                        f.flush()

    fetch_file(
        url,
        do_fetch,
        reporter,
        target_name,
        target_dir,
        filename_transform=filename_transform,
        override_existing=override_existing
    )


class HttpSource(DataSource):
    """
    Fetch static HTTP URLs.

    This is useful for unchanging URLs that need to be
    repeatedly updated.
    """

    def __init__(self, urls, target_dir):
        """
        :type urls: list of str
        :type target_dir: str
        :return:
        """
        super(HttpSource, self).__init__()

        self.urls = urls
        self.target_dir = target_dir

    def trigger(self, reporter):
        """
        Download all URLs, overriding existing.
        :type reporter: FetchReporter
        :return:
        """
        for url in self.urls:
            name = filename_from_url(url)
            _fetch_file(self.target_dir, name, reporter, url, override_existing=True)


class HttpListingSource(DataSource):
    """
    Fetch files from a HTTP listing page.

    A pattern can be supplied to limit files by filename.
    """

    def __init__(self, url, target_dir, name_pattern='.*', filename_transform=None):
        super(HttpListingSource, self).__init__()

        self.url = url
        self.name_pattern = name_pattern
        self.target_dir = target_dir
        self.filename_transform = filename_transform

    def trigger(self, reporter):
        """
        Download the given listing page, and any links that match the name pattern.
        """
        res = requests.get(self.url)
        if res.status_code == 404:
            _log.debug("Listing page doesn't exist yet. Skipping.")
            return

        if res.status_code != 200:
            # We don't bother with reporter.file_error() as this initial fetch is critical.
            # Throw an exception instead.
            raise RemoteFetchException(
                "Status code %r" % res.status_code,
                '{url}\n\n{body}'.format(url=self.url, body=res.text)
            )

        page = etree.fromstring(res.text, parser=etree.HTMLParser())
        url = res.url

        anchors = page.xpath('//a')

        for anchor in anchors:
            # : :type: str
            name = anchor.text
            source_url = urljoin(url, anchor.attrib['href'])

            if not anchor.attrib['href'].endswith(name):
                _log.info('Not a filename %r, skipping.', name)
                continue

            if not re.match(self.name_pattern, name):
                _log.info("Filename (%r) doesn't match pattern, skipping.", name)
                continue

            _fetch_file(
                self.target_dir,
                name,
                reporter,
                source_url,
                filename_transform=self.filename_transform
            )


class RssSource(DataSource):
    """
    Fetch any files from the given RSS URL.

    The title of feed entries is assumed to be the filename.
    """

    def __init__(self, url, target_dir, filename_transform=None):
        """
        :type url: str
        :type target_dir: str
        :type filename_transform: FilenameTransform
        :return:
        """
        super(RssSource, self).__init__()

        self.url = url
        self.target_dir = target_dir

        self.filename_transform = filename_transform

    def trigger(self, reporter):
        """
        Download RSS feed and fetch missing files.
        """
        # Fetch feed.
        res = requests.get(self.url)

        if res.status_code != 200:
            # We don't bother with reporter.file_error() as this initial fetch is critical.
            # Throw an exception instead.
            raise RemoteFetchException(
                "Status code %r" % res.status_code,
                '{url}\n\n{body}'.format(url=self.url, body=res.text)
            )

        feed = feedparser.parse(res.text)

        for entry in feed.entries:
            name = entry.title
            url = entry.link

            _fetch_file(
                self.target_dir,
                name,
                reporter,
                url,
                filename_transform=self.filename_transform
            )



