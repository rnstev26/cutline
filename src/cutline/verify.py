"""Compare a media artifact across one handoff, under a policy for THAT handoff.

The boundaries differ in kind, measured rather than assumed:

  auto-editor (a cut)      preserves rotation, geometry and audio parameters;
                           duration and frame count shrink.
  HyperFrames (composite)  legitimately consumes rotation into a fixed canvas
                           and takes the composition's duration; its audio
                           resampling is silent and worth a warning.

"Nothing may change rotation" is therefore wrong as a global rule, which is why
the rule set is a parameter.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cutline.probe import MediaInfo


@dataclass(frozen=True)
class Change:
    prop: str
    before: object
    after: object

    def __str__(self) -> str:
        return f"{self.prop}: {self.before!r} -> {self.after!r}"


@dataclass(frozen=True)
class Policy:
    name: str
    invariant: frozenset[str]
    may_change: frozenset[str] = frozenset()
    warn: frozenset[str] = frozenset()


@dataclass
class Report:
    boundary: str
    changes: list[Change] = field(default_factory=list)
    warnings: list[Change] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.changes

    def __str__(self) -> str:
        lines = [f"[{self.boundary}] {'OK' if self.ok else 'FAILED'}"]
        lines += [f"  violation: {c}" for c in self.changes]
        lines += [f"  warning:   {w}" for w in self.warnings]
        return "\n".join(lines)


_VIDEO = ("width", "height", "codec", "pix_fmt", "sar", "dar", "profile")
_AUDIO = ("sample_rate", "channels", "codec")

CUT_POLICY = Policy(
    name="cut",
    invariant=frozenset(
        ["rotation", *(f"video.{p}" for p in _VIDEO), *(f"audio.{p}" for p in _AUDIO)]
    ),
    may_change=frozenset(["duration", "video.nb_frames",
                          "video.start_time", "audio.start_time"]),
)

COMPOSITE_POLICY = Policy(
    name="composite",
    invariant=frozenset(["video.codec"]),
    may_change=frozenset(
        ["rotation", "duration", "video.width", "video.height", "video.nb_frames",
         "video.sar", "video.dar", "video.pix_fmt", "video.profile",
         "video.start_time", "audio.start_time"]
    ),
    warn=frozenset(["audio.sample_rate", "audio.channels", "audio.codec"]),
)


def _get(info: MediaInfo, prop: str):
    if "." not in prop:
        return getattr(info, prop, None)
    kind, attr = prop.split(".", 1)
    stream = getattr(info, kind, None)
    return None if stream is None else getattr(stream, attr, None)


def _all_props(policy: Policy) -> list[str]:
    return sorted(policy.invariant | policy.warn)


def verify(before: MediaInfo, after: MediaInfo, policy: Policy) -> Report:
    """Report every property that changed and should not have.

    Properties in neither `invariant` nor `warn` are not examined at all — the
    policy is an allow-list of what is checked, so adding a property to
    StreamInfo never silently widens a boundary's contract.
    """
    report = Report(boundary=policy.name)
    for prop in _all_props(policy):
        b, a = _get(before, prop), _get(after, prop)
        if b == a:
            continue
        change = Change(prop=prop, before=b, after=a)
        if prop in policy.invariant:
            report.changes.append(change)
        else:
            report.warnings.append(change)
    return report
