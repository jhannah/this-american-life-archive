import datetime
from time import sleep
from xml.sax.saxutils import escape

import pandas as pd
from bs4 import BeautifulSoup
from requests import Session


class Episode:
    def __init__(self, text: str):
        self._text = text

    @property
    def data(self) -> dict:
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
    def _soup(self) -> BeautifulSoup:
        return BeautifulSoup(self._text, 'lxml')


class TALScraper:
    def __init__(self, **kwargs) -> None:
        self.session: Session = kwargs.get('session')
        self._refresh_old_episodes: bool = kwargs.get('refresh_old_episodes')

        self._raw_fp = 'data/raw.csv'
        self._transformed_fp = 'data/transformed.csv'
        self._missing_fp = 'data/missing.csv'
        self.nums = None
        self._new = []
        self._exc = []

    def get_nums_to_request(self) -> None:
        completed_episode_nums = set(self.transformed.num)

        if self._refresh_old_episodes:
            self.nums = completed_episode_nums
            return

        episode_nums_from_feed = self._get_feed_episode_nums()
        self.nums = set(episode_nums_from_feed - completed_episode_nums)
        return

    def make_requests(self):
        for num in self.nums:
            try:
                self._new.append(self._make_one_request(num))
            except Exception as exc:
                exc_str = str(exc).strip()
                if exc_str:
                    self._exc.append({'num': num, 'exc': exc_str})
            sleep(1)

    def save_raw_and_missing(self):
        new_raw = pd.concat((pd.DataFrame(self._new), self.raw))
        new_raw = new_raw.drop_duplicates(subset=['num', 'download_url'], keep='first')
        new_raw.to_csv(self._raw_fp, index=False)

        exc_df = pd.DataFrame(self._exc).sort_values('num') if self._exc else pd.DataFrame(columns=['num', 'exc'])
        exc_df.to_csv(self._missing_fp, index=False)

    def transform_and_write(self):
        df = self._transform()
        df.to_csv(self._transformed_fp, index=False)
        xml_output = self._write_xml(df)
        open('TALArchive.xml', 'w', encoding='utf8').write(xml_output)

    def _get_feed_episode_nums(self) -> set:
        url = 'http://feed.thisamericanlife.org/talpodcast'
        print(f"Fetching {url}")
        r = self.session.get(url)
        sleep(1)
        soup = BeautifulSoup(r.text, 'lxml-xml')
        all_nums = set()
        for elem in soup.find_all('item'):
            num = elem.find('title').text.split(':', 1)[0]
            if str(num).isdigit():
                all_nums.add(int(num))
        return all_nums

    def _make_one_request(self, num: int) -> dict:
        url = f'https://www.thisamericanlife.org/episode/{num}'
        print(f"Fetching {url}")
        r = self.session.get(url)
        assert r.ok
        data = {
            'num': num,
            'url': url,
            'full_url': r.url,
        }
        data.update(Episode(text=r.text).data)
        return data

    def _transform(self) -> pd.DataFrame:
        df = self.raw.copy()
        df = df.drop_duplicates(subset=['num'], keep='first')
        for col in self._str_fields:
            df[col] = df[col].fillna(' ').apply(lambda x: x.strip()).apply(escape).apply(
                lambda x: x.replace('\u02bc', ''))
        df.download_url = df.download_url.apply(lambda x: x.split('?', 1)[0])
        df.pubdate = df.pubdate.apply(lambda x: f'{x} 18:00:00 -0400').apply(pd.to_datetime)
        df = df.sort_values('pubdate', ascending=False)
        df.pubdate = df.pubdate.apply(lambda x: x.strftime('%a, %d %b %Y %H:%M:%S %z'))
        return df[list(self._dtypes)]

    def _write_xml(self, df: pd.DataFrame) -> str:
        _read = lambda x: open(f'templates/{x}.xml').read()
        item_xml = _read('item')
        items_xml = '\n'.join((item_xml.format(**record) for record in df.to_dict('records')))
        xml_output = _read('feed').format(
            last_refresh=datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%d %H:%M:%S'),
            missing_nums=', '.join(str(i) for i in self._missing.num),
            items=items_xml,
        )
        return xml_output

    @property
    def raw(self) -> pd.DataFrame:
        return pd.read_csv(self._raw_fp, dtype=self._dtypes)

    @property
    def transformed(self) -> pd.DataFrame:
        return pd.read_csv(self._transformed_fp, dtype=self._dtypes)

    @property
    def _missing(self) -> pd.DataFrame:
        return pd.read_csv(self._missing_fp, dtype={'num': int, 'exc': str})

    @property
    def _dtypes(self) -> dict:
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
    def _str_fields(self) -> list:
        return [key for key, value in self._dtypes.items() if value == str]


def main():
    scraper = TALScraper(refresh_old_episodes=True)
    scraper.session = Session()
    scraper.get_nums_to_request()
    if scraper.nums:
        scraper.make_requests()
        scraper.save_raw_and_missing()
    scraper.transform_and_write()
    scraper.session.close()


if __name__ == '__main__':
    main()
