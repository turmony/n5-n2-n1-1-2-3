"""Validate published image targets and relocate Markdown without reformatting it.

Use the reader's Markdown parser and visibility rules. Never guess a replacement
by filename: a link must resolve from its document's own directory.
"""

import posixpath
import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

from markdown import Markdown
from markdown.blockprocessors import ReferenceProcessor
from markdown.inlinepatterns import LinkInlineProcessor

IMAGE_SUFFIXES = frozenset({'.png', '.jpg', '.jpeg', '.gif', '.webp'})
MARKDOWN_EXTENSIONS = ['tables', 'attr_list', 'admonition', 'pymdownx.details', 'pymdownx.superfences']


@dataclass(frozen=True)
class AssetIssue:
    source: str
    link: str
    target: str
    reason: str

    def __str__(self) -> str:
        return f'{self.source}: 图片资源链接 {self.link!r} → {self.target}（{self.reason}）'


class AssetIndex:
    """One build/audit snapshot of exactly the images the reader can publish."""

    def __init__(self, root: Path):
        from .reader.sources import iter_visible_images

        self.root = root.resolve(strict=True)
        self.images = frozenset(iter_visible_images(self.root))

    def issue(self, source: Path, link: str, *, image: bool = True) -> AssetIssue | None:
        try:
            parsed = urlsplit(link)
        except ValueError:
            return AssetIssue(source.as_posix(), link, '无法解析', '无效 URL')
        if parsed.scheme.lower() in {'http', 'https'} or (parsed.netloc and not parsed.scheme):
            return None
        path = unquote(parsed.path)
        if not image and Path(path).suffix.lower() not in IMAGE_SUFFIXES:
            return None
        reason = ''
        relative = posixpath.normpath(posixpath.join(source.parent.as_posix(), path))
        target = self.root / relative
        if parsed.scheme or parsed.netloc or not path or path.startswith('/') or '\\' in path or '\x00' in path:
            reason = '不支持的本地图片地址'
        else:
            try:
                resolved = target.resolve()
                resolved.relative_to(self.root)
                if target not in self.images or resolved != target:
                    reason = '文件不存在或不允许发布（隐藏文件、链接文件或不支持的图片格式）'
            except (OSError, ValueError, RuntimeError):
                reason = '目标越出资料库或无法读取'
        return AssetIssue(source.as_posix(), link, relative, reason) if reason else None

    def check(self, source: Path, markdown: str) -> tuple[AssetIssue, ...]:
        return tuple(dict.fromkeys(
            issue for link, image in rendered_links(markdown)
            if (issue := self.issue(source, link, image=image)) is not None
        ))


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, bool]] = []
        self.code_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'pre', 'code', 'script', 'style'}:
            self.code_depth += 1
        values = dict(attrs)
        if not self.code_depth and tag in {'img', 'a'}:
            value = values.get('src' if tag == 'img' else 'href')
            if value is not None:
                self.links.append((value, tag == 'img'))

    def handle_endtag(self, tag):
        if tag in {'pre', 'code', 'script', 'style'} and self.code_depth:
            self.code_depth -= 1


def rendered_links(text: str) -> tuple[tuple[str, bool], ...]:
    parser = _Links()
    parser.feed(Markdown(extensions=MARKDOWN_EXTENSIONS).convert(text))
    return tuple(parser.links)


def audit_assets(root: Path) -> tuple[AssetIssue, ...]:
    from .reader.sources import load_source_pages

    index = AssetIndex(root)
    return tuple(issue for page in load_source_pages(root)
                 for issue in index.check(page.relative_path, page.markdown))


def _mask_examples(text: str) -> str:
    """Keep source offsets while excluding literal code and comments."""
    def blank(match):
        return ''.join('\n' if c == '\n' else ' ' for c in match.group())

    masked = re.sub(r'<!--.*?-->|<(pre|code|script|style)\b[^>]*>.*?</\1\s*>',
                    blank, text, flags=re.DOTALL | re.IGNORECASE)
    lines = masked.splitlines(keepends=True)
    fence = None
    for i, line in enumerate(lines):
        match = re.match(r'^[ \t>]*(?:[-+*] )?(`{3,}|~{3,})', line)
        if fence:
            lines[i] = ''.join('\n' if c == '\n' else ' ' for c in line)
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence):
                fence = None
        elif match:
            fence = match[1]
            lines[i] = ''.join('\n' if c == '\n' else ' ' for c in line)
        elif line.startswith(('    ', '\t')):
            lines[i] = ''.join('\n' if c == '\n' else ' ' for c in line)
    return re.sub(r'(?<![\\`])(`+)(?!`).*?(?<!`)\1(?!`)', blank, ''.join(lines), flags=re.DOTALL)


