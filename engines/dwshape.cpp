// Shape text with DirectWrite, the shaper behind Windows' own text APIs, for
// the Fontlex checks (test_fontlex.DirectWrite).
//
//     dwshape FONT.ttf [FEATURE ...]
//
// Reads one line per text from stdin, the text's UTF-8 bytes in hex, and
// writes one line per text: the advance width, then for each glyph its id,
// the UTF-16 index of its first character and its x and y, in font units.
// Like an app, it splits the text into script runs first and shapes each run
// on its own (IDWriteTextAnalyzer::AnalyzeScript, GetGlyphs,
// GetGlyphPlacements). The default features (calt, mark and the rest) stay
// on; FEATURE tags such as ss01 are turned on as well.
//
// Build (Visual Studio's x64 tools): cl /nologo /O2 /EHsc /utf-8 dwshape.cpp dwrite.lib

#include <windows.h>
#include <dwrite.h>

#include <algorithm>
#include <cstdio>
#include <iostream>
#include <string>
#include <vector>

static const wchar_t LOCALE[] = L"en-us";

// The text an analysis reads, as one paragraph, left to right.
struct Source : IDWriteTextAnalysisSource {
    const std::wstring &text;
    explicit Source(const std::wstring &t) : text(t) {}
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID id, void **out) override {
        if (id == __uuidof(IUnknown) || id == __uuidof(IDWriteTextAnalysisSource)) {
            *out = this;
            return S_OK;
        }
        *out = nullptr;
        return E_NOINTERFACE;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return 1; }
    ULONG STDMETHODCALLTYPE Release() override { return 1; }
    HRESULT STDMETHODCALLTYPE GetTextAtPosition(UINT32 pos, const WCHAR **s, UINT32 *n) override {
        bool in = pos < text.size();
        *s = in ? text.data() + pos : nullptr;
        *n = in ? UINT32(text.size() - pos) : 0;
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE GetTextBeforePosition(UINT32 pos, const WCHAR **s, UINT32 *n) override {
        bool in = pos > 0 && pos <= text.size();
        *s = in ? text.data() : nullptr;
        *n = in ? pos : 0;
        return S_OK;
    }
    DWRITE_READING_DIRECTION STDMETHODCALLTYPE GetParagraphReadingDirection() override {
        return DWRITE_READING_DIRECTION_LEFT_TO_RIGHT;
    }
    HRESULT STDMETHODCALLTYPE GetLocaleName(UINT32 pos, UINT32 *n, const WCHAR **locale) override {
        *n = UINT32(text.size() - pos);
        *locale = LOCALE;
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE GetNumberSubstitution(UINT32 pos, UINT32 *n, IDWriteNumberSubstitution **sub) override {
        *n = UINT32(text.size() - pos);
        *sub = nullptr;
        return S_OK;
    }
};

// Collects the script runs.
struct Sink : IDWriteTextAnalysisSink {
    struct Run { UINT32 start, length; DWRITE_SCRIPT_ANALYSIS script; };
    std::vector<Run> runs;
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID id, void **out) override {
        if (id == __uuidof(IUnknown) || id == __uuidof(IDWriteTextAnalysisSink)) {
            *out = this;
            return S_OK;
        }
        *out = nullptr;
        return E_NOINTERFACE;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return 1; }
    ULONG STDMETHODCALLTYPE Release() override { return 1; }
    HRESULT STDMETHODCALLTYPE SetScriptAnalysis(UINT32 start, UINT32 n, const DWRITE_SCRIPT_ANALYSIS *s) override {
        runs.push_back({start, n, *s});
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE SetLineBreakpoints(UINT32, UINT32, const DWRITE_LINE_BREAKPOINT *) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE SetBidiLevel(UINT32, UINT32, UINT8, UINT8) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE SetNumberSubstitution(UINT32, UINT32, IDWriteNumberSubstitution *) override { return S_OK; }
};

static int fail(const char *what, HRESULT hr) {
    std::printf("ERR %s 0x%08lx\n", what, (unsigned long)hr);
    std::fflush(stdout);
    return 1;
}

static std::wstring from_hex(const std::string &hex) {
    std::string bytes;
    for (size_t i = 0; i + 1 < hex.size(); i += 2)
        bytes.push_back(char(std::stoi(hex.substr(i, 2), nullptr, 16)));
    if (bytes.empty())
        return L"";
    int n = MultiByteToWideChar(CP_UTF8, 0, bytes.data(), int(bytes.size()), nullptr, 0);
    std::wstring text(n, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, bytes.data(), int(bytes.size()), text.data(), n);
    return text;
}

int wmain(int argc, wchar_t **argv) {
    if (argc < 2) {
        std::fprintf(stderr, "usage: dwshape FONT.ttf [FEATURE ...]\n");
        return 2;
    }
    IDWriteFactory *factory;
    HRESULT hr = DWriteCreateFactory(DWRITE_FACTORY_TYPE_ISOLATED, __uuidof(IDWriteFactory),
                                     reinterpret_cast<IUnknown **>(&factory));
    if (FAILED(hr)) return fail("DWriteCreateFactory", hr);
    IDWriteFontFile *file;
    if (FAILED(hr = factory->CreateFontFileReference(argv[1], nullptr, &file)))
        return fail("CreateFontFileReference", hr);
    BOOL supported;
    DWRITE_FONT_FILE_TYPE file_type;
    DWRITE_FONT_FACE_TYPE face_type;
    UINT32 faces;
    if (FAILED(hr = file->Analyze(&supported, &file_type, &face_type, &faces)) || !supported)
        return fail("Analyze", hr);
    IDWriteFontFace *face;
    if (FAILED(hr = factory->CreateFontFace(face_type, 1, &file, 0, DWRITE_FONT_SIMULATIONS_NONE, &face)))
        return fail("CreateFontFace", hr);
    DWRITE_FONT_METRICS metrics;
    face->GetMetrics(&metrics);
    const float em = metrics.designUnitsPerEm;    // so positions come out in font units
    IDWriteTextAnalyzer *analyzer;
    if (FAILED(hr = factory->CreateTextAnalyzer(&analyzer))) return fail("CreateTextAnalyzer", hr);

    std::vector<DWRITE_FONT_FEATURE> features;
    for (int i = 2; i < argc; i++) {
        const wchar_t *t = argv[i];
        if (wcslen(t) != 4) {
            std::fprintf(stderr, "a feature tag has 4 letters\n");
            return 2;
        }
        features.push_back({DWRITE_FONT_FEATURE_TAG(DWRITE_MAKE_OPENTYPE_TAG(t[0], t[1], t[2], t[3])), 1});
    }
    DWRITE_TYPOGRAPHIC_FEATURES typographic = {features.data(), UINT32(features.size())};
    const DWRITE_TYPOGRAPHIC_FEATURES *typographic_list = &typographic;

    std::string line;
    while (std::getline(std::cin, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        std::wstring text = from_hex(line);
        Source source(text);
        Sink sink;
        if (!text.empty() && FAILED(hr = analyzer->AnalyzeScript(&source, 0, UINT32(text.size()), &sink)))
            return fail("AnalyzeScript", hr);
        std::sort(sink.runs.begin(), sink.runs.end(),
                  [](const Sink::Run &a, const Sink::Run &b) { return a.start < b.start; });
        std::string out;
        char buf[96];
        float pen = 0;
        for (const Sink::Run &run : sink.runs) {
            const WCHAR *s = text.data() + run.start;
            const UINT32 n = run.length;
            UINT32 room = 3 * n / 2 + 16, count = 0;
            std::vector<UINT16> cluster_map(n), ids;
            std::vector<DWRITE_SHAPING_TEXT_PROPERTIES> text_props(n);
            std::vector<DWRITE_SHAPING_GLYPH_PROPERTIES> glyph_props;
            UINT32 range = n;
            for (;;) {    // multiple substitutions can make far more glyphs than characters
                ids.resize(room);
                glyph_props.resize(room);
                hr = analyzer->GetGlyphs(s, n, face, FALSE, FALSE, &run.script, LOCALE, nullptr,
                                         features.empty() ? nullptr : &typographic_list,
                                         features.empty() ? nullptr : &range, features.empty() ? 0 : 1,
                                         room, cluster_map.data(), text_props.data(), ids.data(),
                                         glyph_props.data(), &count);
                if (hr != HRESULT_FROM_WIN32(ERROR_INSUFFICIENT_BUFFER)) break;
                room *= 2;
            }
            if (FAILED(hr)) return fail("GetGlyphs", hr);
            std::vector<FLOAT> advances(count);
            std::vector<DWRITE_GLYPH_OFFSET> offsets(count);
            if (FAILED(hr = analyzer->GetGlyphPlacements(
                           s, cluster_map.data(), text_props.data(), n, ids.data(), glyph_props.data(), count,
                           face, em, FALSE, FALSE, &run.script, LOCALE,
                           features.empty() ? nullptr : &typographic_list,
                           features.empty() ? nullptr : &range, features.empty() ? 0 : 1,
                           advances.data(), offsets.data())))
                return fail("GetGlyphPlacements", hr);
            // Each glyph's character: the first character of the cluster it starts or continues.
            std::vector<long> first(count, -1);
            for (long i = long(n) - 1; i >= 0; i--) first[cluster_map[i]] = long(run.start) + i;
            for (UINT32 g = 0; g < count; g++) {
                if (first[g] < 0) first[g] = g ? first[g - 1] : long(run.start);
                std::snprintf(buf, sizeof buf, " %u %ld %.3f %.3f", ids[g], first[g],
                              pen + offsets[g].advanceOffset, offsets[g].ascenderOffset);
                out += buf;
                pen += advances[g];
            }
        }
        std::printf("%.3f%s\n", pen, out.c_str());
        std::fflush(stdout);
    }
    return 0;
}
