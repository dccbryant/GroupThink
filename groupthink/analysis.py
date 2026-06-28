"""Stage 3 — find cross-session themes and select supporting quotes.

This is the judgement-heavy step and the heart of the tool: Claude reads every
session transcript and returns themes, each with 3-6 supporting quotes drawn
from across the sessions. Claude references quotes by **utterance id** only — it
never emits a timecode — so we resolve the real start/end from the transcripts
afterwards and hallucinated timecodes are structurally impossible.

When no ANTHROPIC_API_KEY is present, a naive keyword-grouping fallback keeps the
demo producing a (rougher) report end-to-end.
"""

from __future__ import annotations

from collections import defaultdict
import re

from pydantic import ValidationError

from .config import Settings
from .models import (
    AnalysisBrief,
    AnalysisResult,
    QuoteSelection,
    ResolvedQuote,
    ResolvedSubTheme,
    ResolvedTheme,
    ThemeDraft,
    ThemeReport,
    Transcript,
)

SYSTEM_PROMPT = """\
You are a senior qualitative researcher analyzing transcripts from a set of \
focus group sessions. Multiple sessions discussed the same topic with different \
respondents.

Your job is to identify the common themes that recur ACROSS the sessions — the \
ideas that come up again and again — and to assemble a presentable highlight \
reel from them.

For each theme:
- Write a short, presentable title (3-7 words) suitable for an on-screen card.
- Write a one or two sentence summary in a researcher's voice.
- Select 3-6 of the strongest supporting quotes. Prefer quotes drawn from \
DIFFERENT sessions and different speakers so the theme is shown to be shared, \
not the opinion of one person.

A theme may either list supporting quotes directly, or — when it naturally \
subdivides — group them under named sub-themes (each sub-theme having its own \
short title and supporting quotes). Use sub-themes when asked to, or when a \
theme clearly contains distinct sub-points.

Rules for quotes:
- Reference each quote by its exact utterance id (e.g. S2-0031), copied from the \
transcript. Never invent an id.
- Copy the quote text verbatim from that utterance — do not paraphrase.
- Only use utterances that actually appear in the transcript provided.

Aim for 3-6 themes, ordered from most to least prominent.\
"""


def render_transcripts(transcripts: list[Transcript]) -> str:
    """Flatten all sessions into a single id-tagged document for the prompt."""
    blocks: list[str] = []
    for t in transcripts:
        lines = [f"### Session {t.session_id} (file: {t.source_video})"]
        for u in t.utterances:
            lines.append(f"[{u.uid}] {u.speaker}: {u.text}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def parse_topics(text: str) -> list[str]:
    """Split the topics field into clean items.

    Prefers one-per-line; falls back to comma separation for a single line so a
    line like "Price, value and cost" isn't split mid-phrase.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    raw_items = lines if len(lines) > 1 else text.split(",")
    items: list[str] = []
    for raw in raw_items:
        # Strip a leading bullet or number marker like "- ", "* ", "1. ", "2) ".
        cleaned = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", raw).strip()
        if cleaned:
            items.append(cleaned)
    return items


def render_brief(brief: AnalysisBrief | None) -> str:
    """Render the researcher's guidance (topics, restriction, guide) for the prompt."""
    if brief is None or brief.is_empty:
        return ""
    parts: list[str] = []
    if brief.discussion_guide.strip():
        parts.append(
            "RESEARCH DISCUSSION GUIDE (the questions and structure that framed "
            "these sessions — use it for context on what was explored):\n"
            + brief.discussion_guide.strip()
        )
    topics = parse_topics(brief.topics)
    if topics:
        numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(topics, start=1))
        if brief.restrict_to_topics:
            parts.append(
                "TOPICS — these are the SECTION TITLES for the output. Use each topic "
                "VERBATIM as a theme title, keep them in the order given, and create "
                "exactly one theme per topic (this overrides the earlier 3-6 themes and "
                "ordering guidance). Within each topic, identify the SUB-THEMES that "
                "emerge from the sessions — give each sub-theme a short title and 1-4 "
                "supporting quotes, and put the quotes inside the sub-themes (use the "
                "`subthemes` field). Also write a one or two sentence summary for the "
                "topic. If a topic genuinely does not subdivide, you may instead attach "
                "3-6 quotes directly to it. Do NOT add any theme outside this list; omit "
                "a topic only if the sessions contain nothing relevant to it:\n\n" + numbered
            )
        else:
            parts.append(
                "TOPICS TO PRIORITISE — organise themes around these where the sessions "
                "support it, AND also surface any other strong themes that emerge on "
                "their own:\n\n" + numbered
            )
    return "\n\n".join(parts)


