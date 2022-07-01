#pylint: disable=no-name-in-module, import-error, invalid-name, wrong-import-position, global-statement
''' This script tries to optimize video files for streaming playback on Plex or other
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
'''


EXPLANATION = '''\
                    | 'lite' mode | 'standalone' mode |   'full' mode    |
--------------------|-------------|-------------------|------------------|
'passthrough' codec |    copy     |       copy        |      copy        |
--------------------|-------------|-------------------|------------------|
'convert' codec     |   convert   | convert AND copy* | convert AND copy |
--------------------|-------------|-------------------|------------------|
attachments**       |    drop     |       copy        |      copy        |
--------------------|-------------|-------------------|------------------|
unknown codec       |    drop     |       copy        |      copy        |
--------------------|-------------|-------------------|------------------|

* For video stream, only convert
** Typically font files (see Matroska reference: https://www.matroska.org/technical/attachments.html)
'''

SUBTITLE_FORMAT_INVESTIGATION = '''\
         | Type  | Compatibility | burn** | bold/italic | concurrent subtitles | custom font | custom placement  | ffmpeg codec name
---------|-------|---------------|--------|-------------|----------------------|-------------|-------------------|-------------------
ASS/SSA  | Text  |     MKV       |  Yes*  |    Yes      |         Yes          |    Yes      |       Yes         |       ass
---------|-------|---------------|--------|-------------|----------------------|-------------|-------------------|-------------------
MOV_TEXT | Text  |     MP4       |  No*   |    Yes*     |         No*          |    No*      |       No*         |     mov_text
---------|-------|---------------|--------|-------------|----------------------|-------------|-------------------|-------------------
SRT      | Text  |     MKV       |  No*   |    Yes*     |         Yes*         |     ?       |        ?          |      subrip
---------|-------|---------------|--------|-------------|----------------------|-------------|-------------------|-------------------
WebVtt   | Text  |   MKV (MP4?)  |   ?    |    Yes*     |         Yes*         |     ?       |        ?          |      webvtt
---------|-------|---------------|--------|-------------|----------------------|-------------|-------------------|-------------------
VOBSUB   | Image |   MKV (MP4?)  |  Yes   |    N/A      |          ?           |    N/A      |        ?          |    dvd_subtitle
---------|-------|---------------|--------|-------------|----------------------|-------------|-------------------|-------------------
PGS      | Image |     MKV       |  Yes   |    N/A      |          ?           |    N/A      |        ?          |  hdmv_pgs_subtitle
---------|-------|---------------|--------|-------------|----------------------|-------------|-------------------|-------------------

* Experimentally verified
** Means: "Typically requires Plex to "burn" subtitle stream into video stream,
   therefore requiring video encoding."

# Notes

## MOV_TEXT
https://en.wikipedia.org/wiki/MPEG-4_Part_17
Also known as 'TTXT' and 'tx3g'
Exclusive to MP4 container and basically the go-to subtitle format for MP4.

## WebVtt
Similar to SRT but supposedly supported by MP4. Hasn't received much investigative
effort past being an intermediary format for ASS -> MOV_TEXT conversion.

## PGS
Can be stored in a SUP container file, converted to SRT using OCR tools.

## VOBSUB
A pain to deal with, can probably be converted to srt using OCR tools.
'''

DEPRECATED_KNOWN_ISSUES = '''\
>When converting, ffmpeg doesn't update some metadata, so inspecting output file with
 tools like MediaInfo may contain inaccurate information. This can be solved by re-muxing
 output files with tools like Mp4Box or MKVmerge. [May have been fixed since v0.0.dev1]
>Converting ASS subtitles can result in messy output: duplicate entries, one-frame
 entries, issues with concurrent entries, etc. Dealing with subtitles automatically
 with ffmpeg is hard in general. [Improved since v0.0.dev3]
'''

DEPRECATED_FIX_LOG = '''\
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

- Useful link on MP4 subtitles on GPAC's GitHub:
    https://github.com/gpac/gpac/wiki/Subtitling-with-GPAC

### Decision

Idea 02 was selected and is pending implementation, with idea 01 was selected as alternative.
'''

