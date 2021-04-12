from datetime import datetime
from time import sleep
from xml.sax.saxutils import escape
import pandas as pd
from bs4 import BeautifulSoup as BS
from requests import get


class Reader:
    _data_dir = 'data/'
    _raw_fp = _data_dir + 'raw.csv'
    _transformed_fp = _data_dir + 'transformed.csv'
    _exceptions_fp = _data_dir + 'missing.csv'

    @property
    def raw(self):
        return pd.read_csv(self._raw_fp, dtype=self._dtypes)

    @property
    def _transformed(self):
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
        return ['url', 'full_url', 'title', 'description', 'download_url']


class Requester(Reader):
    def __init__(self, **kwargs):
        self._nums = kwargs.get('nums')
        self._new = []
        self._exc = []

    def make_requests(self):
        for num in self._nums:
            try:
                self._new.append(_make_one_request(num))
            except Exception as exc:
                self._exc.append({
                    'num': num,
                    'exc': str(exc),
                })
            sleep(1)

    def save_raw(self, overwrite=None):
        new = pd.DataFrame(self._new)
        df = new if overwrite else pd.concat((new, self.raw))
        df.to_csv(self._raw_fp, index=False)
        pd.DataFrame(self._exc).sort_values('num').to_csv(self._exceptions_fp, index=False)


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
        return BS(self._text, 'lxml')


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
            last_refresh=datetime.today().strftime('%Y-%m-%d %H:%M:%S'),
            missing_nums=', '.join(str(i) for i in self._exceptions.num),
            items=items_xml,
        )
        return xml_output


def _make_one_request(num):
    url = f'https://www.thisamericanlife.org/episode/{num}'
    r = get(url)
    assert r.ok
    data = {
        'num': num,
        'url': url,
        'full_url': r.url,
    }
    data.update(Episode(text=r.text).data)
    return data


def _get_latest_episode_number():
    r = get('http://feed.thisamericanlife.org/talpodcast')
    sleep(1)
    soup = BS(r.text, 'lxml')
    return int(soup.find('item').find('title').text.split(':', 1)[0])


def main():
    latest_num = _get_latest_episode_number()
    writer = Writer(nums=(latest_num,))
    if latest_num not in set(writer.raw.num):
        writer.make_requests()
        writer.save_raw()
    writer.transform_and_write()


if __name__ == '__main__':
    main()
