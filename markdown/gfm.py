"""GitHub Flavored Markdown's inline extensions, as cmark-gfm 0.29.0.gfm.13
(the parser github.com uses) implements them in extensions/autolink.c:
extended autolinks to www., http://, https:// and ftp:// addresses and to
email addresses.

cmark-gfm scans UTF-8 bytes, with ASCII-only character classes in places, so
these functions do too: they take the subject as bytes and return byte
offsets. Its quirks are kept (comments say where), since the Markdown font
has to draw what github.com shows.
"""

import bisect


def is_space(b):              # cmark_isspace: not \v or \f
    return b in (9, 10, 13, 32)


def is_alpha(b):
    return 65 <= b <= 90 or 97 <= b <= 122


def is_alnum(b):
    return is_alpha(b) or 48 <= b <= 57


def is_punct(b):              # ASCII punctuation
    return 33 <= b <= 47 or 58 <= b <= 64 or 91 <= b <= 96 or 123 <= b <= 126


# cmark_utf8proc_is_punctuation: the P categories of an older Unicode.
PUNCTUATION = [
    (0xa1, 0xa1), (0xa7, 0xa7), (0xab, 0xab), (0xb6, 0xb7), (0xbb, 0xbb), (0xbf, 0xbf), (0x37e, 0x37e),
    (0x387, 0x387), (0x55a, 0x55f), (0x589, 0x58a), (0x5be, 0x5be), (0x5c0, 0x5c0), (0x5c3, 0x5c3), (0x5c6, 0x5c6),
    (0x5f3, 0x5f4), (0x609, 0x60a), (0x60c, 0x60d), (0x61b, 0x61b), (0x61e, 0x61f), (0x66a, 0x66d), (0x6d4, 0x6d4),
    (0x700, 0x70d), (0x7f7, 0x7f9), (0x830, 0x83e), (0x85e, 0x85e), (0x964, 0x965), (0x970, 0x970), (0xaf0, 0xaf0),
    (0xdf4, 0xdf4), (0xe4f, 0xe4f), (0xe5a, 0xe5b), (0xf04, 0xf12), (0xf14, 0xf14), (0xf3a, 0xf3d), (0xf85, 0xf85),
    (0xfd0, 0xfd4), (0xfd9, 0xfda), (0x104a, 0x104f), (0x10fb, 0x10fb), (0x1360, 0x1368), (0x1400, 0x1400),
    (0x166d, 0x166e), (0x169b, 0x169c), (0x16eb, 0x16ed), (0x1735, 0x1736), (0x17d4, 0x17d6), (0x17d8, 0x17da),
    (0x1800, 0x180a), (0x1944, 0x1945), (0x1a1e, 0x1a1f), (0x1aa0, 0x1aa6), (0x1aa8, 0x1aad), (0x1b5a, 0x1b60),
    (0x1bfc, 0x1bff), (0x1c3b, 0x1c3f), (0x1c7e, 0x1c7f), (0x1cc0, 0x1cc7), (0x1cd3, 0x1cd3), (0x2010, 0x2027),
    (0x2030, 0x2043), (0x2045, 0x2051), (0x2053, 0x205e), (0x207d, 0x207e), (0x208d, 0x208e), (0x2308, 0x230b),
    (0x2329, 0x232a), (0x2768, 0x2775), (0x27c5, 0x27c6), (0x27e6, 0x27ef), (0x2983, 0x2998), (0x29d8, 0x29db),
    (0x29fc, 0x29fd), (0x2cf9, 0x2cfc), (0x2cfe, 0x2cff), (0x2d70, 0x2d70), (0x2e00, 0x2e2e), (0x2e30, 0x2e42),
    (0x3001, 0x3003), (0x3008, 0x3011), (0x3014, 0x301f), (0x3030, 0x3030), (0x303d, 0x303d), (0x30a0, 0x30a0),
    (0x30fb, 0x30fb), (0xa4fe, 0xa4ff), (0xa60d, 0xa60f), (0xa673, 0xa673), (0xa67e, 0xa67e), (0xa6f2, 0xa6f7),
    (0xa874, 0xa877), (0xa8ce, 0xa8cf), (0xa8f8, 0xa8fa), (0xa92e, 0xa92f), (0xa95f, 0xa95f), (0xa9c1, 0xa9cd),
    (0xa9de, 0xa9df), (0xaa5c, 0xaa5f), (0xaade, 0xaadf), (0xaaf0, 0xaaf1), (0xabeb, 0xabeb), (0xfd3e, 0xfd3f),
    (0xfe10, 0xfe19), (0xfe30, 0xfe52), (0xfe54, 0xfe61), (0xfe63, 0xfe63), (0xfe68, 0xfe68), (0xfe6a, 0xfe6b),
    (0xff01, 0xff03), (0xff05, 0xff0a), (0xff0c, 0xff0f), (0xff1a, 0xff1b), (0xff1f, 0xff20), (0xff3b, 0xff3d),
    (0xff3f, 0xff3f), (0xff5b, 0xff5b), (0xff5d, 0xff5d), (0xff5f, 0xff65), (0x10100, 0x10102), (0x1039f, 0x1039f),
    (0x103d0, 0x103d0), (0x1056f, 0x1056f), (0x10857, 0x10857), (0x1091f, 0x1091f), (0x1093f, 0x1093f),
    (0x10a50, 0x10a58), (0x10a7f, 0x10a7f), (0x10af0, 0x10af6), (0x10b39, 0x10b3f), (0x10b99, 0x10b9c),
    (0x11047, 0x1104d), (0x110bb, 0x110bc), (0x110be, 0x110c1), (0x11140, 0x11143), (0x11174, 0x11175),
    (0x111c5, 0x111c8), (0x111cd, 0x111cd), (0x11238, 0x1123d), (0x114c6, 0x114c6), (0x115c1, 0x115c9),
    (0x11641, 0x11643), (0x12470, 0x12474), (0x16a6e, 0x16a6f), (0x16af5, 0x16af5), (0x16b37, 0x16b3b),
    (0x16b44, 0x16b44), (0x1bc9f, 0x1bc9f),
]
_STARTS = [a for a, _ in PUNCTUATION]