DEPRECATED_FEATURE_IDEAS = '''\
> Convert image subtitles with tools based on Tesseract (like https://github.com/Tentacule/PgsToSrt)
'''

FULL_MODE_WARNING = '''\
WARNING: you chose `full` mode. Please read notes regarding this mode in the help
by running `plex_optimizer` with parameter `--help`. You must understand that this
feature is experimental and that video player support for output files is limited.

Press ENTER to continue or CRTL+C to quit'''

HONORABLE_MENTIONS = '''\
The following links were insightful when crafting this script:
https://stackoverflow.com/questions/54659242/ffmpeg-convert-all-audio-streams-from-mkv-to-mp4
https://stackoverflow.com/questions/43727447/ffmpeg-recode-all-audio-streams-while-keeping-originals
https://stackoverflow.com/questions/32922226/extract-every-audio-and-subtitles-from-a-video-with-ffmpeg
https://support.plex.tv/articles/200471133-adding-local-subtitles-to-your-media/
https://en.wikipedia.org/wiki/Comparison_of_video_container_formats
https://superuser.com/a/1363012 # about libx264 2-pass
https://github.com/gpac/gpac/wiki/Subtitling-with-GPAC
'''

import argparse
from pathlib import Path
from typing import List

from codec_constraint_converter import CodecConstraintConverter, CodecRule, FFMPEGConvertStream, FFMPEGExtractStream, ExternalCommand, DropStream
from utils import find_available_path, cli_explorer, file_collector
from os_detect import Os

# Adapt these constants to your needs
SRC_FILE_EXT = { '.mp4', '.mkv' }
PGSTOSRT_DLL = Path('G:/Downloads/PgsToSrt-master/PgsToSrt/out/PgsToSrt.dll')

# Dont touch these values unless you know what you're doing
FFMPEG_PARAMETERS = ["-loglevel", "warning", "-stats", "-probesize", "100G", "-analyzeduration", "100G"]
H264_EXTRA_PARAMS = None # [ "-preset", "slow", "-crf", "23" ]

CWD = Path(".").resolve()
SCRIPT_PATH = Path(__file__).resolve().parent


def optimize_video_to_h264(*_, **kwargs):
    ''' Convert video stream to h264 with resolution <=FHD and
    bit depth 8.
    '''
    # print(f"args:{args}, kwargs:{kwargs}")
    stream_info = kwargs['stream_info']
    w,h = stream_info.get("width",0), stream_info.get("height",0)
    param = []
    if w < 1 or h < 1:
        print(f"Warning: Can't retrieve width or height for stream {stream_info['index']} (video)." \
            + "Assuming file isn't broken and resolution is <=1080p.")
    elif w > 1920:
        # resolution limit
        param += [ "-vf", "scale=w=1920:h=-1"]
    if stream_info.get("pix_fmt",'')=="yuv420p10le":
        # 10-bit -> 8bit
        param.append("-pix_fmt yuv420p")

    param += H264_EXTRA_PARAMS
    # 1-pass mode
    if "-crf" in H264_EXTRA_PARAMS:
        return [ FFMPEGConvertStream(codec='h264', parameters=param, output_format='mp4') ]
    # 2-pass mode
    return [
        FFMPEGConvertStream(codec='h264', parameters=param + ['-pass','1','-f','mp4'], output_format='[NULL]', repr_complement=' (1/2 pass)'),
        FFMPEGConvertStream(codec='h264', parameters=param + ['-pass','2'], output_format='mp4', repr_complement=' (2/2 pass)')
    ]


def optimize_audio_to_aac_or_ac3(*_, **kwargs):
    ''' Convert audio stream to aac or ac3
    '''
    # print(f"args:{args}, kwargs:{kwargs}")
    stream_info = kwargs['stream_info']
    nb_channels = stream_info.get("channels",0)
    if nb_channels < 1:
        raise ValueError(f"Warning: stream {stream_info['index']} (audio) doesn't hava a channel count." \
            + "Assuming mono or stereo.")
    if nb_channels <= 2:
        return [ FFMPEGConvertStream(codec='aac', parameters=["-q:{out_stream}", "1.4"]) ]
    return  [ FFMPEGConvertStream(codec='ac3') ]


