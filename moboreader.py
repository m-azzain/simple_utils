import os
import re
import codecs
import io
import csv
from subprocess import Popen, PIPE, run
from inspect import getmembers
import json

from lxml import etree, builder, html
from lxml.html import builder as html_builder
from lxml.cssselect import CSSSelector
from urllib.request import Request, urlopen
from urllib import parse

import logging
import logging.handlers
from datetime import datetime


CURR_DIR = os.path.dirname(__file__)
CHAPTER_NO_RE = re.compile(r'chapter[\s\-_]*(\d+)[\s\-_]*(\d+)_(\(full\)|\(short\))[\s\-_]*([\s\S]+)', re.I)
FILTER_RE = re.compile(r'(\.log)')
CHAPTER_NO_CLEAR_RE = re.compile(r'\d*[\s\-_]*chapter[\s\-_]*\d+', re.I)
FORBIDDEN_CHAR_RE = re.compile(r'[^\w \s\-_\(\)\[\].\'\"]', re.I)
full_threshold = 2500 ## minimum chars

style = """
    body {
        margin-left: 5rem;
        margin-right: 5rem;
    }
    .p_sj {
        font-family: Microsoft YaHei;
        color: #333;
        font-size: 1.2rem;
    }
    .name {
        text-align: center;
        font-family: Microsoft YaHei;
        font-weight: 700;
        color: #333;
        margin: 1rem;
    }
    .end {
        margin-top: 2rem;
    }
"""