def is_unicode_space(uc):     # cmark_utf8proc_is_space
    return uc in (9, 10, 12, 13, 32, 160, 5760, 8239, 8287, 12288) or 8192 <= uc <= 8202


def is_unicode_punct(uc):
    if uc < 128:
        return is_punct(uc)
    i = bisect.bisect_right(_STARTS, uc) - 1
    return i >= 0 and PUNCTUATION[i][0] <= uc <= PUNCTUATION[i][1]


def decode(data, i, n):
    """cmark_utf8proc_iterate on data[i:i + n]: the code point, or -1 (also
    in the middle of a character)."""
    if n <= 0:
        return -1
    b = data[i]
    length = 1 if b < 0x80 else 2 if 0xC0 <= b < 0xE0 else 3 if 0xE0 <= b < 0xF0 else 4 if 0xF0 <= b < 0xF8 else 0
    if not length or length > n or any(data[i + k] & 0xC0 != 0x80 for k in range(1, length)):
        return -1
    if length == 1:
        return b
    uc = b & (0x1F, 0x0F, 0x07)[length - 2]
    for k in range(1, length):
        uc = (uc << 6) | (data[i + k] & 0x3F)
    if uc < (0x80, 0x800, 0x10000)[length - 2] or 0xD800 <= uc < 0xE000 or uc >= 0x110000:
        return -1
    return uc


def is_valid_hostchar(data, i, n):
    uc = decode(data, i, n)
    return uc >= 0 and not is_unicode_space(uc) and not is_unicode_punct(uc)


def autolink_delim(data, start, link_end):
    """How much of data[start:start + link_end] stays in the link once
    trailing punctuation, unmatched `)` and a trailing entity are dropped."""
    opening = closing = 0
    for i in range(link_end):
        c = data[start + i]
        if c == 0x3C:            # <
            link_end = i
            break
        if c == 0x28:
            opening += 1
        elif c == 0x29:
            closing += 1
    while link_end > 0:
        c = data[start + link_end - 1]
        if c == 0x29:            # )
            if closing <= opening:
                return link_end
            closing -= 1
            link_end -= 1
        elif c in b"?!.,:*_~'\"":
            link_end -= 1
        elif c == 0x3B:          # ; ending something like &amp;
            new_end = link_end - 2
            while new_end > 0 and is_alpha(data[start + new_end]):
                new_end -= 1
            if new_end < link_end - 2 and data[start + new_end] == 0x26:
                link_end = new_end
            else:
                link_end -= 1
        else:
            return link_end
    return link_end


def check_domain(data, start, size, allow_short):
    """The length of the domain at data[start:start + size], or 0. As in
    cmark-gfm, the first and the last byte go unchecked, a backslash skips
    a byte, and the loop goes byte by byte, so it stops in the middle of
    the first non-ASCII character (which then joins the link anyway)."""
    np = uscore1 = uscore2 = 0
    i = 1
    while i < size - 1:
        if data[start + i] == 0x5C and i < size - 2:
            i += 1
        c = data[start + i]
        if c == 0x5F:
            uscore2 += 1
        elif c == 0x2E:
            uscore1, uscore2 = uscore2, 0
            np += 1
        elif not is_valid_hostchar(data, start + i, size - i) and c != 0x2D:
            break
        i += 1
    if (uscore1 > 0 or uscore2 > 0) and np <= 10:
        return 0
    if allow_short:
        return i
    return i if np else 0


