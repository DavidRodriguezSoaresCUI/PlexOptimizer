#pylint: disable=no-name-in-module, import-error, invalid-name, wrong-import-position, global-statement
''' This script tries to optimize video files for streaming playback on Plex or other
services, mainly by avoiding video and audio transcoding.

This is achieved by:
1. Converting video formats that are not h264, with bit depth other than 8-bit or
   with resolution superior to 1080p.
2. Converting non-widely-supported formats (vorbis, opus, flac, dts) to AAC if
   mono/stereo or ac3 for multi-channel
3. Converting text subtitle formats that need to be "burned into" the video stream
   to a more basic text format.
4. Using MP4 container for output when possible (MKV otherwise)

Note on experimental feature `mode`:
    >'lite': Produce an optimized file as a "high compatibility" version of the original,
      so replacing "low compatibility" streams. These files are meant to coexist with
      source files as an alternative. Recommended for most and default. Output should
      always be MP4. Warning: drops image-based subtitle streams (VobSub,PGS).
    >'full': Produce a file that contains all streams from the original file, plus the
      "high compatibility" ones. These files are meant to replace source files as a
      "superset" of its streams. NOT RECOMMENDED because video files with multiple video
      streams aren't supported on most players. Output is MP4 if possible but typically
      MKV. WARNING: this is an experimental feature
    >'standalone': Same as 'full' except it will not include "low compatibility" video
      streams. These files are meant to replace source files (if you don't care about
      potentially losing the original video stream). Use it if you absolutely don't want
      to have two versions of the same video or really need the disk space. Output is MP4
      if possible but usually MKV.

Requirements: Python >= 3.6, also ffmpeg and ffprobe (need to be callable by their name)

Known issues:
    >When converting, ffmpeg doesn't update some metadata, so inspecting output file with
     tools like MediaInfo may contain inaccurate information. This can be solved by re-muxing
     output files with tools like Mp4Box or MKVmerge.
    >Converting ASS subtitles can result in messy output: duplicate entries, one-frame
    entries, issues with concurrent entries, etc. Dealing with subtitles automatically
    with ffmpeg is hard in general.

WARNING:
    >Any lossy media conversion involves some information/quality loss. Keep the original
     files if possible. The author of this program isn't responsible for loss of data.
    >Dealing with subtitle streams is particularly hard because of the variety of format,
     difference between image-based and text-based formats, and the lossy nature of conversion
     between some of them. There is a clear compromise between compatibility and capability
     when it comes to subtitle codecs, so keep in mind that converted "high compatibility"
     subtitles ARE NOT EQUAL to the original and MAY BE UNUSABLE.
'''


EXPLANATION = '''\
                    | 'lite' mode | 'standalone' mode |   'full' mode    |
--------------------|-------------|-------------------|------------------|
'passthrough' codec |    copy     |       copy        |      copy        |
--------------------|-------------|-------------------|------------------|
'convert' codec     |   convert   | *copy AND convert | copy AND convert |
--------------------|-------------|-------------------|------------------|
unknown codec       |    drop     |       copy        |      copy        |
--------------------|-------------|-------------------|------------------|

* For video stream, only convert
'''

FIX_LOG = '''\
# FIX LOG

## Fix 01

### Problem

When converting subtitles (ASS->SRT), the output font size information may be applied
differently between players, so some may display text too small or large. There appear
to be no fix for this because it's how ffmpeg does the conversion. Other artifacts like
broken or missing text is to be expected. Worse, a report of Plex Smart TV app freezing
while trying to render such subtitles raised the importance of the issue.

### Fix description

- Idea 01: Using 'text' as encoder instead of 'srt' removes all markup tags. This may not be desirable,
as it also removes effects such as making the text bold or italic.

- Idea 02: It was discovered that when converting ASS subtitles to WebVTT first, then to SRT, the
<font ..> tag is discarded while bold and italic tags are kept.

- Idea 03: It was discovered that when converting ASS subtitles to 'mov_text', the
<font ..> tag is discarded while bold and italic tags are kept. Also, this codec
is compatible with the MP4 container.

### Decision

Idea 02 was selected and is pending implementation, with idea 01 was selected as alternative.
'''

