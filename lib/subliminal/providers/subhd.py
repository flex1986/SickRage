# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import sys, os

import io
import zipfile
import logging
import babelfish
import requests
import urllib
import simplejson as json
import guessit
import rarfile
from lxml import html
from . import Provider
from .. import __version__
from ..exceptions import ProviderError
from ..subtitle import Subtitle, fix_line_endings, compute_guess_matches
from ..video import Episode, Movie


logger = logging.getLogger(__name__)


class SubHDSubtitle(Subtitle):
    provider_name = 'subhd'

    def __init__(self, language, series, season, episode, movie, year, subber, release, url):  # @ReservedAssignment
        super(SubHDSubtitle, self).__init__(language)
        self.series = series
        self.season = season
        self.episode = episode
        self.movie = movie
        self.year = year
        self.release = release
        self.url = url
        self.subber = subber
        self.hash = 'subhd'

    def compute_matches(self, video):
        matches = set()
        # episode
        if isinstance(video, Episode):
            # series
            if video.series and self.series.lower() == video.series.lower():
                matches.add('series')
            # season
            if video.season and self.season == video.season:
                matches.add('season')
            # episode
            if video.episode and self.episode == video.episode:
                matches.add('episode')
            # guess
            matches |= compute_guess_matches(video, guessit.guess_episode_info(self.release + '.mkv'))
        elif isinstance(video, Movie):
            if video.year and self.year == video.year:
                matches.add('year')

            if video.title and self.movie == video.title:
                matches.add('title')

            # guess
            matches |= compute_guess_matches(video, guessit.guess_movie_info(self.release + '.mkv'))
        else:
            logger.info('%r is not a valid movie_kind for %r', self.movie_kind, video)
            return matches

        if self.subber and "yyets" in self.subber.lower():
            matches.add("yyets")
            
        return matches


class SubHDProvider(Provider):
    languages = {babelfish.Language.fromalpha2(l) for l in ['zh']}
    #required_hash = 'subhd'

    def initialize(self):
        self.session = requests.Session()
        self.session.headers = {'User-Agent': 'SubDB/1.0 (subliminal/%s; https://github.com/Diaoul/subliminal)' %
                                __version__.split('-')[0]}

    def terminate(self):
        self.session.close()

    def get(self, video):
        """Make a GET request on the server with the given parameters

        :param params: params of the request
        :return: the response
        :rtype: :class:`requests.Response`

        """
        params = ""
        if isinstance(video, Episode):
            params = video.series

            if video.year != None:
                params = params + " (" + str(video.year) + ")"

            params = params + " S"
            if video.season < 10:
                params = params + "0" + str(video.season)
            else:
                params = params + "" + str(video.season)

            params = params + "E"
            if video.episode < 10:
                params = params + "0" + str(video.episode)
            else:
                params = params + "" + str(video.episode)
        elif isinstance(video, Movie):
            params = video.title

            if video.year != None:
                params = params + " (" + str(video.year) + ")"

        return self.session.get("http://subhd.com/search/" + urllib.quote_plus(params))

    def post(self, params):
        return self.session.post("http://subhd.com/ajax/down_ajax", params)

    def query(self, video):
        logger.debug('Searching subtitles %r', video)
        r = self.get(video)
        if r.status_code != 200:
            raise ProviderError('Request failed with status code %d' % r.status_code)

        subtitles = []
        tree = html.fromstring(r.text)

        elements = tree.xpath('//div[@class="box"]')
        for element in elements:
            s_url = str(element.xpath('.//div[@class="d_title"]/a')[0].attrib['href'])
            s_release = element.xpath('.//span[@data-toggle="tooltip"]')[0].attrib['title']
            s_subber = element.xpath('.//div[@class="d_zu"]/a')[0].text if len(element.xpath('.//div[@class="d_zu"]/a')) > 0 else ""
            
            if isinstance(video, Episode):
                subtitles.append(SubHDSubtitle(babelfish.Language.fromalpha2('zh'), video.series , video.season, video.episode, None, None, s_subber, s_release, s_url))
            elif isinstance(video, Movie):
                subtitles.append(SubHDSubtitle(babelfish.Language.fromalpha2('zh'), None , None, None, video.title, video.year, s_subber, s_release, s_url))


        return reversed(subtitles)

    def list_subtitles(self, video, languages):
        return [s for s in self.query(video) if s.language in languages]

    def download_subtitle(self, subtitle):
        sid = subtitle.url.split('/')[-1]

        r = self.post({'sub_id': sid})
        data = json.loads(r.text)

        r = self.session.get(data['url'], timeout=60)

        if r.status_code != 200:
           raise ProviderError('Request failed with status code %d' % r.status_code)

        if data['url'].endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                for subfile in zf.namelist():
                    if subfile.endswith('简体.srt') or subfile.endswith('chs.srt'):
                        subtitle.content = fix_line_endings(zf.read(subfile))
        elif data['url'].endswith('.rar'):
            with rarfile.RarFile(io.BytesIO(r.content)) as rf:
                for subfile in rf.namelist():
                    if subfile.endswith('简体.srt') or subfile.endswith('chs.srt'):
                        subtitle.content = fix_line_endings(rf.read(subfile))
        else:
            raise ProviderError(data['url'])


