''' A very simple script to get container codec compatibility
by using bruteforce with FFMPEG.

Usage: Lauch this script, type container when prompted, watch
codecs being tried one by one and find report file after execution.

Note: ffmpeg may hang on some codecs. Symptom: Encoding takes more than
15-30 seconds AND checking output temporary file's properties shows it
is small (<1ko) and doesn't grow. You may kill its process using
task manager or equivalent.

WARNING: The list of "compatible codecs" produced likely is incomplete
because of the limitations of FFMPEG, which can't encode to any format.
In particular, some image-based subtitles formats will probably be missing.
Recommendation: cross-check with online resources.
(eg: https://en.wikipedia.org/wiki/Comparison_of_video_container_formats)

KNOWN ISSUES:
- MP4 should support WebVTT subtitles but ffmpeg can't do it (see:
  https://github.com/gpac/gpac/wiki/Subtitling-with-GPAC)
- MP4 should support AV1,h263 video but ffmpeg can't do it
- MP4 should not support dirac but ffmpeg can do it
- MP4 should support VC-1 video but ffmpeg can't encode it


You can get sample video files from :
- https://mkvtoolnix.download/samples/vsshort-vorbis-subs.mkv (video file including 2 srt streams)
- https://gotranscript.com/captions-and-subtitles-samples (video file + srt file, so you need to remux them)
'''

import argparse
import json
import subprocess
from typing import Iterable, Dict
from pathlib import Path

FFMPEG_CALL = [
    'ffmpeg',
    '-y', # overwrite files
    '-loglevel', 'warning',
    '-probesize', '100G',
    '-analyzeduration', '100G'
]

FFMPEG_PATCH_ENCODER = {
    'opus': 'libopus',
    'vp8': 'libvpx',
    'vorbis': 'libvorbis',
    'dvb_subtitle': 'dvbsub',
    'dvd_subtitle': 'dvdsub'
}

SCRIPT_PATH = Path(__file__).resolve().parent

def execute( command: Iterable[str], shell: bool = False, timeout: int = None ) -> Dict[str,str]:
    ''' Passes command to subprocess.Popen, retrieves stdout/stderr and performs
    error management.
    Returns a dictionnary containing stdX.
    Upon command failure, prints exception and returns empty dict. '''

    PIPE = subprocess.PIPE
    with subprocess.Popen( command, stdout=PIPE, stderr=PIPE, shell=shell ) as process:
        # wait and retrieve stdout/err
        try:
            _stdout, _stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            print("Caught TimeoutExpired")
            process.kill()
            print("Killed process")
            _stdout, _stderr = process.communicate()

        # handle text encoding issues and return stdX
        return {
            'stdout': _stdout.decode('utf8', errors='backslashreplace'),
            'stderr': _stderr.decode('utf8', errors='backslashreplace')
        }


def get_ffmpeg_codecs() -> dict:
    ''' Retrieves codecs fully supported by FFMPEG (encoding and decoding)
    Returns them by category.
    '''
    ffmpeg_codecs_raw = execute( ['ffmpeg', '-codecs'] )['stdout']
    assert ffmpeg_codecs_raw

    codec_type = lambda x: 'video' if 'V' in x else ('audio' if 'A' in x else ('subtitle' if 'S' in x else None))
    ffmpeg_codecs = {
        line_items[1]: codec_type(line_items[0])
        for line_items in [
            line.split()
            for line in ffmpeg_codecs_raw.splitlines()
        ]
        if line_items[0].startswith('DE') and codec_type(line_items[0])
    }
    ffmpeg_codecs_by_type = {
        _type: [
            _codec
            for _codec, _codec_type in ffmpeg_codecs.items()
            if _codec_type==_type
        ]
        for _type in set(ffmpeg_codecs.values())
    }
    return ffmpeg_codecs_by_type


