import os
import re
import codecs
import io
import csv
from subprocess import Popen, PIPE, run
from inspect import getmembers

from lxml import etree, builder, html
from lxml.cssselect import CSSSelector
from lxml.html import builder as html_builder
from urllib.request import Request, urlopen
import json

import logging
import logging.handlers
from datetime import datetime

# from collections import defaultdict

"""
>>> import novelfull_reader as r
>>> nfr = r.NovelFullReader()
>>> nfr.read()
"""

style = """
    body {
        margin-left: 5rem;
        margin-right: 5rem;
    }
    .end {
        margin-top: 2rem;
    }
    """
CURR_DIR = os.path.dirname(__file__)
translations = {}
not_translated_words = set()

class NovelFullReader:
    URL = 'https://novelfull.com'
    DEFAULT_NOVEL_NAME = 'martial-peak'
    DEFAULT_FILE_DEST = 'C:\\Users\\malza\\Desktop\\odoo_base_web\\temp\\web_page_reader\\novelfull'

    CHAPTER_NO_RE = re.compile(r'chapter[\s*\-_]*(\d+)', re.I)
    # FORBIDDEN_CHAR_RE = re.compile(r'[\*\?\\\/\:\!\"\>\<]', re.I)
    FORBIDDEN_CHAR_RE = re.compile(r'[^\w \s\-_\(\)\[\].\'\"]', re.I)
    CLEAN_TEXT_SPLITTER_RE = re.compile(r'[^\w]', re.I)

    def __init__(self, novel_name=DEFAULT_NOVEL_NAME, file_dest=DEFAULT_FILE_DEST):

        self.novel_name = novel_name
        self.file_dest = os.path.normpath(file_dest)

        if (not os.path.exists(self.file_dest)):
            os.makedirs(self.file_dest, 0o700)
        dir1 = os.path.normpath(os.path.join(self.file_dest, self.novel_name))
        if (not os.path.exists(dir1)):
            os.makedirs(dir1, 0o700)

        handler = logging.FileHandler(os.path.normpath(os.path.join(self.file_dest, self.novel_name, '%s_main_logfile.log'%self.novel_name)))
        logging.getLogger(__name__).addHandler(handler)
        self.main_logger = logging.getLogger(__name__)
        self.main_logger.setLevel(logging.DEBUG)

    def read_by_chapter(self, first_chapter, last_chapter):
        first_page = (first_chapter//50) if first_chapter % 50 == 0 else (first_chapter//50)+1
        last_page = (last_chapter//50) if last_chapter % 50 == 0 else (last_chapter//50)+1
        self._read_sub_page(first_page, first_chapter, direction='up')
        if last_page - first_page >= 2:
            self.read_by_page(first_page+1, last_page -1 )
        if last_page > first_page:
            self._read_sub_page(last_page, last_chapter, direction='down')

    def _read_sub_page(self, page, anchor_chapter_no, direction):
        total_size = {'raw_size': 0, 'clean_size': 0}
        page_url = '%s/%s.html?page=%d' % (self.URL, self.novel_name, page)
        page_req = Request(page_url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            with urlopen(page_req) as f1:
                page_result = etree.HTML(f1.read())
                sel = CSSSelector('#list-chapter')
                list_chapter = sel(page_result)[0]
                for a in list_chapter.iter('a'):
                    chapter_href = a.get('href')
                    if not self.CHAPTER_NO_RE.search(chapter_href):
                        continue
                    chapter_no = int(self.CHAPTER_NO_RE.search(chapter_href).group(1))
                    if (direction == 'up' and chapter_no < anchor_chapter_no) or (direction == 'down' and chapter_no > anchor_chapter_no):
                        continue
                    chapter_title = a.get('title').strip()
                    # for span in a:
                    #     chapter_title = span.text.strip() or chapter_href.split('.')[0]
                    file_name = self.CHAPTER_NO_RE.sub(r'%s%s' % ('Chapter_', str(chapter_no).rjust(5, '0')), chapter_title)
                    file_name = self.FORBIDDEN_CHAR_RE.sub('', file_name)
                    _, r, c = self._read_chapter(chapter_href, chapter_no, file_name)
                    total_size['raw_size'] += r
                    total_size['clean_size'] += c

        except Exception as e:
            self._log_exception(e, self.main_logger)
        msg = '[[Total_Raw_Size:%(raw_size)d, Total_Clean_Size:%(clean_size)d]]' % total_size
        self._log(msg, self.main_logger)
        return msg

    def read_by_page(self, start_page, end_page):
        total_size = {'raw_size': 0, 'clean_size': 0}
        for page in range(start_page, end_page + 1):
            page_url = '%s/%s.html?page=%d' % (self.URL, self.novel_name, page)
            page_req = Request(page_url, headers={'User-Agent': 'Mozilla/5.0'})
            try:
                with urlopen(page_req) as f1:
                    page_result = etree.HTML(f1.read())
                    sel = CSSSelector('#list-chapter')
                    list_chapter = sel(page_result)[0]
                    for a in list_chapter.iter('a'):
                        chapter_href = a.get('href')
                        if not self.CHAPTER_NO_RE.search(chapter_href):
                            continue
                        chapter_no = int(self.CHAPTER_NO_RE.search(chapter_href).group(1))
                        chapter_title = a.get('title').strip()
                        # for span in a:
                        #     chapter_title = span.text.strip() or chapter_href.split('.')[0]
                        file_name = self.CHAPTER_NO_RE.sub(r'%s%s' % ('Chapter_', str(chapter_no).rjust(5, '0')), chapter_title)
                        file_name = self.FORBIDDEN_CHAR_RE.sub('', file_name)
                        _, r, c = self._read_chapter(chapter_href, chapter_no, file_name)
                        total_size['raw_size'] += r
                        total_size['clean_size'] += c

            except Exception as e:
                self._log_exception(e, self.main_logger)
        msg = '[[Total_Raw_Size:%(raw_size)d, Total_Clean_Size:%(clean_size)d]]' % total_size
        self._log(msg, self.main_logger)
        return msg

    def _read_chapter(self, chapter_href, chapter_no, file_name):
        chapter_url = '%s%s' % (self.URL, chapter_href)
        chapter_req = Request(chapter_url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            with urlopen(chapter_req) as f1:
                chapter_result = etree.HTML(f1.read())
                return self._process_raw(chapter_result, chapter_no, file_name, chapter_url)
        except Exception as e:
            self._log_exception(e, self.main_logger)

    def clean_raw(self, sub_dir='raw', filter_not_raw=False):
        chapter_no_re = re.compile(r'chapter[\s*\-_]*(\d+)([\s\S]+)', re.I)
        filter_re = re.compile(r'(\(raw\)\.html)|(\.log)')
        raw_dir = os.path.normpath(os.path.join(self.file_dest, self.novel_name, sub_dir))
        try:
            for file in os.listdir(raw_dir):
                if os.path.isdir(os.path.join(raw_dir, file)):
                    self.clean_raw(os.path.join(sub_dir, file), filter_not_raw)
                if not (os.path.isfile(os.path.join(raw_dir, file)) and chapter_no_re.search(file)):
                    continue
                if filter_not_raw and not filter_re.search(file):
                    continue
                chapter_no_search = chapter_no_re.search(file)
                chapter_no = chapter_no_search.group(1)
                clean_file_name = 'Chapter_%s %s' % (chapter_no.rjust(5,'0'), chapter_no_search.group(2))
                clean_file_name = self.FORBIDDEN_CHAR_RE.sub(' ', clean_file_name)
                clean_file_name = filter_re.sub('', clean_file_name)
                # clean_file_name = clean_file_name.rsplit('.', 1)[0]
                full_raw_file_name = os.path.join(raw_dir, file)
                with open(full_raw_file_name) as f1:
                    raw_material = etree.HTML(f1.read())
                    self._process_raw(raw_material, int(chapter_no), clean_file_name)
        except Exception as e:
            self._log_exception(e, self.main_logger)

    def _process_raw(self, raw_material, chapter_no, file_name, chapter_url=''):
        sel = CSSSelector('#chapter-content')
        chapter_content = sel(raw_material)[0]

        dir1 = os.path.normpath(os.path.join(self.file_dest, self.novel_name))
        if (not os.path.exists(dir1)):
            os.makedirs(dir1, 0o700)
        dir2 = str((chapter_no // 100) * 100).rjust(5, '0')
        dir2 = os.path.normpath(os.path.join(dir1, dir2))
        if (not os.path.exists(dir2)):
            os.makedirs(dir2, 0o700)
        full_file_name_raw = os.path.join(dir2, '%s%s' % (file_name, '(raw).html'))
        with open(full_file_name_raw, "wb") as f2:
            raw_size = f2.write(etree.tostring(raw_material, pretty_print=True, method="html"))

        for script in chapter_content.iter('script'):
            s_parent = script.getparent()
            s_parent.remove(script)
        google_sel = CSSSelector('.google-auto-placed, .ads, .ads-holder')
        google_contents = google_sel(chapter_content)
        for google_content in google_contents:
            google_content_parent = google_content.getparent()
            google_content_parent.remove(google_content)
        for ins in chapter_content.iter('ins'):
            i_parent = ins.getparent()
            i_parent.remove(ins)

        gen_html = html_builder.HTML(
            html_builder.HEAD(html_builder.TITLE(file_name), html_builder.STYLE(style)),
            html_builder.BODY(chapter_content,
                              html_builder.DIV(
                                  html_builder.CLASS("end"),
                                  html_builder.P('The End...'),
                                  html_builder.A(chapter_url, href=chapter_url))
                              ))
        # gen_html = builder.E.html(builder.E.head(builder.E.title(file_name)))
        # gen_html.append(builder.E.body(chapter_content))
        full_file_name = os.path.join(dir2, '%s%s' % (file_name, '.html'))
        with open(full_file_name, "wb") as f3:
            clean_size = f3.write(etree.tostring(gen_html, pretty_print=True, method="html"))

        msg = 'file_name:%s,raw_size:%d,clean_size:%d,timestamp:%s' % (
        file_name, raw_size, clean_size, f'{datetime.now()}')
        self._log(msg, self.main_logger)
        return file_name, raw_size, clean_size

    def convert_to_pdf(self, dest_dir, starting_dir= 0, starting_chapter= 1, ending_chapter=100000):
        if not dest_dir: raise Exception('dest_dir is required')
        filter_re = re.compile(r'(\(raw\)\.html)|(\.log)')
        sub_dir_no_re = re.compile(r'(\d+)')
        full_dest = os.path.normpath(os.path.join(dest_dir, self.novel_name))
        if not os.path.exists(full_dest):
            os.makedirs(full_dest, 0o700)

        source_dir = os.path.normpath(os.path.join(self.file_dest, self.novel_name))
        try:
            for sub_dir in os.listdir(source_dir):
                if sub_dir.endswith('.log') or not sub_dir_no_re.search(sub_dir): continue
                sub_dir_no = int(sub_dir_no_re.search(sub_dir).group(1))
                dest_sub_dir = os.path.join(full_dest, sub_dir)
                if not os.path.exists(dest_sub_dir):
                    os.makedirs(dest_sub_dir, 0o700)
                print('start sub-dir %s' % sub_dir)
                for file in os.listdir(os.path.join(source_dir, sub_dir)):
                    if filter_re.search(file): continue
                    chapter_no = int(self.CHAPTER_NO_RE.search(file).group(1))
                    if sub_dir_no < starting_dir or chapter_no < starting_chapter or chapter_no > ending_chapter: continue
                    full_source_file = os.path.join(source_dir, sub_dir, file)
                    full_dest_file = os.path.join(dest_sub_dir, file.replace('.html', '.pdf'))
                    command = ['wkhtmltopdf', full_source_file, full_dest_file]
                    try:
                        # wkhtmltopdf_process = Popen(command, stdin=PIPE, stdout=PIPE, stderr=PIPE)
                        completed_process = run(command, stdout=PIPE)
                        completed_process.check_returncode() # If returncode is non - zero, raise a CalledProcessError.
                        # for m, n in getmembers(completed_process, lambda m1: not callable(m1)):
                        #     print('%s => %s' % (str(m), str(n)))
                    except Exception as e:
                        self._log_exception(e, self.main_logger)
        except Exception as e:
            self._log_exception(e, self.main_logger)

    ##Tanslations

    def humanize_translations(self):
        global translations
        full_dest = os.path.normpath(os.path.join(self.file_dest, 'translation'))
        try:
            with open(os.path.join(full_dest, 'translations_mini.json'), 'rt') as f1:
                file_content1 = f1.read()
                translations = json.loads(file_content1) if file_content1 else {}

            translated_file = os.path.join(full_dest, 'translations_humanized.json')
            with open(translated_file, 'wt') as f3:
                f3.write(json.dumps(translations, indent=1))

            import codecs
            # opens a file and converts input to true Unicode
            with codecs.open(os.path.join(full_dest, 'translations_humanized.json'), "rb", "unicode_escape") as my_input:
                contents = my_input.read()
                # type(contents) = unicode
            # opens a file with UTF-8 encoding
            with codecs.open(os.path.join(full_dest, 'translations_humanized.json'), "wb", "utf8") as my_output:
                my_output.write(contents)
        except Exception as e:
            self._log_exception(e, self.main_logger)

    def merge_translations(self):
        global translations
        full_dest = os.path.normpath(os.path.join(self.file_dest, 'translation'))
        try:
            if os.path.exists(os.path.join(full_dest, 'translations_mini.json')):
                with open(os.path.join(full_dest, 'translations_mini.json'), 'rt') as f1:
                    file_content1 = f1.read()
                    translations = json.loads(file_content1) if file_content1 else {}
            for file in os.listdir(full_dest):
                if not file.endswith('_translation.json'): continue
                with open(os.path.join(full_dest, file), 'rt') as f2:
                    file_content2 = f2.read()
                    file_content2 = json.loads(file_content2) if file_content2 else {}
                    for k in file_content2:
                        if not translations.get(k):
                            translations[k] = file_content2[k]
            # for ke in translations:
            #     translations[ke] = eval(translations[ke])
            translated_file = os.path.join(full_dest, 'translations_mini.json')
            with open(translated_file, 'wt') as f3:
                f3.write(json.dumps(translations))
                self._log('Total merged words are: %d' % len(translations), self.main_logger)
        except Exception as e:
            self._log_exception(e, self.main_logger)

    def extract_empty_translation(self):
        empty_words = set()
        full_dest = os.path.normpath(os.path.join(self.file_dest, 'translation'))
        try:
            if os.path.exists(os.path.join(full_dest, 'translations_mini.json')):
                with open(os.path.join(full_dest, 'translations_mini.json'), 'rt') as f1:
                    file_content1 = f1.read()
                    global translations
                    translations = json.loads(file_content1) if file_content1 else {}
            for k in list(translations.keys()):
                entry = translations[k][0]
                if not entry['translations']:
                    print('Empty : %s' % k)
                    empty_words.add(k)

            translations_empty_words_file = os.path.join(full_dest, 'translations_empty_words.json')
            with open(translations_empty_words_file, 'wt') as f2:
                f2.write(json.dumps(list(empty_words), indent=4))
        except Exception as e:
            self._log_exception(e, self.main_logger)

    def translate_by_word(self, starting_chapter= 1, ending_chapter=100000):
        filter_re = re.compile(r'(\(raw\)\.html)|(\.log)')
        sub_dir_no_re = re.compile(r'(\d+)')
        full_dest = os.path.normpath(os.path.join(self.file_dest, 'translation'))
        if not os.path.exists(full_dest):
            os.makedirs(full_dest, 0o700)
        try:
            if os.path.exists(os.path.join(full_dest, 'translations_mini.json')):
                with open(os.path.join(full_dest, 'translations_mini.json'), 'rt') as f1:
                    file_content1 = f1.read()
                    global translations
                    translations = json.loads(file_content1) if file_content1 else {}

            if os.path.exists(os.path.join(full_dest, 'not_translated_word.json')):
                with open(os.path.join(full_dest, 'not_translated_word.json'), 'rt') as f2:
                    file_content2 = f2.read()
                    global not_translated_words
                    not_translated_words =  set(json.loads(file_content2)) if file_content2 else set()
        except Exception as e:
            self._log_exception(e, self.main_logger)

        source_dir = os.path.normpath(os.path.join(self.file_dest, self.novel_name))
        try:
            for sub_dir in os.listdir(source_dir):
                if sub_dir.endswith('.log') or not sub_dir_no_re.search(sub_dir): continue
                print('start sub-dir %s' % sub_dir)
                for file in os.listdir(os.path.join(source_dir, sub_dir)):
                    if filter_re.search(file): continue
                    chapter_no = int(self.CHAPTER_NO_RE.search(file).group(1))
                    if chapter_no < starting_chapter or chapter_no > ending_chapter: continue
                    full_source_file = os.path.join(source_dir, sub_dir, file)
                    try:
                        with open(full_source_file) as f1:
                            content = etree.HTML(f1.read())
                            for p in content.iter('p'):
                                p_text = p.text and p.text.strip()
                                if not p_text: continue
                                p_text = filter(lambda t: len(t)>2, self.CLEAN_TEXT_SPLITTER_RE.split(p_text))
                                for text in p_text:
                                    text = text.lower()
                                    print('looking into : %s'%text)
                                    if text in not_translated_words or translations.get(text) or text.isdigit(): continue
                                    print('Translating  : %s' % text)
                                    translate = self._microsoft_translate_word(text)
                                    translations[text] = translate
                    except Exception as e:
                        self._log_exception(e, self.main_logger)
                        self._dump_translation(full_dest)

        except Exception as e:
            self._log_exception(e, self.main_logger)
            self._dump_translation(full_dest)
        self._dump_translation(full_dest)

    def _dump_translation(self, dest):
        self._log('the total of Translations = %d' % len(translations), self.main_logger)
        self._log('the total of not_translated_words = %d' % len(not_translated_words), self.main_logger)
        translation_file = os.path.join(dest, '%s_%s_%s' % (f'{datetime.now()}'.replace(':','.'), self.novel_name, 'translation.json'))
        not_translated_file = os.path.join(dest, 'not_translated_word.json')
        with open(translation_file, 'wt') as f1:
            f1.write(json.dumps(translations, indent=1))
        with open(not_translated_file, 'wt') as f2:
            f2.write(json.dumps(list(not_translated_words), indent=1))

    def translate_py_chapter(self, starting_chapter= 1, ending_chapter=100000):
        filter_re = re.compile(r'(\(raw\)\.html)|(\.log)')
        sub_dir_no_re = re.compile(r'(\d+)')
        full_dest = os.path.normpath(os.path.join(self.file_dest, 'translation'))
        if not os.path.exists(full_dest):
            os.makedirs(full_dest, 0o700)

        source_dir = os.path.normpath(os.path.join(self.file_dest, self.novel_name))
        try:
            for sub_dir in os.listdir(source_dir):
                if sub_dir.endswith('.log') or not sub_dir_no_re.search(sub_dir): continue
                print('start sub-dir %s' % sub_dir)
                for file in os.listdir(os.path.join(source_dir, sub_dir)):
                    if filter_re.search(file): continue
                    chapter_no = int(self.CHAPTER_NO_RE.search(file).group(1))
                    if chapter_no < starting_chapter or chapter_no > ending_chapter: continue
                    full_source_file = os.path.join(source_dir, sub_dir, file)
                    try:
                        chapter_translations = {}
                        with open(full_source_file) as f1:
                            content = etree.HTML(f1.read())
                            # content_translated = content.copy
                            for index, p in enumerate(content.iter('p')):
                                p_text = p.text and p.text.strip()
                                if p.find('p') or not p_text: continue
                                p_text = p_text.replace("'", '').replace('"', '')
                                print(p_text)
                                chapter_translations[index] = self._microsoft_translate_text(p_text)
                                translation = chapter_translations[index] and\
                                              chapter_translations[index][0]['translations'] and\
                                              chapter_translations[index][0]['translations'][0].get('text')
                                p.addnext(html_builder.P(translation))
                                print(translation)
                                # p_text = filter(lambda t: len(t)>2, self.CLEAN_TEXT_SPLITTER_RE.split(p_text))
                                # for text in p_text:
                                #     text = text.lower()
                                #     print('looking into : %s'%text)
                                #     if text in not_translated_words or translations.get(text) or text.isdigit(): continue
                                #     print('Translating  : %s' % text)
                                #     translate = self._microsoft_translate(text)
                                #     translations[text] = translate
                        # with open('%s_%s' % (full_source_file[:-5], 'translation.json'), 'wt') as f2:
                        #     f2.write(json.dumps(chapter_translations, indent=1))
                        with open('%s_%s' % (full_source_file[:-5], 'translation.html'), 'wb') as f3:
                            f3.write(html.tostring(content, pretty_print=True, method="html"))
                    except Exception as e:
                        self._log_exception(e, self.main_logger)
        except Exception as e:
            self._log_exception(e, self.main_logger)

    def _microsoft_translate_word(self, word):
        import http.client

        conn = http.client.HTTPSConnection("microsoft-translator-text.p.rapidapi.com")

        payload = "[\r\n    {\r\n        \"Text\": \"%s\"\r\n    }\r\n]" % word

        headers = {
            'User-Agent': 'Mozilla/5.0',
            'content-type': "application/json",
            'x-rapidapi-host': "microsoft-translator-text.p.rapidapi.com",
            'x-rapidapi-key': "fb635a8454msh796a79b3a00ad30p1dac5fjsn85374dd1956a"
        }

        conn.request("POST", "/Dictionary/Lookup?to=ar&api-version=3.0&from=en", payload.encode('utf-8'), headers)

        try:
            res = conn.getresponse()
            data = res.read()

            # print(data.decode("utf-8"))
            return eval(data.decode("utf-8"))
        except Exception as e:
            self._log_exception(e, self.main_logger)
            raise

    def _microsoft_translate_text(self, text):
        import http.client
        conn = http.client.HTTPSConnection("microsoft-translator-text.p.rapidapi.com")
        payload = """[\r
            {\r
                \"Text\": \"%s.\"\r
            }\r            
        ]""" % text

        headers = {
            'content-type': "application/json",
            'x-rapidapi-host': "microsoft-translator-text.p.rapidapi.com",
            'x-rapidapi-key': "fb635a8454msh796a79b3a00ad30p1dac5fjsn85374dd1956a"
        }

        conn.request("POST", "/translate?to=ar&api-version=3.0&from=en&profanityAction=NoAction&textType=plain", payload.encode('utf-8'),
                 headers)
        try:
            res = conn.getresponse()
            data = res.read()
            # print(data.decode("utf-8"))
            return eval(data.decode("utf-8"))
        except Exception as e:
            self._log_exception(e, self.main_logger)
            raise

    def _log(self, msg, logger):
        logger.log(logging.DEBUG, '*******************************************')
        logger.log(logging.DEBUG, msg)
        logger.log(logging.DEBUG, '*******************************************')

    def _log_exception(self, e, logger):
        logger.log(logging.DEBUG, '*******************************************')
        logger.log(logging.DEBUG, '[%s]' % (str(e)))
        logger.log(logging.DEBUG, '*******************************************')
