# Spike — auto-editor vs ffmpeg silencedetect

**Status: throwaway. Not part of the product.**

Nothing in `src/` may import from this directory. Its outputs are gitignored.

## Question

v1 ships its silence analyzer on `ffmpeg -af silencedetect`. `auto-editor` was the originally
planned analyzer and was set aside because its distinctive value — motion detection and NLE
round-trip export — is out of v1 scope, while it would add a second toolchain.

This spike answers one question with measurement rather than preference:

> On a real speech recording, which producer yields better cuts — and by what standard?

## Blocked on

A real talking-head recording with natural pauses. Generated fixtures cannot answer this: a sine
tone with programmed gaps has no breath, no filler, and no trailing consonants, which is exactly
where the two approaches would differ.

This does **not** block v1.

## What to record when run

- versions of both tools, as actually installed (PyPI and GitHub disagree on auto-editor's
  latest version — record what installs)
- cut counts and total retained duration from each
- where the two disagree, and whether the disagreement is audible
- whether margin should be symmetric or asymmetric (design spec §11.4)

The finding belongs in the design spec, not here. This directory is deleted once the question
is answered.