class MoboReader:

    URL = 'https://overseas-en.cdreader.com/api'
    DEFAULT_NOVEL_NAME = 'Apotheosis' ##bookId=18325322
    DEFAULT_FILE_DEST = os.path.join(CURR_DIR, 'moboreader')
    Novel_Name_Map = {'Apotheosis': '18325322', "The Demon King's Destiny":'23998322'}

    def __init__(self, novel_name=DEFAULT_NOVEL_NAME, file_dest=DEFAULT_FILE_DEST):

        self.novel_name = novel_name
        self.file_dest = os.path.normpath(file_dest)

        if (not os.path.exists(self.file_dest)):
            os.makedirs(self.file_dest, 0o700)
        dir1 = os.path.normpath(os.path.join(self.file_dest, self.novel_name))
        if (not os.path.exists(dir1)):
            os.makedirs(dir1, 0o700)

        self.acc_list = self._read_acc()
        self.current_token = ''

        handler = logging.FileHandler(os.path.normpath(os.path.join(self.file_dest, self.novel_name, '%s_main_logfile.log'%self.novel_name)))
        logging.getLogger(__name__).addHandler(handler)
        self.main_logger = logging.getLogger(__name__)
        self.main_logger.setLevel(logging.DEBUG)

    def _read_chapter_list(self):
        #https://overseas-en.cdreader.com/api/Book/BookDetail?bookId=18325322
        book_detail_url = '%s/Book/BookDetail?bookId=%s' % (self.URL, self.Novel_Name_Map[self.novel_name])
        book_detail_req = Request(book_detail_url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            with urlopen(book_detail_req) as f1:
                book_detail_json = f1.read()
                book_detail = json.loads(book_detail_json)
                book_detail_file = os.path.join(self.file_dest, self.novel_name, 'book_detail.json')
                with open(book_detail_file, 'wt') as f2:
                    f2.write(json.dumps(book_detail, indent=4))

            page_index = 1
            page_size = book_detail['data']['chapterNum']
            chapter_list_url = '%s/Book/ChapterList?bookId=%s&pageIndex=%d&pageSize=%d' % \
                               (self.URL, self.Novel_Name_Map[self.novel_name], page_index, page_size)
            chapter_list_req = Request(chapter_list_url, headers={'User-Agent': 'Mozilla/5.0'})

            with urlopen(chapter_list_req) as f2:
                chapter_list = json.loads(f2.read().decode('utf-8'))
                chapter_list_file = os.path.join(self.file_dest, self.novel_name, 'chapter_list.json')
                with open(chapter_list_file, 'wt') as f3:
                    f3.write(json.dumps(chapter_list, indent=4))

        except Exception as e:
            self._log_exception(e, self.main_logger)

    def read_by_chapter(self, first_chapter, last_chapter):
        chapter_list_file = os.path.join(self.file_dest, self.novel_name, 'chapter_list.json')
        try:
            if not os.path.exists(chapter_list_file):
                self._read_chapter_list()
            with open(chapter_list_file, 'rt') as f1:
                chapter_list = json.loads(f1.read())
            chapter_list = list(filter(lambda c: first_chapter <= c['serialNumber'] <= last_chapter,
                                       chapter_list['data']['chapterList']))

            main_dir = os.path.normpath(os.path.join(self.file_dest, self.novel_name))

            if not self.current_token:
                self._get_token()

            for index, chapter in enumerate(chapter_list):
                #https://overseas-en.cdreader.com/api/Book/ChapterRead?bookId=18325322&chapterId=389358
                chapter_url = '%s/Book/ChapterRead?bookId=%s&chapterId=%d' % \
                              (self.URL, self.Novel_Name_Map[self.novel_name], chapter['chapterId'])

                chapter_req = Request(chapter_url,
                                      headers={'User-Agent': 'Mozilla/5.0', 'Authorization': 'Bearer '+self.current_token})

                with urlopen(chapter_req) as f2:
                    chapter_content = json.loads(f2.read().decode('utf-8'))
                    dir1 = str((chapter['serialNumber'] // 100) * 100).rjust(5, '0')
                    dir1 = os.path.normpath(os.path.join(main_dir, dir1))
                    if (not os.path.exists(dir1)):
                        os.makedirs(dir1, 0o700)

                    first_content = '<div>' + chapter_content['data']['firstContent'] + '</div>'
                    last_content = '<div>' + chapter_content['data']['lastContent'] + '</div>'

                    full_or_short = '(full)' if len(first_content) >= full_threshold else '(short)'

                    file_name = CHAPTER_NO_CLEAR_RE.sub('', chapter['chapterName'])
                    clean_file_name = 'Chapter_%05d_%05d_%s %s' % \
                                      (chapter['serialNumber'], chapter['chapterId'], full_or_short, file_name)
                    clean_file_name = FORBIDDEN_CHAR_RE.sub(' ', clean_file_name)

                    msg = 'file_name:%s,first_content_size:%d,last_content_size:%d,timestamp:%s' % (
                        clean_file_name, len(first_content), len(last_content), f'{datetime.now()}')
                    self._log(msg, self.main_logger)

                    if (len(first_content) < full_threshold and self._get_token()):
                        chapter_list[index + 1:index + 1] = [chapter]

                    first_content = html.fromstring(first_content)
                    last_content = html.fromstring(last_content)
                    chapter_content = html_builder.DIV(first_content, html_builder.HR(), last_content)

                    novel_name_h = html_builder.H3(html_builder.CLASS("name"), self.novel_name)
                    chapter_name_h = html_builder.H4(html_builder.CLASS("name"), chapter['chapterName'])
                    gen_html = html_builder.HTML(
                        html_builder.HEAD(html_builder.TITLE(chapter['chapterName']), html_builder.STYLE(style)),
                        html_builder.BODY(novel_name_h, chapter_name_h, chapter_content,
                                          html_builder.DIV(
                                              html_builder.CLASS("end"),
                                              html_builder.P('The End...'),
                                              html_builder.A(chapter_url, href=chapter_url))
                                          )
                    )
                    # gen_html = builder.E.html(builder.E.head(builder.E.title()))
                    # gen_html.append(builder.E.body(chapter_content))
                    full_file_name = os.path.join(dir1, '%s%s' % (clean_file_name, '.html'))
                    with open(full_file_name, "wb") as f3:
                        clean_size = f3.write(html.tostring(gen_html, pretty_print=True, method="html"))
        except Exception as e:
            self._log_exception(e, self.main_logger)

    def set_account(self, email, password):
        acc_file = os.path.join(self.file_dest, 'acc_list.json')
        acc_list = self._read_acc()
        acc = acc_list.setdefault(email, {})
        acc['passw'] = password
        with open(acc_file, 'wt') as f2:
            f2.write(json.dumps(acc_list))

    def _read_acc(self):
        acc_file = os.path.join(self.file_dest, 'acc_list.json')
        if os.path.exists(acc_file):
            with open(acc_file, 'rt') as f1:
                return json.loads(f1.read())
        else:
            return {}

    def _get_token(self):
        try:
            email = list(self.acc_list.keys())[0]
        except IndexError:
            self._log('*******All Tokens have been consumed******', self.main_logger)
            return ''
        passw = self.acc_list[email]['passw']
        #https://overseas-en.cdreader.com/api/User/Login
        chapter_url = '%s/User/Login' % self.URL
        data = json.dumps({"email": email, "pwd": passw, "loginType": 0}).encode('utf-8')
        chapter_req = Request(chapter_url, headers={'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/json'},
                              method='POST', data=data)

        try:
            with urlopen(chapter_req) as f1:
                response = json.loads(f1.read().decode('utf-8'))
                self.current_token = response['data']['accesstoken']
                del self.acc_list[email]

                msg = 'User/Login (%s) Response:\n%s\n,timestamp:%s' % (email,json.dumps(response, indent=2), f'{datetime.now()}')
                self._log(msg, self.main_logger)

                return self.current_token
        except Exception as e:
            self._log_exception(e, self.main_logger)
            return ''

    def convert_to_pdf(self, dest_dir, starting_dir= 0, starting_chapter= 1, ending_chapter=100000):
        if not dest_dir: raise Exception('dest_dir is required')
        filter_re = re.compile(r'(Chapter_\d+_\d+_\(short\))|(\.log)')
        sub_dir_no_re = re.compile(r'(\d+)')
        full_dest = os.path.normpath(os.path.join(dest_dir, self.novel_name))
        if not os.path.exists(full_dest):
            os.makedirs(full_dest, 0o700)

        source_dir = os.path.normpath(os.path.join(self.file_dest, self.novel_name))
        try:
            for sub_dir in os.listdir(source_dir):
                if sub_dir.endswith('.log') or sub_dir.endswith('.json') or not sub_dir_no_re.search(sub_dir): continue
                sub_dir_no = int(sub_dir_no_re.search(sub_dir).group(1))
                dest_sub_dir = os.path.join(full_dest, sub_dir)
                if not os.path.exists(dest_sub_dir):
                    os.makedirs(dest_sub_dir, 0o700)
                print('start sub-dir %s' % sub_dir)
                for file in os.listdir(os.path.join(source_dir, sub_dir)):
                    if filter_re.search(file): continue
                    chapter_no = int(CHAPTER_NO_RE.search(file).group(1))
                    if sub_dir_no < starting_dir or ending_chapter < chapter_no or chapter_no < starting_chapter: continue
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

    def _log(self, msg, logger):
        logger.log(logging.DEBUG, '*******************************************')
        logger.log(logging.DEBUG, msg)

    def _log_exception(self, e, logger):
        logger.log(logging.DEBUG, '*******************************************')
        logger.log(logging.DEBUG, '[%s]' % (str(e)))