# Markdown, rendered by a font
This text box holds plain Markdown. The *font* renders it: **bold**, *italic*, ***both***, `code spans`, and [links](https://commonmark.org).
Markers stay in the text (copy it and you get Markdown back) but take no room: a lone * or an unmatched `backtick stays visible.
Emphasis follows CommonMark exactly: *nested **strong** inside*, __underscores__ but snake_case_names, 2*3*4 and foo*bar*.
GitHub's extensions too: ~~strikethrough~~, bare URLs like www.commonmark.org/help or https://github.github.com/gfm/, and hello@example.com.
Images show their description: ![a diagram of the passes](passes.png), autolinks <https://spec.commonmark.org/0.31.2/>.
Raw HTML is dimmed: <kbd>Ctrl</kbd>+<kbd>C</kbd>, <!-- a comment -->, entities decode: &copy; &frac12; &#955; &amp;.
Escapes work: \*not emphasis\*, \`not code\`, \[not a link\].
> Each line's block markup is read too: block quotes,
- list items, with a bullet,
- [x] task boxes, checked
- [ ] or not,
1. and ordered items, which keep their numbers.
    An indented line is code: *a* [b](c) stays as typed.
---
По-русски тоже: *курсив*, **жирный**, `код` и \*звёздочки\*.
Και στα ελληνικά: *πλάγια*, **έντονα**, `κώδικας`, &laquo;εισαγωγικά&raquo;.
Code spans keep everything literal: `*a* [b](c) <d> &amp;` and ``a `tick` inside``.
