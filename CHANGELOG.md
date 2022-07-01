# Changelog for Plex Optimizer
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!-- Sections should be one of: Added, Changed, Fixed, Removed -->


## [0.0.dev4] - 2022-07-01
_Note: issue of styled subtitles losing their font: Unfortunately I could not find information on supported font attachment formats for the MKV container so for now only `ttf` fonts are considered (`otf` may be supported also, requires investigation)._
### Added
- Streams of type `attachment` (format `ttf` only for now) are now copied in modes `standalone` and `full`. This was done to preserve look of original subtitle streams with font support. Note: forces use of MKV container
- `SUBTITLE_FORMAT_INVESTIGATION`: Summary of intel about subtitle formats
- CLI argument `--bitrate_limit` now accepts "human-readable" suffixes (eg: `12M` equivalent to `12000000` and `650k` equivalent to `650000`)


## [0.0.dev3] - 2022-06-24
_Note: issue of lost concurrent subtitles when converting to the MP4 container (MOV_TEXT format): While the introduced solution can have ugly results (when there are a lot of concurrent subtitles or some are very long), it remains an improvement in my opinion._
### Added
- `webvtt_sanitize.py` and `webvtt_sanitize_LR()`: A step was added for the (text-based subtitle) -> MOV_TEXT conversion because the WebVtt -> MOV_TEXT conversion had issues (can't deal with blank lines in subtitle text or with concurrent subtitles). See notes in `webvtt_sanitize.py` for more information.


## [0.0.dev2] - 2022-05-22
_Note: Motivation for adding 2-pass variable bitrate mode on h264 video encoding: Users may want to target a specific bitrate, or (indirectly) a specific file size._
### Added
- CLI arguments to control common libx264 parameters: `--x264_preset` (default is `slow`), and rate mode: either CRF with `--x264_crf` (default option; default value is `22`) or variable bitrate with `--x264_target_bitrate`
- Implementation of 1-pass (CRF) vs 2-pass for h264 video encoding
- 2-pass-specific temporary file cleanup

### Changes
- Fixed issue with streams to be copied would be included in temporary files
- Various other fixes and checks


## [0.0.dev1] - 2022-05-20
_Note: While this iteration is the first to be documented in this document, it does not qualify as a *release* by decision of the author. Reasoning hinges on both the willingness to document evolution of the current project and the unwillingness to produce releases due to the current "alpha" nature of the software._

_The author plans to start producing releases when this project reaches a more
stable state._

### Added
- This CHANGELOG file to hopefully document changes, improvement, bugfixes
  and more.
- Temporary directory creation and cleanup after finishing moved to optimization
  script because it made more sense to do it that way.
- Handling of `hdmv_pgs_subtitle` subtitles in function `optimize_subtitle_to_mov_text_or_srt` for format `mkv`.
- CLI argument `--format` to override default.

### Fixed
- Constant `CodecConstraintConverter.FFMPEG_CALL` was being modified in function
  `CodecConstraintConverter.remux`, leading to hard-to-debug issues and cascading
  command corruption.
- Function `CodecConstraintConverter.plan_conversion` was ignoring `output_format`
  argument and defaulting to `mp4`.
- CLI argument `--just_one` implementation is now functional.

### Changed
- User is now prompted to choose between recursive and non-recursive file gathering
  instead of defaulting to recursive.
- `display_status` now displays status of CLI arguments `--format` and `--single_script`
- Minor CLI improvements