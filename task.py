from datetime import datetime
from time import sleep
from xml.sax.saxutils import escape

import pandas as pd
from bs4 import BeautifulSoup
from requests import Session

_DATA_DIR = 'data/'


class Episode:
    def __init__(self, **kwargs):
        self._text = kwargs.get('text')

    @property
    def data(self):
        title_section = self._soup.find('div', class_='episode-title')
        container = title_section.find_parent('div', class_='container')

        try:
            description = container.find('div', class_='field-name-body').text
        except AttributeError:
            description = ''

        data = {
            'pubdate': container.find('div', class_='meta').find('div', class_='field-name-field-radio-air-date').find(
                'span', class_='date-display-single').text,
            'title': title_section.find('h1').text,
            'description': description,
            'download_url': container.find('ul', class_='actions').find('li', class_='download').find('a').get('href'),
        }
        return data

    @property
    def _soup(self):
        return BeautifulSoup(self._text, 'lxml')


class DataReader:
    _raw_fp = _DATA_DIR + 'raw.csv'
    _transformed_fp = _DATA_DIR + 'transformed.csv'
    _exceptions_fp = _DATA_DIR + 'missing.csv'

    @property
    def raw(self):
        return pd.read_csv(self._raw_fp, dtype=self._dtypes)

    @property
    def transformed(self):
        return pd.read_csv(self._transformed_fp, dtype=self._dtypes)

    @property
    def _exceptions(self):
        return pd.read_csv(self._exceptions_fp, dtype={'num': int, 'exc': str})

    @property
    def _dtypes(self):
        return {
            'num': int,
            'title': str,
            'download_url': str,
            'description': str,
            'pubdate': str,
            'url': str,
            'full_url': str,
        }

    @property
    def _str_fields(self):
        return [key for key, value in self._dtypes.items() if value == str]


class Requester(DataReader):
    def __init__(self, **kwargs):
        self._nums = kwargs.get('nums')
        self._session = kwargs.get('session')
        self._new = []
        self._exc = []

    def make_requests(self):
        for num in self._nums:
            try:
                self._new.append(self._make_one_request(num))
            except Exception as exc:
                self._exc.append({'num': num, 'exc': str(exc)})
            sleep(1)

    def save_raw_and_exceptions(self):
        pd.concat((pd.DataFrame(self._new), self.raw)).to_csv(self._raw_fp, index=False)
        pd.DataFrame(self._exc).sort_values('num').to_csv(self._exceptions_fp, index=False)

    def _make_one_request(self, num):
        url = f'https://www.thisamericanlife.org/episode/{num}'
        r = self._session.get(url)
        assert r.ok
        data = {
            'num': num,
            'url': url,
            'full_url': r.url,
        }
        data.update(Episode(text=r.text).data)
        return data


class Writer(Requester):
    def transform_and_write(self):
        df = self._transform()
        df.to_csv(self._transformed_fp, index=False)
        xml_output = self._write_xml(df)
        open('TALArchive.xml', 'w').write(xml_output)

    def _transform(self):
        df = self.raw.copy()
        for col in self._str_fields:
            df[col] = df[col].fillna(' ').apply(lambda x: x.strip()).apply(escape).apply(
                lambda x: x.replace('\u02bc', ''))
        df.download_url = df.download_url.apply(lambda x: x.split('?', 1)[0])
        df.pubdate = df.pubdate.apply(lambda x: f'{x} 18:00:00 -0400').apply(pd.to_datetime)
        df = df.sort_values('pubdate', ascending=False)
        df.pubdate = df.pubdate.apply(lambda x: x.strftime('%a, %d %b %Y %H:%M:%S %z'))
        return df.drop_duplicates(subset=['num'])[list(self._dtypes)]

    def _write_xml(self, df):
        _read = lambda x: open(f'templates/{x}.xml').read()
        item_xml = _read('item')
        items_xml = '\n'.join((item_xml.format(**record) for record in df.to_dict('records')))
        xml_output = _read('feed').format(
            last_refresh=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
            missing_nums=', '.join(str(i) for i in self._exceptions.num),
            items=items_xml,
        )
        return xml_output


def _get_feed_episode_nums(session):
    r = session.get('http://feed.thisamericanlife.org/talpodcast')
    sleep(1)
    soup = BeautifulSoup(r.text, 'lxml')
    return {int(elem.find('title').text.split(':', 1)[0]) for elem in soup.find_all('item')}


def main():
    session = Session()

    completed = DataReader().transformed.copy()
    completed_nums = set(completed.num)
    temp_url_nums = set(completed[~completed.download_url.str.contains('thisamericanlife.org')].num)
    feed_nums = _get_feed_episode_nums(session)

    nums = set(range(1, max(completed_nums.union(feed_nums)) + 1)) - completed_nums
    nums.update(temp_url_nums - feed_nums)

    writer = Writer(nums=nums, session=session)
    if nums:
        writer.make_requests()
        writer.save_raw_and_exceptions()
    writer.transform_and_write()

    session.close()


if __name__ == '__main__':
    main()
