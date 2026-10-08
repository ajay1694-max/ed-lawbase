"""Remove administrative eOffice stamps, preserving public judgment text."""
import re

ADMIN_LINE = re.compile(
    r"(?im)^(?:\d{5,7}/\d{4}/Legal\(ED\)\(HO\)|"
    r"File No\. Leg[-/]\d+(?:/\d+)*/\d{4}-LEGAL-HO \(Computer No\. \d+\)|"
    r"Generated from eOffice by [^\n]*ED Head Quarter on \d{2}/\d{2}/\d{4}[^\n]*)[ \t]*\r?$\n?"
)


def strip_admin_lines(text):
    return ADMIN_LINE.sub("", text)