FEATURE_IDEAS = '''\
> Convert image subtitles with tools based on Tesseract (like https://github.com/Tentacule/PgsToSrt)
'''

FULL_MODE_WARNING = '''\
WARNING: you chose `full` mode. Please read notes regarding this mode in the help
by running `plex_optimizer` with parameter `--help`. You must understand that this
feature is experimental and that video player support for output files is limited.

Press ENTER to continue or CRTL+C to quit
'''

HONORABLE_MENTIONS = '''\
The following links were insightful when crafting this script:
https://stackoverflow.com/questions/54659242/ffmpeg-convert-all-audio-streams-from-mkv-to-mp4
https://stackoverflow.com/questions/43727447/ffmpeg-recode-all-audio-streams-while-keeping-originals
https://stackoverflow.com/questions/32922226/extract-every-audio-and-subtitles-from-a-video-with-ffmpeg
https://support.plex.tv/articles/200471133-adding-local-subtitles-to-your-media/
'''

import argparse
import json
from collections import namedtuple
from pathlib import Path
from typing import List

from DRSlib.cli_ui import cli_explorer
from DRSlib.path_tools import file_collector
from DRSlib.execute import execute
from DRSlib.path_tools import find_available_path


CodecRule = namedtuple(typename='CodecRule', field_names=['passthrough','convert'])
ConversionStep = namedtuple(typename='ConversionStep', field_names=['codec', 'parameters'])
VIDEO_EXT = { '.mp4', '.mkv' }
CODEC_OPTIMIZATION_RULES = {
    "video": CodecRule(
        passthrough={},
        convert={ 'mjpeg', 'mpeg4', 'mpeg2video', 'hevc', 'av1' }
    ),
    "audio": CodecRule(
        passthrough={ 'mp3', 'aac', 'ac3', 'eac3' },
        convert={ 'flac', 'vorbis', 'opus', 'dts', 'mp2' }
    ),
    "subtitle": CodecRule(
        passthrough={ 'mov_text' },
        convert={ 'ass', 'ssa', 'subrip' }
    )
}
H264_EXTRA_PARAMS = [ "-preset", "slow", "-crf", "22" ]
FFMPEG_PARAMS = "-loglevel warning -stats -probesize 100G -analyzeduration 100G"
DEBUG = False
MKV_PATCH = {
    'mov_text': 'webvtt' # Fix for error `Subtitle codec 94213 is not supported.`
}

# V: 'mjpeg', 'h264', 'mpeg4', 'mpeg2video', 'hevc', 'av1'
# A: 'aac', 'vorbis', 'ac3', 'eac3', 'mp3', 'opus', 'flac', 'dts', 'mp2'
# S: 'ass', 'mov_text', 'subrip', 'hdmv_pgs_subtitle', 'dvd_subtitle'
# WEIRD: 'png'

CWD = Path(".").resolve()
SCRIPT_PATH = Path(__file__).resolve().parent
CODEC_TYPES = set(CODEC_OPTIMIZATION_RULES.keys())
CMD_ENCODE = lambda f, mode, mp4_ffmpeg_parameters, mkv_ffmpeg_parameters: f'''\
chcp 65001
@echo off
SET IN_FILE="{f.resolve()}"
SET OUT_FILE_MP4="{f.resolve().with_suffix(f'.optimized_{mode}.mp4')}"
SET OUT_FILE_MKV="{f.resolve().with_suffix(f'.optimized_{mode}.mkv')}"
IF EXIST %IN_FILE% (
    echo Converting %IN_FILE%..
    echo Trying to encode in a MP4 container & ( ffmpeg {FFMPEG_PARAMS} -i %IN_FILE% {' '.join(mp4_ffmpeg_parameters)} %OUT_FILE_MP4% ) || ( del %OUT_FILE_MP4% & echo Attempt failed. Trying to encode in a MKV container & ffmpeg {FFMPEG_PARAMS} -i %IN_FILE% {' '.join(mkv_ffmpeg_parameters)} %OUT_FILE_MKV% ) || ( del %OUT_FILE_MKV% & echo WARNING! ATTEMPTS TO ENCODE TO MP4 AND MKV FAILED! )
) ELSE (
    echo ERROR: File %IN_FILE% not found!
)
'''