def ffmpeg_try_encoding( file: Path, codec: str, codec_type: str, _format: str, allow_experimental: bool = False, stream_idx: int = 0 ) -> bool:
    ''' Tries to launch conversion with FFMPEG targeting a specific format and codec.
    Returns whether or not FFMPEG can produce the file.

    Note: for performance reasons, only encodes first 10 seconds on audio/video codecs
    '''
    out_file = file.with_suffix(f".{codec_type}.{codec}.{_format}")
    if out_file.is_file():
        out_file.unlink()

    # Unfortunately, some encoders are picky about the formats they accept, so they need extra steps
    additional_parameters = {
        'avui':    ['-vf', 'scale=720:576'],
        'dnxhd':   ['-vf', 'scale=1280:720,fps=30000/1001,format=yuv422p', '-b:v', '110M'],
        'dvvideo': ['-vf', 'scale=720:576,fps=25/1'],
        'h261':    ['-vf', 'scale=352:288'],
        'h263':    ['-vf', 'scale=352:288'],
        'adpcm_g726': ['-ac','1','-ar','8000'],
        'adpcm_g726le': ['-ac','1','-ar','8000'],
        'adpcm_swf': ['-ar','44100'],
        'amr_nb': ['-ac','1','-ar','8000'],
        'amr_wb': ['-ac','1','-ar','16000'],
        'comfortnoise': ['-ac','1'],
        'g723_1': ['-ac','1','-ar','8000'],
        'gsm': ['-ar','8000'],
        'gsm_ms': ['-ar','8000'],
        'nellymoser': ['-ac','1','-ar','22050'],
        'roq_dpcm': ['-ar','22050'],
    }

    cmd = FFMPEG_CALL + \
        [ '-i', file ] + \
        (['-strict','-2'] if allow_experimental else []) + \
        additional_parameters.get(codec,[]) + \
        [
            '-map', f'0:{codec_type[0]}:{stream_idx}',
            '-c', FFMPEG_PATCH_ENCODER.get(codec,codec),
            out_file
        ]
    stdX = execute(cmd)
    encoding_works = out_file.is_file() and out_file.stat().st_size > 1_000
    out_file.unlink()
    if not encoding_works:
        if 'Subtitle encoding currently only possible from text to text or bitmap to bitmap' in stdX['stderr']:
            return ffmpeg_try_encoding( file, codec, codec_type, _format, stream_idx=1 )
        if "add '-strict -2'" in stdX['stderr']:
            return ffmpeg_try_encoding( file, codec, codec_type, _format, allow_experimental=True )
        if not any(x in stdX['stderr'] for x in ['is not supported by this format','codec not currently supported in container','No wav codec tag found for codec']):
            print(cmd)
            print(f">{codec}: stderr: {stdX['stderr']}", end='')
    return encoding_works


def get_args() -> argparse.Namespace:
    ''' Get command-line arguments '''
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'test_file',
        action='store',
        help='Test file with at least one video, audio and subtitle stream.'
    )
    return parser.parse_args()


def main() -> None:
    ''' main '''
    args = get_args()
    test_file = Path(args.test_file)

    assert test_file.is_file()

    ffmpeg_codecs_by_type = get_ffmpeg_codecs()
    _format = input("Test format: ")
    c_type = None
    while c_type not in list(ffmpeg_codecs_by_type)+['all']:
        c_type = input("Codec type [video,audio,subtitle,all]: ")

    compatible_codecs = { codec_type:list() for codec_type in ffmpeg_codecs_by_type }
    for codec_type, _codecs in ffmpeg_codecs_by_type.items():
        if codec_type!=c_type and c_type!='all':
            continue
        print(f"FFMPEG {codec_type} codecs:")
        for _codec in _codecs:
            codec_is_compatible = ffmpeg_try_encoding(
                file=test_file,
                codec=_codec,
                codec_type=codec_type,
                _format=_format
            )
            print(f">{_codec}: {codec_is_compatible}")
            if codec_is_compatible:
                compatible_codecs[codec_type].append(_codec)

    res_file = SCRIPT_PATH / f'compatibility_report_{_format}.{c_type}.json'
    res_file.write_text(
        json.dumps(
            compatible_codecs,
            indent=2
        ),
        encoding='utf8',
        errors='ignore'
    )
    print(f"Results saved to {res_file}")


if __name__=='__main__':
    main()
    print("END OF PROGRAM")
