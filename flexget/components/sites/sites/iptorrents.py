import re
from urllib.parse import quote_plus

from loguru import logger

from flexget import plugin
from flexget.components.sites.urlrewriting import UrlRewritingError
from flexget.components.sites.utils import normalize_unicode, torrent_availability
from flexget.config_schema import one_or_more
from flexget.entry import Entry
from flexget.event import EventType, event
from flexget.utils import requests
from flexget.utils.soup import get_soup
from flexget.utils.tools import parse_filesize

logger = logger.bind(name='iptorrents')

CATEGORIES = {
    # All
    'All': '',
    # Movies
    'Movie-all': 72,
    'Movie-3D': 87,
    'Movie-480p': 77,
    'Movie-4K': 101,
    'Movie-BD-R': 89,
    'Movie-BD-Rip': 90,
    'Movie-Cam': 96,
    'Movie-DVD-R': 6,
    'Movie-HD-Bluray': 48,
    'Movie-Kids': 54,
    'Movie-MP4': 62,
    'Movie-Non-English': 38,
    'Movie-Packs': 68,
    'Movie-Web-DL': 20,
    'Movie-x265': 100,
    'Movie-XviD': 7,
    # TV
    'TV-all': 73,
    'TV-Documentaries': 26,
    'TV-Sports': 55,
    'TV-480p': 78,
    'TV-BD': 23,
    'TV-DVD-R': 24,
    'TV-DVD-Rip': 25,
    'TV-Mobile': 66,
    'TV-Non-English': 82,
    'TV-Packs': 65,
    'TV-Packs-Non-English': 83,
    'TV-SD-x264': 79,
    'TV-x264': 5,
    'TV-x265': 99,
    'TV-XVID': 4,
    'TV-Web-DL': 22,
}

BASE_URL = 'https://iptorrents.com'


class UrlRewriteIPTorrents:
    """
        IpTorrents urlrewriter and search plugin.

        iptorrents:
          rss_key: xxxxxxxxx  (required)
          uid: xxxxxxxx  (required)
          password: xxxxxxxx  (required)
          category: HD

          Category is any combination of: Movie-all, Movie-3D, Movie-480p,
          Movie-4K, Movie-BD-R, Movie-BD-Rip, Movie-Cam, Movie-DVD-R,
          Movie-HD-Bluray, Movie-Kids, Movie-MP4, Movie-Non-English,
          Movie-Packs, Movie-Web-DL, Movie-x265, Movie-XviD,

          TV-all, TV-Documentaries, TV-Sports, TV-480p, TV-BD, TV-DVD-R,
          TV-DVD-Rip, TV-MP4, TV-Mobile, TV-Non-English, TV-Packs,
          TV-Packs-Non-English, TV-SD-x264, TV-x264, TV-x265, TV-XVID, TV-Web-DL
    """

    schema = {
        'type': 'object',
        'properties': {
            'rss_key': {'type': 'string'},
            'uid': {'oneOf': [{'type': 'integer'}, {'type': 'string'}]},
            'password': {'type': 'string'},
            'category': one_or_more(
                {'oneOf': [{'type': 'integer'}, {'type': 'string', 'enum': list(CATEGORIES)}]}
            ),
        },
        'required': ['rss_key', 'uid', 'password'],
        'additionalProperties': False,
    }

    # urlrewriter API
    def url_rewritable(self, task, entry):
        url = entry['url']
        if url.startswith(BASE_URL + '/download.php/'):
            return False
        if url.startswith(BASE_URL + '/'):
            return True
        return False

    # urlrewriter API
    def url_rewrite(self, task, entry):
        if 'url' not in entry:
            logger.error("Didn't actually get a URL...")
        else:
            logger.debug('Got the URL: {}', entry['url'])
        if entry['url'].startswith(BASE_URL + '/t?'):
            # use search
            results = self.search(task, entry)
            if not results:
                raise UrlRewritingError("No search results found")
            # TODO: Search doesn't enforce close match to title, be more picky
            entry['url'] = results[0]['url']

    @plugin.internet(logger)
    def search(self, task, entry, config=None):
        """
        Search for name from iptorrents
        """

        categories = config.get('category', 'All')
        # Make sure categories is a list
        if not isinstance(categories, list):
            categories = [categories]

        # If there are any text categories, turn them into their id number
        categories = [c if isinstance(c, int) else CATEGORIES[c] for c in categories]
        filter_url = '&'.join((str(c) + '=') for c in categories)

        entries = set()

        for search_string in entry.get('search_strings', [entry['title']]):
            query = normalize_unicode(search_string)
            query = quote_plus(query.encode('utf8'))

            url = "{base_url}/t?{filter}&q={query}&qf=".format(
                base_url=BASE_URL, filter=filter_url, query=query
            )
            logger.debug('searching with url: {}', url)
            req = requests.get(
                url, cookies={'uid': str(config['uid']), 'pass': config['password']}
            )

            if '/u/' + str(config['uid']) not in req.text:
                raise plugin.PluginError("Invalid cookies (user not logged in)...")

            soup = get_soup(req.content, parser="html.parser")
            torrents = soup.find('table', {'id': 'torrents'})

            results = torrents.findAll('tr')
            for torrent in results:
                if torrent.th and 'ac' in torrent.th.get('class'):
                    # Header column
                    continue
                if torrent.find('td', {'colspan': '99'}):
                    logger.debug('No results found for search {}', search_string)
                    break
                entry = Entry()
                link = torrent.find('a', href=re.compile('download'))['href']
                entry['url'] = "{base}{link}?torrent_pass={key}".format(
                    base=BASE_URL, link=link, key=config.get('rss_key')
                )
                entry['title'] = torrent.find('a', href=re.compile('details')).text

                seeders = torrent.findNext('td', {'class': 'ac t_seeders'}).text
                leechers = torrent.findNext('td', {'class': 'ac t_leechers'}).text
                entry['torrent_seeds'] = int(seeders)
                entry['torrent_leeches'] = int(leechers)
                entry['torrent_availability'] = torrent_availability(
                    entry['torrent_seeds'], entry['torrent_leeches']
                )

                size = torrent.findNext(text=re.compile(r'^([\.\d]+) ([GMK]?)B$'))
                size = re.search(r'^([\.\d]+) ([GMK]?)B$', size)

                entry['content_size'] = parse_filesize(size.group(0))
                logger.debug('Found entry {}', entry)
                entries.add(entry)

        return entries


@event(EventType.plugin__register)
def register_plugin():
    plugin.register(
        UrlRewriteIPTorrents, 'iptorrents', interfaces=['urlrewriter', 'search'], api_ver=2
    )