def dump( root: Path, msg: str ) -> Path:
    ''' Dump message to file
    '''
    dump_file = find_available_path(
        root=root,
        base_name='dump.tmp',
        file=True
    )
    dump_file.write_text(
        msg,
        encoding='utf8',
        errors='xmlcharrefreplace'
    )
    return dump_file


def dump_json( root: Path, obj: str ) -> Path:
    ''' Dump message to file
    '''
    dump_file = find_available_path(
        root=root,
        base_name='dump.json',
        file=True
    )
    dump_file.write_text(
        json.dumps(
            obj,
            indent=2,
            default=str
        ),
        encoding='utf8',
        errors='xmlcharrefreplace'
    )
    return dump_file


def dir_to_work_on( root_dir: Path ) -> Path:
    ''' Returns a Path representing the directory
    selected by the user. Script is terminated on
    KeyboardInterrupt.
    '''
    return cli_explorer(
        root_dir,
        allow_mkdir=False
    )


def probe( _file: Path ) -> dict:
    ''' Use ffprobe to get stream information
    '''
    # Run ffprobe
    cmd = [
        'ffprobe',
        '-loglevel', 'error', # disable most messages
        '-show_entries', 'stream', # output all streams
        '-of', 'json', # output format as json
        _file
    ]
    stdX = execute( cmd, shell=False )
    # Handle and decode output
    if stdX['stderr'] != '':
        print("Something went wrong: ffprobe stderr is:")
        print(stdX['stderr'])
        return None
    try:
        file_info = json.loads(stdX['stdout'])
        assert "streams" in file_info, "No 'streams' in info"
    except (json.JSONDecodeError, AssertionError) as e:
        print(e)
        dump_file = dump(CWD, stdX['stdout'])
        print(f"FFprobe output is invalid, see file {dump_file} for content")
        return None

    # package information
    return {
        s['index']:s
        for s in file_info['streams']
        if s['codec_type'] in CODEC_TYPES
    }


def optimize_video_to_h264( idx, stream_info ) -> ConversionStep:
    ''' Convert video stream to h264 with resolution <=FHD and
    bit depth 8.
    '''
    w,h = stream_info.get("width",0), stream_info.get("height",0)
    res = []
    if w < 1 or h < 1:
        print(f"Warning: Can't retrieve width or height for stream {idx} (video)." \
            + "Assuming file isn't broken and resolution is <=1080p.")
    elif w > 1920:
        # resolution limit
        res += [ "-vf", "scale=w=1920:h=-1"]
    if stream_info.get("pix_fmt",'')=="yuv420p10le":
        # 10-bit -> 8bit
        res.append("-pix_fmt yuv420p")
    res += H264_EXTRA_PARAMS
    return ConversionStep(codec='h264', parameters=res)


def optimize_audio_to_aac_or_ac3( idx, stream_info ) -> ConversionStep:
    ''' Convert audio stream to aac or ac3
    '''
    nb_channels = stream_info.get("channels",0)
    if nb_channels < 1:
        print(f"Warning: stream {idx} (audio) doesn't hava a channel count." \
            + "Assuming mono or stereo.")
    if nb_channels <= 2:
        return ConversionStep(codec='aac', parameters=[ "-q:{idx}", "1.4" ])
    return ConversionStep(codec='ac3', parameters=[])


def optimize_subtitle_to_srt( *_ ) -> ConversionStep:
    ''' Used for ASS -> SRT conversion '''
    return ConversionStep(codec='srt', parameters=[])


def optimize_subtitle_to_mov_text( *_ ) -> ConversionStep:
    ''' Used for ASS -> tx3g (mov_text) conversion '''
    return ConversionStep(codec='mov_text', parameters=[])