def _extend(data, start, size, link_end):
    while link_end < size and not is_space(data[start + link_end]) and data[start + link_end] != 0x3C:
        link_end += 1
    return link_end


def www_match(data, pos):
    """At a `w`: the length of the www. link that starts here, or 0."""
    size = len(data) - pos
    if pos > 0 and data[pos - 1] not in b"*_~(" and not is_space(data[pos - 1]):
        return 0
    if size < 4 or data[pos:pos + 4] != b"www.":
        return 0
    link_end = check_domain(data, pos, size, False)
    if link_end == 0:
        return 0
    return autolink_delim(data, pos, _extend(data, pos, size, link_end))


SCHEMES = (b"http://", b"https://", b"ftp://")


def url_match(data, pos):
    """At a `:`: (rewind, length) of the http(s)/ftp link around it, where the
    link starts `rewind` letters before the `:`, or None."""
    size = len(data) - pos
    if size < 4 or data[pos + 1] != 0x2F or data[pos + 2] != 0x2F:
        return None
    rewind = 0
    while rewind < pos and is_alpha(data[pos - rewind - 1]):
        rewind += 1
    s, n = pos - rewind, size + rewind
    if not any(n > len(sc) and data[s:s + len(sc)].lower() == sc and is_valid_hostchar(data, s + len(sc), n - len(sc))
               for sc in SCHEMES):
        return None
    domain_len = check_domain(data, pos + 3, size - 3, True)
    if domain_len == 0:
        return None
    link_end = autolink_delim(data, pos, _extend(data, pos, size, 3 + domain_len))
    return (rewind, link_end) if link_end else None


def _protocol(protocol, data, at, rewind, max_rewind):
    """validate_protocol: does `protocol` end just before the rewound part?"""
    n = len(protocol)
    if n > max_rewind - rewind or data[at - rewind - n:at - rewind] != protocol:
        return False
    return n == max_rewind - rewind or not is_alnum(data[at - rewind - n - 1])


def emails(data):
    """The email autolinks in a text node's bytes: [(start, end, mailto)],
    `mailto` telling whether the link adds "mailto:". As in
    cmark-gfm, a second `@` restarts the search without resetting what the
    first found (whether xmpp: came before, the dots counted)."""
    links = []
    start = offset = 0
    remaining = len(data)
    while offset < remaining:
        auto_mailto, is_xmpp, np = True, False, 0
        at = data.find(b"@", start + offset, start + remaining)
        if at < 0:
            break
        max_rewind = at - (start + offset)
        while True:            # found_at
            base = start + offset + max_rewind
            rewind = 0
            while rewind < max_rewind:
                c = data[base - rewind - 1]
                if is_alnum(c) or c in b".+-_":
                    rewind += 1
                    continue
                if c == 0x3A:
                    if _protocol(b"mailto:", data, base, rewind, max_rewind):
                        auto_mailto = False
                        rewind += 1
                        continue
                    if _protocol(b"xmpp:", data, base, rewind, max_rewind):
                        auto_mailto, is_xmpp = False, True
                        rewind += 1
                        continue
                break
            if rewind == 0:
                offset += max_rewind + 1
                break
            link_end, again = 1, False
            while link_end < remaining - offset - max_rewind:
                c = data[base + link_end]
                if c == 0x40:
                    offset += max_rewind + 1
                    max_rewind = link_end - 1
                    again = True
                    break
                if c == 0x2E and link_end < remaining - offset - max_rewind - 1 and is_alnum(data[base + link_end + 1]):
                    np += 1
                elif not (is_alnum(c) or (c == 0x2F and is_xmpp) or c in (0x2D, 0x5F)):
                    break
                link_end += 1
            if again:
                continue
            last = data[base + link_end - 1]
            if link_end < 2 or np == 0 or (not is_alpha(last) and last != 0x2E):
                offset += max_rewind + link_end
                break
            link_end = autolink_delim(data, base, link_end)
            if link_end == 0:
                offset += max_rewind + 1
                break
            links.append((base - rewind, base + link_end, auto_mailto))
            start += offset + max_rewind + link_end
            remaining -= offset + max_rewind + link_end
            offset = 0
            break
    return links