class ClaudeAnalyzer:
    name = "claude"

    def __init__(self, api_key: str, model: str) -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def analyze(
        self,
        transcripts: list[Transcript],
        project: str,
        brief: AnalysisBrief | None = None,
    ) -> AnalysisResult:
        transcript_text = render_transcripts(transcripts)
        brief_text = render_brief(brief)

        # The researcher's brief is the volatile part of the prompt; it goes
        # AFTER the cached transcript so re-runs with tweaked topics still hit
        # the cache on the (large) transcript prefix.
        task = "Identify the common themes across these sessions and select supporting quotes."
        if brief_text:
            task = brief_text + "\n\n" + task

        try:
            # Longer timeout than the SDK default keeps non-streaming requests
            # from tripping the 10-minute guard on big transcripts.
            response = self._client.with_options(timeout=600.0).messages.parse(
                model=self._model,
                # Generous budget — sub-themes nest more JSON, and adaptive
                # thinking shares this allowance, so 8k was getting truncated
                # mid-string on multi-topic runs.
                max_tokens=16000,
                # Theme-finding is judgement-heavy; let Claude think. Effort defaults
                # to "high", and parse() owns output_config.format, so we don't set
                # output_config here to avoid clobbering the response schema.
                thinking={"type": "adaptive"},
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        # Stable instructions cache with the transcript below.
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                # The transcript is large and reused across re-runs of
                                # the same project — cache it so iterating is cheap.
                                "type": "text",
                                "text": f"Project: {project}\n\nTranscripts:\n\n{transcript_text}",
                                "cache_control": {"type": "ephemeral"},
                            },
                            {"type": "text", "text": task},
                        ],
                    }
                ],
                output_format=AnalysisResult,
            )
        except ValidationError as exc:
            # The most common cause is the response getting cut off mid-JSON
            # because Claude ran out of room. Give the user something actionable.
            raise RuntimeError(
                "Claude's analysis was too long to fit in one response — the "
                "report's JSON was cut off. Try running with fewer focus topics, "
                "a shorter discussion guide, or a smaller batch of sessions."
            ) from exc
        result = response.parsed_output
        if result is None:
            raise RuntimeError(
                f"Claude did not return a parseable analysis (stop_reason={response.stop_reason})."
            )
        return result


class KeywordAnalyzer:
    """No-key fallback: cluster utterances by a few seed keywords.

    Deliberately simple — it exists so the pipeline produces *something* without
    an API key, not to rival Claude's judgement.
    """

    name = "keyword"

    _SEED_THEMES = {
        "Price and value": ["price", "pay", "expensive", "cost", "worth"],
        "Trust and credibility": ["trust", "brand", "claims", "reviews", "believe"],
        "Ease of use": ["setup", "complicated", "manual", "easy", "time"],
        "Design and appeal": ["design", "packaging", "premium", "gorgeous", "counter"],
    }

    def analyze(
        self,
        transcripts: list[Transcript],
        project: str,
        brief: AnalysisBrief | None = None,
    ) -> AnalysisResult:
        all_utterances = [u for t in transcripts for u in t.utterances]

        # Restricted mode: title one theme per user topic, matched by keyword.
        if brief is not None and brief.restrict_to_topics and brief.topics.strip():
            themes: list[ThemeDraft] = []
            for topic in parse_topics(brief.topics):
                words = [w.lower() for w in re.findall(r"[A-Za-z]+", topic) if len(w) > 3]
                matches = [
                    u for u in all_utterances
                    if words and any(w in u.text.lower() for w in words)
                ]
                if not matches:
                    continue
                themes.append(
                    ThemeDraft(
                        title=topic,
                        summary=f"What respondents said about {topic.lower()}.",
                        quotes=[
                            QuoteSelection(utterance_id=u.uid, quote=u.text,
                                           rationale="Relates to the topic.")
                            for u in matches[:6]
                        ],
                    )
                )
            return AnalysisResult(themes=themes)

        themes: list[ThemeDraft] = []

        for title, keywords in self._SEED_THEMES.items():
            matches = [
                u
                for u in all_utterances
                if any(k in u.text.lower() for k in keywords)
            ]
            if len(matches) < 3:
                continue
            quotes = [
                QuoteSelection(
                    utterance_id=u.uid,
                    quote=u.text,
                    rationale="Mentions the theme keyword.",
                )
                for u in matches[:6]
            ]
            themes.append(
                ThemeDraft(
                    title=title,
                    summary=f"Respondents repeatedly raised {title.lower()} across sessions.",
                    quotes=quotes,
                )
            )

        return AnalysisResult(themes=themes)


def build_analyzer(settings: Settings):
    """Claude when a key is present, keyword fallback otherwise."""
    if settings.has_anthropic:
        return ClaudeAnalyzer(settings.anthropic_api_key, settings.analysis_model)
    return KeywordAnalyzer()


# --------------------------------------------------------------------------- #
# Resolution: join the analysis back to real timecodes
# --------------------------------------------------------------------------- #


def resolve_report(
    analysis: AnalysisResult,
    transcripts: list[Transcript],
    project: str,
) -> ThemeReport:
    """Turn Claude's id-referenced themes into timecoded `ResolvedTheme`s.

    Quotes whose utterance id can't be found (e.g. a model slip) are dropped, and
    themes left with no resolvable quotes are dropped too.
    """
    index: dict[str, tuple[Transcript, "Utterance"]] = {}  # noqa: F821
    for t in transcripts:
        for u in t.utterances:
            index[u.uid] = (t, u)

    def resolve_quotes(selections: list[QuoteSelection]) -> list[ResolvedQuote]:
        out: list[ResolvedQuote] = []
        for sel in selections:
            found = index.get(sel.utterance_id)
            if found is None:
                continue
            transcript, utterance = found
            out.append(
                ResolvedQuote(
                    session_id=transcript.session_id,
                    source_video=transcript.source_video,
                    speaker=utterance.speaker,
                    quote=utterance.text,  # trust the transcript for what gets cut
                    rationale=sel.rationale,
                    start_ms=utterance.start_ms,
                    end_ms=utterance.end_ms,
                )
            )
        return out

    resolved_themes: list[ResolvedTheme] = []
    for theme in analysis.themes:
        resolved_subs: list[ResolvedSubTheme] = []
        for sub in theme.subthemes:
            sub_quotes = resolve_quotes(sub.quotes)
            if sub_quotes:
                resolved_subs.append(ResolvedSubTheme(title=sub.title, quotes=sub_quotes))
        flat_quotes = resolve_quotes(theme.quotes)
        if resolved_subs or flat_quotes:
            resolved_themes.append(
                ResolvedTheme(
                    title=theme.title,
                    summary=theme.summary,
                    subthemes=resolved_subs,
                    quotes=flat_quotes,
                )
            )

    return ThemeReport(project=project, themes=resolved_themes)