def stream_optimization_step( idx: int, stream_info: dict, mode: str ) -> dict:
    ''' Plans optimization for a particular stream
    '''
    optimizations = {
        "video": optimize_video_to_h264,
        "audio": optimize_audio_to_aac_or_ac3,
        "subtitle": optimize_subtitle_to_mov_text
    }

    codec_type, codec_name = stream_info.get("codec_type"), stream_info.get("codec_name")

    if codec_name in CODEC_OPTIMIZATION_RULES[codec_type].passthrough:
        # Passthrough => copy
        return ConversionStep(codec='copy', parameters=[])
    elif codec_name not in CODEC_OPTIMIZATION_RULES[codec_type].convert:
        # Unlisted codec => drop or copy
        return ConversionStep(codec='drop' if mode=='lite' else 'copy', parameters=[])

    # Current stream needs to be converted => construct optimization plan
    stream_optimization_plan = optimizations[codec_type](idx,stream_info)
    # Edit title
    stream_title = stream_info.get("tags",{}).get("title")
    stream_optimization_plan = ConversionStep(
        codec=stream_optimization_plan.codec,
        parameters=stream_optimization_plan.parameters + [
            '-metadata:s:{idx}',
            f'title="[COMPAT] {stream_title}"' if stream_title else 'title="[COMPAT]"'
        ]
    )

    # Print info
    stream_lang = stream_info.get("tags",{}).get("language",'?')
    print(f"Optimizing stream {idx} (lang:{stream_lang}): " \
        + f"{codec_name} -> {stream_optimization_plan.codec}")

    return stream_optimization_plan


def streams_optimization( streams_info: dict, mode: str ) -> dict:
    ''' Plans optimization for video file, stream by stream
    '''
    return {
        idx:stream_optimization_step(idx, stream_info, mode)
        for idx, stream_info in streams_info.items()
    }



def produce_optimized_video_script( _file: Path, destination_dir: Path, optimization_plan: dict, mode: str, cmd_file: Path = None ) -> dict:
    ''' Writes a BAT script that produces optimized file using ffmpeg.

    Notes on ffmpeg:
    Select input file stream with: -map 0:<input_file_stream_index> h264
    Set video codec with: -c:<output_file_stream_index> h264
    '''
    assert mode in { 'lite', 'full', 'standalone' }

    highest_stream = max(optimization_plan.keys())

    def lite_cmd():
        nonlocal optimization_plan
        _cmd = []
        out_idx = 0
        for in_idx in range(highest_stream+1):
            if in_idx not in optimization_plan or optimization_plan[in_idx].codec=='drop':
                # Marked to be dropped, or probably not video, audio or subtitle
                print(f"Stream {in_idx} was dropped.")
                continue

            # idx in optimization_plan and not dropped => deal with 'copy', '<codec>'
            _codec, _parameters = optimization_plan[in_idx].codec, optimization_plan[in_idx].parameters
            _cmd += [ "-map", f"0:{in_idx}", f"-c:{out_idx}", _codec ]
            _cmd += [ p.replace('{idx}',str(out_idx)) for p in _parameters ]
            out_idx += 1

        return _cmd

    def full_cmd():
        nonlocal optimization_plan
        _cmd = []
        out_idx = 0 # stream id for output file
        for in_idx in range(highest_stream+1):

            if in_idx not in optimization_plan or optimization_plan[in_idx].codec=='drop':
                # Marked to be dropped, or probably not video, audio or subtitle
                raise ValueError(f"Did not expect for stream {in_idx} to be dropped with mode `full`.")

            _cmd += [ "-map", f"0:{in_idx}", f"-c:{out_idx}", 'copy' ]
            out_idx += 1

            _codec, _parameters = optimization_plan[in_idx].codec, optimization_plan[in_idx].parameters
            _cmd += [ "-map", f"0:{in_idx}", f"-c:{out_idx}", _codec ]
            _cmd += [ p.replace('{idx}',str(out_idx)) for p in _parameters ]
            out_idx += 1

        return _cmd

    def standalone_cmd():
        nonlocal optimization_plan
        _cmd = []
        out_idx = 0 # stream for output file
        for in_idx in range(highest_stream+1):

            if in_idx not in optimization_plan or optimization_plan[in_idx].codec=='drop':
                # Marked to be dropped, or probably not video, audio or subtitle
                raise ValueError(f"Did not expect for stream {in_idx} to be dropped with mode `standalone`.")

            _codec, _parameters = optimization_plan[in_idx].codec, optimization_plan[in_idx].parameters
            if _codec!='h264':
                # Not a "low compatibility" video stream => copy
                _cmd += [ "-map", f"0:{in_idx}", f"-c:{out_idx}", 'copy' ]
                out_idx += 1

            _cmd += [ "-map", f"0:{in_idx}", f"-c:{out_idx}", _codec ]
            _cmd += [ p.replace('{idx}',str(out_idx)) for p in _parameters ]
            out_idx += 1

        return _cmd

    def mkv_patch( commands: List[str] ) -> str:
        ''' Generates MKV-specific command for ffmpeg, to avoid incompatible codecs
        breaking conversion '''
        for s in commands:
            if s in MKV_PATCH:
                yield MKV_PATCH[s]
            else:
                yield s


    # Get command and write worker script
    mode_switch = { 'lite':lite_cmd, 'full':full_cmd, 'standalone':standalone_cmd }
    cmd = mode_switch[mode]()
    if not cmd_file:
        cmd_file = find_available_path(
            root=destination_dir,
            base_name=_file.with_suffix(f'.optimizer_{mode}.bat').name
        )
        print(f"Run '{cmd_file.resolve()}' to produce optimized video.")
    with cmd_file.open('a',encoding='utf8') as f:
        f.write(
            CMD_ENCODE(
                f=_file.resolve(),
                mode=mode,
                mp4_ffmpeg_parameters=cmd,
                mkv_ffmpeg_parameters=list(mkv_patch(cmd))
            ) + '\n'
        )