def PGS_OCR_to_SRT_command( lang: str ) -> list:
    ''' Use project PgsToSrt to convert PGS subtitles (SUP container) to SRT
    see: https://github.com/Tentacule/PgsToSrt
    '''
    return ExternalCommand(
        command=[
            'dotnet', PGSTOSRT_DLL,
            '--input', "{in_file}",
            #'--output', "{out_file}", # Bug with PgsToStr: doesn't work
            '--tesseractlanguage', lang
        ],
        output_codec='subrip',
        output_format='srt',
        custom_output_file=lambda _in_file: _in_file.with_suffix('.srt')
    )


def webvtt_sanitize_LR() -> list:
    ''' Use external script to 'sanitize'/optimize webvtt for conversion to
    MOV_TEXT
    '''
    external_script = SCRIPT_PATH / 'webvtt_sanitize.py'
    assert external_script.is_file()
    return ExternalCommand(
        command=[
            'python', external_script,
            '-i', "{in_file}",
            '-o', "{out_file}"
        ],
        output_codec='webvtt (optimized)',
        output_format='vtt'
    )


def optimize_subtitle_to_mov_text_or_srt(*_, **kwargs):
    ''' Subtitle conversion to mov_text or srt '''
    # print(f"args:{args}, kwargs:{kwargs}")
    codec, output_format = kwargs['stream_info']['codec_name'], kwargs['format']

    if output_format=='mp4':
        if codec=='mov_text': # natiely compatible
            return [ FFMPEGConvertStream(codec='copy', output_format='mp4') ]
        if codec in {'webvtt', 'subrip'}: # need simple conversion step
            return [
                webvtt_sanitize_LR(),
                FFMPEGConvertStream(codec='mov_text', output_format='mp4')
            ]
        if codec=='ass': # need complex conversion step
            return [
                FFMPEGExtractStream( codec='webvtt', output_format='vtt'),
                webvtt_sanitize_LR(),
                FFMPEGConvertStream( codec='mov_text', output_format='mp4' )
            ]
        if codec=="hdmv_pgs_subtitle": # need complex conversion step including OCR
            _lang = kwargs['stream_info'].get('tags',{}).get('language',None)
            return [
                FFMPEGExtractStream( codec='copy', output_format='sup' ),
                PGS_OCR_to_SRT_command( lang=_lang ),
                FFMPEGConvertStream( codec='mov_text', output_format='mp4' )
            ]
        # else: not handled => Drop stream
        return [ DropStream() ]

    if output_format=='mkv':
        if codec=='subrip': # natively compatible
            return [ FFMPEGConvertStream(codec='copy', output_format='mkv') ]
        if codec in {'webvtt', 'mov_text'}: # simple conversion for incompatible or less popular codec
            return [ FFMPEGConvertStream(codec='subrip', output_format='mkv') ]
        if codec in {'ass', 'ssa'}: # need complex conversion step
            return [
                FFMPEGExtractStream( codec='webvtt', output_format='vtt'),
                FFMPEGConvertStream( codec='subrip', output_format='srt' )
            ]
        if codec=="hdmv_pgs_subtitle": # need complex conversion step including OCR
            _lang = kwargs['stream_info'].get('tags',{}).get('language',None)
            return [
                FFMPEGExtractStream( codec='copy', output_format='sup' ),
                PGS_OCR_to_SRT_command( lang=_lang )
            ]
        # else: not handled => Drop stream
        return [ DropStream() ]

    raise ValueError(f"Unexpected format '{format}'")


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
        help="See above for which option to choose. Default: lite"
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
    parser.add_argument(
        '--format',
        nargs="*",
        default=["mp4","mkv"],
        help="Override output format range (Default equivalent to `--format mp4 mkv`)."
    )
    parser.add_argument(
        '--bitrate_limit',
        action="store",
        default='7M',
        help="Maximum bitrate for a stream (default: 7M=7000000). Heavier streams are forcibly converted. Accepted suffixes are K (kbps) and M (mbps) (case insensitive)."
    )
    parser.add_argument(
        '--x264_preset',
        action="store",
        default='slow',
        help="Sets value for `-preset` used by h264 encoder."
    )
    x264_rate = parser.add_mutually_exclusive_group()
    x264_rate.add_argument(
        '--x264_crf',
        action="store",
        default='22',
        help="Sets value for `-crf` used by h264 encoder (1-pass mode)."
    )
    x264_rate.add_argument(
        '--x264_target_bitrate',
        action="store",
        help="Sets value for `-b` used by h264 encoder (2-pass mode)."
    )
    return parser.parse_args()


