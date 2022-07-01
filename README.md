# [Plex Optimizer](https://github.com/DavidRodriguezSoaresCUI/PlexOptimizer)

This software aims at helping you with your movies/series library of video files by making them as **widely compatible** as possible.

This software was originally developed for low-power Plex servers that can't handle real-time transcoding, by producing "high compatibility" versions of video files in advance that can be streamed without transcoding to pretty much any device, but you may find it other uses !

> You may share your use case by opening an issue with title beginning with `[USECASE]`

## Contents of this repository

I am the exclusive owner of the content of this repository, unless explicitly stated.

Required to execute `Plex Optimizer`:
- `plex_optimizer.py`: the main script
- `codec_constraint_converter.py`: bespoke module for rule-based conversion planning with ffmpeg and ffprobe
- `os_detect.py`: taken from [scivision's pybashutils](https://github.com/scivision/pybashutils/blob/main/pybashutils/os_detect.py)
- `utils.py`: contains functions and stuff, mostly taken from my other project [DRSlib](https://github.com/DavidRodriguezSoaresCUI/DRSlib)
- `webvtt_sanitize.py`: bespoke script for a subtitle conversion step
- `format_compatibility.json`: contains information about MP4 and MKV containers' format compatibilities

Repository-specific:
- `CHANGELOG.md`: for changes and version information
- `README.md`: contains this text
- `LICENSE`: for copyright information
- `ELSE`: directory containing information and PoC used during development (some contents are owned by the `ffmpeg` or `mkvmerge` projects)
- `FFMPEGContainerTester`: directory containing related project made to determine container codec compatibility using FFMPEG, used during development

## Requirements

**WARNING**: For now, it was only tested on **Windows** and **WSL**. Full Linux support is pending.

- `Python` (version >=3.6) must be installed in your system to run the script.
  - see [official site](https://www.python.org/downloads/)

- `ffmpeg`, `ffprobe`: must be installed in your system and callable from the command line.
  - **Windows**: [Latest releases](https://github.com/GyanD/codexffmpeg/releases/tag/5.0.1) (if you don't know which one to get, download ``ffmpeg-*-full_build-shared.zip``)
  - Others: see [official site](https://ffmpeg.org/download.html)

- `mkvmerge`: Needed for proper MKV output because `ffmpeg` doesn't update metadata properly

- (Optional) [PgsToSrt](https://github.com/Tentacule/PgsToSrt): used to convert image-based `PGS` subtitles (found in Blu-Ray discs) to text

You can easily find guides on how to install these dependencies on your favorite search engine.

## Help

The help contains important information about how the `Plex Optimizer` script works and the implications of using it, so it's **highly recommended** to give it a read.

You can view the help with by typing `python plex_optimizer.py  -help` or `python3 plex_optimizer.py --help` into a terminal at the location of file `plex_optimizer.py`.

```
usage: Plex Optimizer [-h] [--mode {lite,full,standalone}] [--just_one]
                      [--single_script] [--threads THREADS]
                      [--format [FORMAT ...]] [--bitrate_limit BITRATE_LIMIT]
                      [--x264_preset X264_PRESET]
                      [--x264_crf X264_CRF | --x264_target_bitrate X264_TARGET_BITRATE]
                      [DIR]

 This script tries to optimize video files for streaming playback on Plex or other
services, mainly by avoiding video and audio transcoding.

This is achieved by:
1.Converting video formats that are not h264, with bit depth other than 8-bit or
  with resolution superior to 1080p.
2.Converting non-widely-supported formats (vorbis, opus, flac, dts) to AAC if
  mono/stereo or ac3 for multi-channel
3.Converting text subtitle formats that need to be "burned into" the video stream
  to a more basic text format.
4.(Possibly unnecessary) Using MP4 container for output when possible (MKV otherwise)

Note on feature `mode`:
>'lite': Produce an optimized file as a "high compatibility" version of the original,
 so replacing "low compatibility" streams. These files are meant to coexist with
 source files as an alternative. Recommended for most and default. Output should
 always be MP4. Warning: drops image-based subtitle streams (VobSub,PGS).
>'standalone': Same as 'full' except it will not include "low compatibility" video
 streams. These files are meant to replace source files (if you don't care about
 potentially losing the original video stream). Use it if you absolutely don't want
 to have two versions of the same video or really need the disk space. Output is MP4
 if possible but usually MKV.
>'full': [WARNING: THIS IS AN EXPERIMENTAL FEATURE] Produce a file that contains
 all streams from the original file, plus the "high compatibility" ones. These files
 are meant to replace source files as a "superset" of its streams. NOT RECOMMENDED
 because video files with multiple video streams aren't supported on most players.
 Output is typically MKV.

Requirements: Python >= 3.6, also ffmpeg and ffprobe (need to be callable by their name)

WARNING:
>Any lossy media conversion involves some information/quality loss. Keep the original
 files if possible. THE AUTHOR OF THIS PROGRAM ISN'T RESPONSIBLE FOR LOSS OF DATA.
>Dealing with subtitle streams is particularly hard because of the variety of format,
 difference between image-based and text-based formats, and the lossy nature of conversion
 between some of them. There is a clear compromise between compatibility and capability
 when it comes to subtitle codecs, so keep in mind that converted "high compatibility"
 subtitles ARE NOT EQUAL to the original and MAY BE UNUSABLE.

positional arguments:
  DIR                   (Optional) Directory containing video files to
                        process.

options:
  -h, --help            show this help message and exit
  --mode {lite,full,standalone}
                        See above for which option to choose. Default: lite
  --just_one            Only process one file.
  --single_script       Only produce one script for all optimizations.
  --threads THREADS     Sets limit on threads used by h264 encoder.
  --format [FORMAT ...]
                        Override output format range (Default equivalent to
                        `--format mp4 mkv`).
  --bitrate_limit BITRATE_LIMIT
                        Maximum bitrate for a stream (default: 7M=7000000).
                        Heavier streams are forcibly converted. Accepted
                        suffixes are K (kbps) and M (mbps) (case insensitive).
  --x264_preset X264_PRESET
                        Sets value for `-preset` used by h264 encoder.
  --x264_crf X264_CRF   Sets value for `-crf` used by h264 encoder (1-pass
                        mode).
  --x264_target_bitrate X264_TARGET_BITRATE
                        Sets value for `-b` used by h264 encoder (2-pass
                        mode).

If no DIR is given, you will be prompted at runtime.
```

**Note**: default is equivalent to ```python plex_optimizer.py --mode lite```

## Usage examples

For the following examples, it is assumed that the terminal's Current Working Directory contains the `Plex Optimizer` script.

- You want to produce a high compatibility version of file `D:\movies\avatar (2009).avi` and choose mode `lite`. First, you move the file to `D:\convert` then you can run :

    ```bash
    python plex_optimizer_2.py --mode lite "D:\convert"
    ```

    It tells you you can run script `D:\convert\avatar (2009).optimizer_lite.bat` for encoding, so you run :
    ```bash
    "D:\convert\avatar (2009).optimizer_lite.bat"
    ```
    This may take a few minutes/hours, but a "high compatibility" version this movie will be produced if needed.

- You want to produce a high compatibility version of files of a show located at `D:\shows\Steven Universe`, choose mode `standalone`. You do a test run first on one file :

    ```bash
    python plex_optimizer_2.py --mode standalone --just_one "D:\shows\Steven Universe"
    ```

    It tells you you can run script `D:\shows\Steven Universe\S01E01.optimizer_standalone.bat` for encoding, so you run :
    ```bash
    "D:\shows\Steven Universe\S01E01.optimizer_standalone.bat"
    ```

    It produces file `D:\shows\Steven Universe\S01E01.optimized_standalone.mkv`. You are satisfied with the result, so you run :

    ```bash
    python plex_optimizer_2.py --mode standalone --just_one "D:\shows\Steven Universe"
    ```

    It tells you you can run script `D:\shows\Steven Universe\optimize_all.bat` for encoding, so you run :
    ```bash
    "D:\shows\Steven Universe\optimize_all.bat"
    ```
    This may take a few minutes/hours, but a "high compatibility" version of any file found in `D:\shows\Steven Universe` that can be optimized will be produced.

## To-do list

- [High priority, likely to happen] Make it work on Linux systems (mostly requires a dedicated script formatter)

- [Med priority, unlikely to happen] Implement a custom subtitle conversion process for image-based subtitle streams (would involve OCR tools like Tesseract)
  > Using project [PgsToSrt](https://github.com/Tentacule/PgsToSrt) to convert PGS subtitles (SUP container) to SRT since version `0.0.dev1`.

- [Low priority, unlikely to happen] Implement a custom subtitle conversion process for text-based subtitle streams
  > Partially done; by finding better conversion steps and implementing a custom conversion step (see changelog for version `0.0.dev3`)

## Q & A

**Q: Why do I need to move a video file I want to optimize into an empty folder ?**

`Plex Optimizer` is designed for mass conversion, so it operates on folders. It explores the content and processes any video file it finds. If you want to process a single/few file(s), you must place it/them in its/their own folder. This is temporary and you can move them back afterward.

**Q: Plex Optimizer doesn't produce optimized versions for some files. Why ?**

A: This can be caused by a number of reasons, mainly:

- `Plex Optimizer` determined there was no need for a "high compatibility" version to be produced

- `Plex Optimizer` didn't find the files

- `ffprobe` couldn't read the files

- Something went wrong (in this case you may request help from the developer or post an issue)


**Q: The optimized version can't be read by my player/requires real-time transcoding during playback. What can I do ?**

Check what video format (and codecs) your player is natively capable of rendering, or what causes transcoding (check playback information, there should be information on why transcoding is happening). Please make sure the file being played back is the optimized version and that you issue is specifically related to the codec being unsupported on the playback device. Open an issue with the details of your case so the developer can investigate and solve the issue.

**Q: Can I get rid of the original files once optimized versions are produced ?**

You decide, but PLEASE read the help's content on modes to better understand what the optimized version files actually contain.

TL;DR: if you use mode `standalone` (or `full`), you may delete the original files if you want, but it's not recommended when using mode `lite`. The developer is not responsible for your data.

**Q: Warning messages appear during encoding. What do I do ?**

Warning messages appear for a whole heap of reasons (not all caused by PlexOptimizer itself), but the bottom line is that as long as you don't see the `"WARNING! ATTEMPTS TO ENCODE TO MP4 AND MKV FAILED!"` message appear and the output file exists and can be played back, there is nothing to worry.

If a particularly worrying message concerns you, you may request help from the developer or post an issue.