class _SourceLinkProcessor(LinkInlineProcessor):
    def unescape(self, text: str) -> str:
        # These are original source slices, never Markdown placeholder nodes.
        return text


def _destinations(text: str):
    """Yield exact URL spans; use Python-Markdown's balanced link parser."""
    masked = _mask_examples(text)
    html_tags = list(re.finditer(
        r'''</?[A-Za-z][\w:-]*(?:\s+(?:[^"'>]|"[^"]*"|'[^']*')*)?/?>''', masked,
    ))
    markdown_only = masked
    for tag in reversed(html_tags):
        markdown_only = markdown_only[:tag.start()] + ' ' * len(tag.group()) + markdown_only[tag.end():]
    processor = _SourceLinkProcessor(r'\[', Markdown())
    spans = set()
    for match in re.finditer(r'(?<!\\)\[', markdown_only):
        _, index, handled = processor.getText(markdown_only, match.end())
        if not handled:
            continue
        href, _, end, handled = processor.getLink(markdown_only, index)
        if handled and href:
            start = index + 1
            while start < end and markdown_only[start].isspace():
                start += 1
            if markdown_only[start:start + 1] == '<':
                start += 1
            if markdown_only[start:start + len(href)] == href:
                spans.add((start, start + len(href)))
    for match in ReferenceProcessor.RE.finditer(masked):
        start, end = match.span(2)
        if masked[start:start + 1] == '<':
            start += 1
        if masked[end - 1:end] == '>':
            end -= 1
        spans.add((start, end))
    for tag in html_tags:
        if not re.match(r'<(?:img|a)(?=\s|/?>)', tag.group(), flags=re.IGNORECASE):
            continue
        for attr in re.finditer(r'''\s+([\w:-]+)\s*=\s*(["'])(.*?)\2''', tag.group(), flags=re.DOTALL):
            if attr[1].lower() not in {'src', 'href'}:
                continue
            spans.add((tag.start() + attr.start(3), tag.start() + attr.end(3)))
    return sorted(spans)


def rebase_assets(root: Path, source: Path, destination: Path, body: str) -> str:
    """Rebase real image references only; fail before writing on ambiguity."""
    index = AssetIndex(root)
    issues = index.check(source, body)
    if issues:
        raise ValueError('\n'.join(map(str, issues)))
    links = rendered_links(body)
    replacements = {}
    for link, image in links:
        parsed = urlsplit(link)
        if parsed.scheme or parsed.netloc or not parsed.path or parsed.path.startswith('/'):
            continue
        if not image and Path(unquote(parsed.path)).suffix.lower() not in IMAGE_SUFFIXES:
            continue
        target = posixpath.normpath(posixpath.join(source.parent.as_posix(), parsed.path))
        relative = posixpath.relpath(target, destination.parent.as_posix())
        replacements[link] = urlunsplit(('', '', relative, parsed.query, parsed.fragment))
    result = body
    for start, end in reversed(_destinations(body)):
        raw = body[start:end]
        replacement = replacements.get(unescape(raw))
        if replacement is not None:
            # Preserve entity spelling in query strings and Markdown syntax.
            old_path = urlsplit(unescape(raw)).path
            new_path = urlsplit(replacement).path
            result = result[:start] + raw.replace(old_path, new_path, 1) + result[end:]
    expected = tuple((replacements.get(link, link), image) for link, image in links)
    if rendered_links(result) != expected:
        raise ValueError('图片链接无法无损换算；请显式修正链接后重新入库')
    issues = index.check(destination, result)
    if issues:
        raise ValueError('\n'.join(map(str, issues)))
    return result