def yes_or_no( msg: str ) -> bool:
    ''' Prompts the user for a Y/N '''
    while True:
        _user_input = input(msg + " [Y/N] ")
        if len(_user_input)!=1:
            continue
        if _user_input.lower()=='y':
            return True
        if _user_input.lower()=='n':
            return False


def get_files( src_dir: Path ) -> List[Path]:
    ''' Get list of video files within `src_dir`
    '''
    _recursive = yes_or_no("Should the file search be recursive ?")
    return list(
        filter(
            lambda f: f.suffix in SRC_FILE_EXT and '.optimized' not in f.name,
            file_collector(
                root=src_dir,
                pattern=('**' if _recursive else '.')+'/*.*'
            )
        )
    )


def display_status( args: argparse.Namespace, src_dir: Path, files: List[Path] ) -> None:
    ''' Get list of video files within `src_dir`
    '''
    print("="*40)
    print("[Plex Optimizer]".center(40))
    print("="*40)
    print(f"Found {len(files)} files in `{src_dir}`:")
    for idx,f in enumerate(files):
        if idx>10:
            print("[...]")
            break
        print(f">{f.relative_to(src_dir)}")

    print(f"Mode: {args.mode}")
    print(f"Output format(s): {args.format}")
    if args.single_script:
        print("Single script mode active")
    print(f"Bitrate limit: {args.bitrate_limit}")
    print("="*40)