def get_args() -> argparse.Namespace:
    ''' Returns a namespace representing command-line arguments
    '''
    parser = argparse.ArgumentParser(
        prog="Plex Optimizer",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="If no DIR is given, you will be prompted at runtime."
    )
    parser.add_argument(
        'directory',
        metavar='DIR',
        nargs='?',
        help="(Optional) Directory containing video files to process."
    )
    parser.add_argument(
        '--mode',
        choices=['lite', 'full', 'standalone'],
        default='lite',
        help="See above for which option to choose"
    )
    parser.add_argument(
        '--just_one',
        action="store_true",
        help="Only process one file."
    )
    parser.add_argument(
        '--single_script',
        action="store_true",
        help="Only produce one script for all optimizations."
    )
    parser.add_argument(
        '--threads',
        action="store",
        help="Sets limit on threads used by h264 encoder."
    )
    return parser.parse_args()


def main():
    '''main'''

    args = get_args()
    global H264_EXTRA_PARAMS
    if args.threads:
        H264_EXTRA_PARAMS += [ '-threads', args.threads ]
    if args.mode=='full':
        input(FULL_MODE_WARNING)
    # Get source directory
    if args.directory:
        src_dir = Path(args.directory).resolve()
    if not args.directory or not src_dir.is_dir():
        try:
            base_dir = Path(input("Base path to explore: "))
            if not base_dir.is_dir():
                print("Dir not found. Using CWD..")
                base_dir = CWD

            src_dir = dir_to_work_on(base_dir)
        except KeyboardInterrupt:
            return

    # Collect files to optimize
    src_dir_files = list(
        filter(
            lambda f: f.suffix in VIDEO_EXT and '.optimized' not in f.name,
            file_collector( root=src_dir ) # recursive
        )
    )
    if len(src_dir_files)==0:
        print(f"No file found in {src_dir}!")
        return

    # Process files
    nb_files = len(src_dir_files)
    cmd_file = None
    if args.single_script:
        cmd_file = find_available_path(
            root=src_dir,
            base_name="optimize_all.bat"
        )
    for idx, f in enumerate(src_dir_files):
        print(f"[{idx+1}/{nb_files}] {f}")

        # Get file stream info
        streams_info = probe(f)

        # Optimize file
        optimization_plan = streams_optimization(streams_info, args.mode)
        if optimization_plan:
            produce_optimized_video_script(
                f,
                destination_dir=f.parent,
                optimization_plan=optimization_plan,
                mode=args.mode,
                cmd_file=cmd_file
            )

            if DEBUG:
                (f.parent / f"{f.stem}.opti_plan.json").write_text(
                    json.dumps(optimization_plan, indent=2),
                    encoding='utf8',
                    errors='ignore',
                )
            if args.just_one:
                break

    if args.single_script:
        print(f"Run '{cmd_file.resolve()}' to produce optimized videos.")


if __name__=="__main__":
    main()
    print("END OF PROGRAM")
