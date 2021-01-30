import io
import logging
import os
from abc import ABC
from tempfile import NamedTemporaryFile
from typing import Type, TypeVar

import sass
from bs4 import BeautifulSoup
from livereload import Server
from mkdocs.config import Config
from mkdocs.plugins import BasePlugin
from mkdocs.structure.pages import Page
from mkdocs.utils import normalize_url

_T_SassEntry = TypeVar('_T', bound='_SassEntry')


_logger = logging.getLogger('mkdocs.extra-sass')


class ExtraSassPlugin(BasePlugin):
    """Extra Sass Plugin"""

    def __init__(self):
        self.__entry_point = None

    def on_config(self, config: Config):
        self.__entry_point = None

    def on_serve(self, server: Server, config: Config, builder, **kwargs):
        self._entry_point(config).on_serve(server, builder)
        return server

    def on_post_page(
        self, output_content: str, page: Page, config: Config
    ) -> str:
        relative_path = self._entry_point(config).relative_path
        if not relative_path:
            return output_content

        # injection

        href = normalize_url(relative_path, page=page)

        soup = BeautifulSoup(output_content, 'html.parser')

        stylesheet = soup.new_tag('link')
        stylesheet.attrs['href'] = href
        stylesheet.attrs['rel'] = 'stylesheet'

        soup.head.append(stylesheet)

        _logger.debug(
            "[SASS] add on Page: %s, entry_point: %s" %
            (page.url, stylesheet))
        _logger.debug(str(soup.head))

        return str(soup)

    # ------------------------------

    def _entry_point(self, config: Config) -> _T_SassEntry:
        if self.__entry_point is None:
            self.__entry_point = self._build_entry(config)
        return self.__entry_point

    def _build_entry(self, config: Config) -> _T_SassEntry:
        entry_point = _SassEntry.search_entry_point()
        if entry_point.is_available:
            try:
                site_dir = config["site_dir"]
                dest_dir = os.path.join("assets", "stylesheets")
                info = entry_point.save_to(site_dir, dest_dir)
                _logger.info(
                    '[SASS] Build CSS "%s" from "%s"' % (
                        info['dst'], info['src']))
            except Exception as ex:
                _logger.exception('[SASS] Failed to build CSS: %s', ex)
                if config['strict']:
                    raise ex

        return entry_point


# ==============================
#
#


class _SassEntry(ABC):

    _styles_dir = 'extra_sass'
    _style_filenames = [
        'style.css.sass', 'style.sass',
        'style.css.scss', 'style.scss',
    ]

    @classmethod
    def search_entry_point(cls: Type[_T_SassEntry]) -> _T_SassEntry:
        d = cls._styles_dir
        if os.path.isdir(d):
            for f in cls._style_filenames:
                path = os.path.join(d, f)
                if path and os.path.isfile(path):
                    return _AvailableSassEntry(d, f)
        return _NoSassEntry()

    @property
    def is_available(self) -> bool:
        return False

    @property
    def relative_path(self) -> str:
        return ""

    def on_serve(self, server: Server, builder) -> None:
        pass

    def save_to(self, site_dir: str, dest_dir: str) -> dict:
        raise AssertionError('DO NOT CALL HERE')


class _NoSassEntry(_SassEntry):
    pass


class _AvailableSassEntry(_SassEntry):

    def __init__(self, dirname: str, filename: str):
        self._dirname = dirname
        self._filename = filename

        self._relative_path = None

    @property
    def is_available(self) -> bool:
        return True

    @property
    def relative_path(self) -> str:
        """ Compiled CSS file: relative path from `SITE_DIR` """
        return self._relative_path

    def on_serve(self, server: Server, builder) -> None:
        source_path = os.path.join(self._dirname, self._filename)
        if os.path.isfile(source_path):
            server.watch(self._dirname, builder)

    def save_to(self, site_dir: str, dest_dir: str) -> dict:

        def fix_umask(temp_file):
            # see: https://stackoverflow.com/questions/10541760/can-i-set-the-umask-for-tempfile-namedtemporaryfile-in-python  # noqa: E501
            umask = os.umask(0o666)
            os.umask(umask)
            os.chmod(temp_file.name, 0o666 & ~umask)

        source_path = os.path.join(self._dirname, self._filename)

        output_dir = os.path.join(site_dir, dest_dir)
        os.makedirs(output_dir, exist_ok=True)

        with NamedTemporaryFile(
            prefix='extra-style.',
            suffix='.min.css',
            dir=output_dir,
            delete=False,
            mode='w',
            encoding='utf-8',
            newline=''
        ) as css_file:
            fix_umask(css_file)

            _, filename = os.path.split(css_file.name)
            source_map_filename = filename + '.map'

            css, source_map = sass.compile(
                filename=source_path,
                output_style='compressed',
                source_map_filename=source_map_filename,
                source_map_contents=True,
                omit_source_map_url=False,
                output_filename_hint=filename
            )

            css_file.write(css)

            map_file = os.path.join(output_dir, source_map_filename)
            with io.open(map_file, 'w', encoding='utf-8', newline='') as f:
                f.write(source_map)

            self._relative_path = os.path.join(dest_dir, filename)

            return {
                'src': source_path,
                'dst': self._relative_path
            }
