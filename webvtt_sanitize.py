""" This is a proof of concept of a tool that 'sanitizes' the content of
a WEBVTT subtitle file, or more accurately said it converts it to a version
optimized for converting to MOV_TEXT.

Why: Project PlexOptimizer makes use of WebVtt format as a intermediary
when converting text-based subtitle formats to MOV_TEXT. There are two issues:
- While modern text-based subtitle formats like WebVtt, ASS and SRT can handle
  concurrent subtitles, MOV_TEXT can't, and will drop subtitles.
- WebVtt subtitle text containing litteral line breaks between paragraphs
  will cause the conversion to MOV_TEXT to silently fail

How: By re-ordering subtitles, fusing them so the timeline doesn't contain
concurrent subtitles and escaping litteral line breaks between paragraphs,
this script attempts to mitigate the issues with WebVtt -> MOV_TEXT conversion.

Warning:
- While not lossy, this conversion is intended to be one-way:
    (native WebVtt) -> (WebVtt optimized for converting to MOV_TEXT)
  The author has no plan to implement the reverse conversion.
- The converted

"""

from pathlib import Path
from typing import List
import re
import json
import argparse


TIMECODE_PATTERN = re.compile(r"(\d{2}:\d{2}\.\d{3}) \-\-> (\d{2}:\d{2}\.\d{3})")


def get_args() -> argparse.Namespace:
    ''' Parses CLI arguments, enforces required arguments
    '''
    parser = argparse.ArgumentParser()
    parser.add_argument('-i',action='store',required=True, help="Input vtt file.")
    parser.add_argument('-o',action='store',required=True, help="Output vtt file.")
    return parser.parse_args()


def ms_to_timecode(ms: int) -> str:
    ''' Conversion <timecode_ms:int> -> <timecode_txt:str>
    '''
    _s = ms // 1000
    return f"{_s//60:02d}:{_s%60:02d}.{ms%1000:03d}"


def timecode_to_ms(timecode: str) -> int:
    ''' Conversion <timecode_txt:str> -> <timecode_ms:int>
    '''
    components = [
        int(x)
        for x in re.split(r"[\.:]+", timecode)
    ]
    assert len(components)==3
    return components[0] * 60_000 + components[1] * 1000 + components[2]


class SubtitleUnit:
    ''' Represents a unique subtitle, with its text and timecodes
    '''
    def __init__(self, timecode: str, text: List[str]):
        ''' init with timecode conversion
        '''
        begin, end = re.split(r" \-\-> ", timecode)
        begin_ms, end_ms = timecode_to_ms(begin), timecode_to_ms(end)
        assert begin_ms < end_ms
        self.a, self.b = begin_ms, end_ms
        self.txt = text

    def __lt__(self, other: 'SubtitleUnit') -> bool:
        ''' Implements operator '<' for sorting
        '''
        if self.a == other.a:
            return self.b > other.b
        return self.a < other.a

    def __eq__(self, other: 'SubtitleUnit') -> bool:
        ''' Implements operator '==' for sorting
        '''
        return self.a == other.a and self.b == other.b


    def collision(self, other: 'SubtitleUnit') -> bool:
        ''' Returns True if two subtitles are concurrent
        '''
        return self.h_collision(other_a=other.a, other_b=other.b)


    def h_collision(self, other_a: int, other_b: int) -> bool:
        ''' Returns True if two subtitles are concurrent
        '''
        if self.a <= other_a:
            return 0 < self.b - other_a
        return 0 < other_b - self.a


    @property
    def timecode(self) -> str:
        ''' Webvtt-compliant timecode
        '''
        return f"{ms_to_timecode(self.a)} --> {ms_to_timecode(self.b)}"


    @classmethod
    def subtitles_to_str(cls, subtitles: List['SubtitleUnit']) -> str:
        ''' Debug: print a list of subtitles
        '''
        return ', '.join(json.dumps(s.__dict__) for s in subtitles)


    @classmethod
    def fuse_subtitles(cls, subtitles):
        ''' Merge N subtitles into M non-concurrent sutitles
        '''
        ts = list(sorted(set(s.a for s in subtitles).union(set(s.b for s in subtitles))))
        subs = []
        for a,b in zip(ts, ts[1:]):
            displayed_subs = [s for s in subtitles if s.h_collision(a,b)]
            assert displayed_subs, f"No displayable subtitle in [{a},{b}] for {SubtitleUnit.subtitles_to_str(subtitles)}"
            text = []
            for idx, s in enumerate(reversed(displayed_subs)):
                if idx!=0:
                    text.append("<br/><br/>")
                text.extend(s.txt)
            subs.append(
                SubtitleUnit(
                    f"{ms_to_timecode(a)} --> {ms_to_timecode(b)}",
                    text
                )
            )
        return subs