def main():
    ''' main '''

    args = get_args()

    # crafting H264_EXTRA_PARAMS from CLI arguments
    global H264_EXTRA_PARAMS
    if args.x264_target_bitrate is None:
        H264_EXTRA_PARAMS = [ "-preset", args.x264_preset, "-crf", args.x264_crf ]
    else:
        H264_EXTRA_PARAMS = [ "-preset", args.x264_preset, "-b:{out_stream}", args.x264_target_bitrate ]

    if args.mode=='full':
        print(FULL_MODE_WARNING)
        input("")

    # Get source directory
    if args.directory:
        src_dir = Path(args.directory).resolve()
    if not args.directory or not src_dir.is_dir():
        try:
            base_dir = Path(input("Base path to explore: "))
            if not base_dir.is_dir():
                print("Dir not found. Using CWD..")
                base_dir = CWD

            src_dir = cli_explorer(
                root_dir=base_dir,
                allow_mkdir=False
            )
        except KeyboardInterrupt:
            return

    # Collect files to optimize
    src_dir_files = get_files(src_dir)
    if len(src_dir_files)==0:
        print(f"No file found in {src_dir}!")
        return
    if args.just_one:
        src_dir_files = [ src_dir_files[0] ]

    # Display status to user
    display_status(args, src_dir, src_dir_files)
    input("[PRESS ENTER TO CONTINUE]")

    # Define converter
    format_rules = {
        'mp4': {
            'video': CodecRule(
                passthrough={ 'h264' },
                convert={ 'mjpeg', 'mpeg4', 'mpeg2video', 'hevc', 'av1', "vp9" }
            ),
            'audio': CodecRule(
                passthrough={ 'mp2', 'mp3', 'aac', 'ac3', 'eac3' },
                convert={ 'flac', 'vorbis', 'opus', 'dts' }
            ),
            'subtitle': CodecRule( # missing: 'dvd_subtitle'
                passthrough={ 'mov_text' },
                convert={ 'webvtt', 'ass', 'subrip', "hdmv_pgs_subtitle" }
            ),
            'attachment': CodecRule(
                passthrough={},
                convert={}
            )
        },
        'mkv': {
            'video': CodecRule(
                passthrough={ 'h264' },
                convert={ 'mjpeg', 'mpeg4', 'mpeg2video', 'hevc', 'av1', "vp9" }
            ),
            'audio': CodecRule(
                passthrough={ 'mp2', 'mp3', 'aac', 'ac3', 'eac3' },
                convert={ 'flac', 'vorbis', 'opus', 'dts' }
            ),
            'subtitle': CodecRule( # missing: 'dvd_subtitle'
                passthrough={ 'subrip' },
                convert={ 'mov_text', 'webvtt', 'ass', "hdmv_pgs_subtitle" }
            ),
            'attachment': CodecRule(
                passthrough={ 'ttf' },
                convert={}
            )
        }
    }
    conversion_rules = {
        'video': optimize_video_to_h264,
        'audio': optimize_audio_to_aac_or_ac3,
        'subtitle': optimize_subtitle_to_mov_text_or_srt
    }
    keep_original_streams = {
        'video': args.mode == 'full',    # Only keep original video stream on `full` mode
        'audio': args.mode != 'lite',    # Only drop original audio stream on `lite` mode
        'subtitle': args.mode != 'lite', # Only drop original audio stream on `lite` mode
        'attachment': args.mode != 'lite' # Only drop attachments on `lite` mode
    }
    _max_bitrate = args.bitrate_limit.lower().replace('k','000').replace('m','000000')
    converter = CodecConstraintConverter(
        ffmpeg_parameters=FFMPEG_PARAMETERS,
        format_rules=format_rules,
        conversion_rules=conversion_rules,
        drop_unknown_streams=args.mode == 'lite',
        keep_original_streams_rules=keep_original_streams,
        bitrate_limit=int(_max_bitrate)
    )

    is_windows = Os().windows
    print("Script type: " + ('windows' if is_windows else 'bash'))
    produce_script = converter.produce_cmd_script if is_windows else converter.produce_bash_script
    script_ext = 'bat' if is_windows else 'sh'

    # Process files
    nb_files = len(src_dir_files)
    script_files = []
    for idx, f in enumerate(src_dir_files):
        script_file = find_available_path(
            root=f.parent,
            base_name=f.with_suffix(f'.optimizer.{args.mode}.{script_ext}').name
        )
        for _fmt in args.format:
            print(f"\n[{idx+1}/{nb_files}] {f.name} -> {_fmt}")
            # Make file
            out_file = find_available_path(
                root=f.parent,
                base_name='.'.join([f.stem,args.mode,_fmt]),
                file=True
            )
            # Plan conversion
            conversion_commands = converter.plan_conversion(
                file=f,
                output_format=_fmt,
                output_file=out_file
            )
            if conversion_commands: # format supports conversion => craft script
                # Patch for MKV files
                if _fmt=='mkv':
                    # Use mkvmerge to remux output file
                    tmp_file = out_file.with_suffix('..mkv')
                    conversion_commands += [
                        ['REN', out_file, f'"{tmp_file.name}"' ],
                        ['mkvmerge', '-o', out_file, tmp_file ],
                        ['DEL', tmp_file]
                    ]
                # Remove temporary files when using 2-pass mode
                if args.x264_target_bitrate:
                    conversion_commands += [
                        ['DEL', 'ffmpeg2pass-0.log.mbtree'],
                        ['DEL', 'ffmpeg2pass-0.log']
                    ]
                # Produce script
                produce_script(
                    script=script_file,
                    commands=conversion_commands
                )
                script_files.append(script_file)
                break

    if args.single_script:
        # craft a `optimize_all` script
        script_file = find_available_path(
            root=src_dir,
            base_name="optimize_all.bat"
        )
        commands = [['chcp 65001\n@echo off']]
        for _script_file in script_files:
            if is_windows:
                commands += [[f'ECHO Processing file "{_script_file}"']]
                commands += [[f'CALL "{_script_file}"']]
            else:
                commands += [[f'echo "Processing file {_script_file}"']]
                commands += [[f'exec "{_script_file}"']]
        produce_script(
            script=script_file,
            commands=commands
        )


if __name__=="__main__":
    main()
    print("\nEND OF PROGRAM")
