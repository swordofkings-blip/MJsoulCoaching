# -*- coding: utf-8 -*-
"""Multi-language AST parser using tree-sitter (Python/HTML/JavaScript/CSS)."""

from typing import Any, Dict, Iterator, List, Optional

from tree_sitter import Node, Tree, Language
from tree_sitter_languages import get_parser, get_language

_LANGUAGES = {
    "python": "python",
    "html": "html",
    "js": "javascript",
    "javascript": "javascript",
    "css": "css",
}


class AstParser:
    """Parse and query source code AST for multiple languages.

    Supported languages: python, html, javascript, css
    """

    parsers: Dict[str, "AstParser"] = {}

    def __init__(self, language: str):
        raw = _LANGUAGES.get(language)
        if raw is None:
            raise ValueError(f"Unsupported language: {language}. "
                             f"Supported: {list(_LANGUAGES)}")
        self._raw_lang = raw
        self._parser = get_parser(raw)
        self._language: Language = get_language(raw)
        self._tree: Optional[Tree] = None
        self._source: bytes = b""

    @classmethod
    def for_(cls, language: str) -> "AstParser":
        if language not in cls.parsers:
            cls.parsers[language] = cls(language)
        return cls.parsers[language]

    @property
    def language(self) -> str:
        return self._raw_lang

    @property
    def tree(self) -> Optional[Tree]:
        return self._tree

    def parse(self, code: str) -> Tree:
        self._source = code.encode("utf-8")
        self._tree = self._parser.parse(self._source)
        return self._tree

    def get_text(self, node: Node) -> str:
        return self._source[node.start_byte:node.end_byte].decode("utf-8")

    def get_source(self) -> str:
        return self._source.decode("utf-8")

    def query(self, query_str: str):
        return self._language.query(query_str)

    def query_matches(self, query_str: str, node: Optional[Node] = None
                      ) -> list:
        q = self.query(query_str)
        return q.matches(node or self._tree.root_node)

    @staticmethod
    def walk(node: Node) -> Iterator[Node]:
        yield node
        for child in node.children:
            yield from AstParser.walk(child)

    @staticmethod
    def find_all(node: Node, type_name: str) -> List[Node]:
        return [n for n in AstParser.walk(node) if n.type == type_name]

    @staticmethod
    def find_first(node: Node, type_name: str) -> Optional[Node]:
        if node.type == type_name:
            return node
        for child in node.children:
            found = AstParser.find_first(child, type_name)
            if found:
                return found
        return None

    @staticmethod
    def to_dict(node: Node) -> dict:
        result: Dict[str, Any] = {
            "type": node.type,
            "start_byte": node.start_byte,
            "end_byte": node.end_byte,
            "start_point": list(node.start_point),
            "end_point": list(node.end_point),
        }
        if node.children:
            result["children"] = [AstParser.to_dict(c) for c in node.children]
        return result

    def sexp(self, node: Optional[Node] = None) -> str:
        return (node or self._tree.root_node).sexp()