class SubtitleStream:
    ''' Represent a whole subtitle stream, like one contained in a .vtt file
    '''

    def __init__(self, subtitles: List[SubtitleUnit]):
        ''' init with timeline restructuring
        '''
        self.subtitles = self.straighten_timeline(subtitles)


    def straighten_timeline(self, subtitles: List[SubtitleUnit]):
        ''' Corrects for incorrectly sorted or concurrent subtitles
        '''
        _subtitles = list(sorted(subtitles))
        nb_subs = len(_subtitles)
        subtitles_ok = []
        i = 0
        while i < nb_subs:
            if not _subtitles[i].collision(_subtitles[i+1]):
                subtitles_ok.append(_subtitles[i])
                i += 1
                continue

            # collision
            collided_subs = [ _subtitles[i], _subtitles[i+1] ]
            j = i+2
            while j < nb_subs and any(_subtitles[k].collision(_subtitles[j]) for k in range(i,j)):
                collided_subs.append( _subtitles[j] )
                j += 1
            fused_subs = SubtitleUnit.fuse_subtitles(collided_subs)
            print(f"Fusing subtitles: {SubtitleUnit.subtitles_to_str(collided_subs)}\n into: {SubtitleUnit.subtitles_to_str(fused_subs)}")
            subtitles_ok.extend(fused_subs)
            i = j

        return subtitles_ok


    @classmethod
    def from_vtt(cls, f: Path) -> 'SubtitleStream':
        ''' Read SubtitleStream from a .vtt file
        '''
        subtitles = []
        lines = f.read_text(encoding='utf8').splitlines()

        # Webvtt files begin with "WEBVTT\n"
        assert lines[0]=='WEBVTT'

        # subtitles begin at line index 2
        # each line can be: timecode, blank or subtitle text
        s_timecode, s_text, sep = None, [], 0

        def null_generator( it ):
            for x in it:
                yield x
            while True:
                yield None

        for line in null_generator(lines[2:]):

            # case: end of file => append current subtitle and return
            if line is None:
                if s_timecode is not None:
                    subtitles.append(SubtitleUnit(s_timecode, s_text))
                break

            # case: new timecode => first or new subtitle
            if re.match(TIMECODE_PATTERN, line):
                if s_timecode is not None:
                    subtitles.append(SubtitleUnit(s_timecode, s_text))
                s_timecode = line
                s_text = []
                sep = 0
                continue

            # case: empty line => separator or "\n" in subtitle text
            if line == '':
                sep += 1
                continue

            # case: other content => subtitle text
            for _ in range(sep):
                print(f"Litteral line break found in subtitle text after '{s_text}'")
                s_text.append('<br/>')
                sep = 0
            s_text.append(line.strip())

        return SubtitleStream(subtitles)


    def to_json(self) -> str:
        ''' Debug: output as json string
        '''
        obj = [
            s.__dict__
            for s in self.subtitles
        ]
        return json.dumps(obj, indent=2)


    def to_webvtt(self) -> str:
        ''' Output as WebVtt-compliant text
        '''
        def gen():
            yield "WEBVTT"
            yield ""
            for s in self.subtitles:
                yield s.timecode
                for t in s.txt:
                    yield t
                yield ""

        return '\n'.join(gen())


if __name__=='__main__':
    args = get_args()
    vtt_file = Path(args.i)
    assert vtt_file.is_file()
    ss = SubtitleStream.from_vtt(vtt_file)
    Path(args.o).write_text(ss.to_webvtt(), encoding='utf-8')
