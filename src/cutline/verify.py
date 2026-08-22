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
    note: str = ""

    def __str__(self) -> str:
        suffix = f" ({self.note})" if self.note else ""
        return f"{self.prop}: {self.before!r} -> {self.after!r}{suffix}"


# Every property §4.1 names, in the form `verify()` addresses it. A Policy must
# classify EVERY one of these into exactly one of invariant / may_change / warn,
# and may name nothing outside the set. Before this was enforced, `may_change`
# was assigned in three places and READ NOWHERE: `_all_props()` returned
# `invariant | warn`, so everything a policy called "may change" was not
# examined at all. That silently swallowed duration, frame count and per-stream
# start_time at the cut boundary -- including the frame count §4.1 describes as
# the one that "catches truncation".
#
# The union check is what makes the field load-bearing in the other direction
# too: adding a property to StreamInfo and to this set without classifying it in
# BOTH policies is an ImportError, not a silent omission.
_VIDEO = ("width", "height", "codec", "pix_fmt", "sar", "dar", "profile",
          "nb_frames", "start_time")
_AUDIO = ("sample_rate", "channels", "codec", "start_time")

CHECKED_PROPERTIES = frozenset(
    ["rotation", "duration", *(f"video.{p}" for p in _VIDEO), *(f"audio.{p}" for p in _AUDIO)]
)


@dataclass(frozen=True)
class Policy:
    name: str
    invariant: frozenset[str]
    may_change: frozenset[str] = frozenset()
    warn: frozenset[str] = frozenset()
    # A subset of may_change that may only move in ONE direction. §4.1's cut
    # row says duration and frame count "may shrink" -- which is not the same
    # permission as "may change", and until now the difference was unexpressed.
    may_shrink: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        buckets = (
            ("invariant", self.invariant),
            ("may_change", self.may_change),
            ("warn", self.warn),
        )
        for i, (a_name, a_set) in enumerate(buckets):
            for b_name, b_set in buckets[i + 1:]:
                both = a_set & b_set
                if both:
                    raise ValueError(
                        f"policy {self.name!r}: {sorted(both)} appears in both "
                        f"{a_name} and {b_name}; every property must land in exactly one"
                    )
        covered = self.invariant | self.may_change | self.warn
        missing = CHECKED_PROPERTIES - covered
        if missing:
            raise ValueError(
                f"policy {self.name!r} does not classify {sorted(missing)}. Every "
                "property in CHECKED_PROPERTIES must be invariant, may_change or warn "
                "-- an unclassified property is one this boundary never looks at."
            )
        unknown = covered - CHECKED_PROPERTIES
        if unknown:
            raise ValueError(
                f"policy {self.name!r} names {sorted(unknown)}, which is not in "
                "CHECKED_PROPERTIES; verify() would never read it"
            )
        stray = self.may_shrink - self.may_change
        if stray:
            raise ValueError(
                f"policy {self.name!r}: {sorted(stray)} is in may_shrink but not "
                "may_change; a direction constraint only means something on a "
                "property the boundary permits to move"
            )


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


# Both policies spell their sets out in full rather than deriving one bucket
# from the others. Deriving (e.g. `invariant = CHECKED_PROPERTIES - may_change`)
# would make Policy.__post_init__'s exhaustiveness check pass by construction —
# a guard on a target the code cannot make fail, which is precisely the class of
# defect this project exists to catch.
CUT_POLICY = Policy(
    name="cut",
    invariant=frozenset(
        ["rotation",
         "video.width", "video.height", "video.codec", "video.pix_fmt",
         "video.sar", "video.dar", "video.profile",
         "audio.sample_rate", "audio.channels", "audio.codec"]
    ),
    may_change=frozenset(["duration", "video.nb_frames",
                          "video.start_time", "audio.start_time"]),
    # §4.1: at the cut boundary duration "may shrink" — it may not grow. Frame
    # count follows it. This is not the whole truncation story (a shrink to 3%
    # of the source is still a shrink); the magnitude is bounded in flow.cut()
    # against the EDL auto-editor itself declared.
    may_shrink=frozenset(["duration", "video.nb_frames"]),
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
    # Nothing directional here: §4.1 says the composite's duration becomes the
    # COMPOSITION's, which may be longer or shorter than the source.
)


def _get(info: MediaInfo, prop: str):
    if "." not in prop:
        return getattr(info, prop, None)
    kind, attr = prop.split(".", 1)
    stream = getattr(info, kind, None)
    return None if stream is None else getattr(stream, attr, None)


def _all_props(policy: Policy) -> list[str]:
    """Every property the policy classifies — including `may_change`.

    `may_change` used to be excluded here, which made it a comment rather than a
    rule: the properties in it were never read, so a direction constraint on
    them could not exist.
    """
    return sorted(policy.invariant | policy.may_change | policy.warn)


def _grew(before: object, after: object) -> bool:
    """Did a may-shrink property move the wrong way?

    Fails CLOSED. If either side is missing, or is not a number, the direction
    cannot be established — and a value you could not read is never evidence
    that the change was safe, so it is reported. bool is excluded explicitly
    because it is an int subclass and ordering two flags means nothing.
    """
    if isinstance(before, bool) or isinstance(after, bool):
        return True
    if not isinstance(before, int | float) or not isinstance(after, int | float):
        return True
    return after > before


def verify(before: MediaInfo, after: MediaInfo, policy: Policy) -> Report:
    """Report every property that changed and should not have.

    The policy is a total classification of CHECKED_PROPERTIES rather than an
    allow-list of what is looked at: `invariant` must be identical, `warn`
    records a change without failing, and `may_change` permits movement — in one
    direction only where the property is also in `may_shrink`.
    """
    report = Report(boundary=policy.name)
    for prop in _all_props(policy):
        b, a = _get(before, prop), _get(after, prop)
        if b == a:
            continue
        if prop in policy.invariant:
            report.changes.append(Change(prop=prop, before=b, after=a))
        elif prop in policy.warn:
            report.warnings.append(Change(prop=prop, before=b, after=a))
        elif prop in policy.may_shrink and _grew(b, a):
            report.changes.append(
                Change(prop=prop, before=b, after=a,
                       note="this boundary permits a shrink, not a growth")
            )
    return report
