#pylint: disable=too-many-arguments, global-statement
''' This module implements CodecConstraintConverter and associated tools. This is aimed at
automating conversion of video files with FFMPEG, with flexible rules.

Interface:
- ``CodecConstraintConverter``: Used to plan file conversion and craft encoding script using
  constraint/conversion rules.
- ``CodecRule``: Used to implement codec-based decision rule passed to CodecConstraintConverter
  (see argument `format_rules`)
- ``FFMPEGConvertStream``, ``FFMPEGExtractStream``, ``ExternalCommand``, ``DropStream``: Represent
  the different stackable stream actions accepted by CodecConstraintConverter's planning engine.

Note: The accompanying file ``format_compatibility.json`` is required, with entries
  <format:str>:<supported_codecs:List[str]>. See project FFMPEGContainerTester.

For a usage example, see project Plex Optimizer.

Refer to ``CodecConstraintConverter``'s documentation for details on parameters.
'''

import enum
import json
from collections import namedtuple
from typing import Callable, List, Union, Dict, Tuple
from pathlib import Path

from utils import find_available_path, execute, dump_json, patch_string
from os_detect import Os

TODO = '''
- Investigate menu duplication
'''

Command = List[Union[str,Path]]
CodecRule = namedtuple(typename='CodecRule', field_names=['passthrough','convert'])
FORMAT_COMPATIBILITY = {} # To be initialized at runtime
DUMP_FFPROBE = False
DEBUG_REMUX = False


class StreamAction(enum.Enum):
    ''' Represents the possible actions when converting a stream '''
    Convert  = 1
    Copy     = 2
    Extract  = 3
    External = 4
    Drop     = 5


def FFMPEGConvertStream( codec: str, parameters: List = None, output_format: str = None, repr_complement: str = None ) -> dict:
    ''' Returns a partial stream-specific conversion command, with custom parameters.
    Use for both convert and copy of streams.

    `output_format`: Not used for streams whose plan is a single FFMPEGConvertStream

    Convention: `in_file_idx`, `in_stream`, `out_stream` are FFMPEG-related indexes
        and `in_file`, `out_file` are Path representing input/output file
    '''
    if parameters is None:
        parameters = []
    return {
        'action': StreamAction.Copy if codec=='copy' else StreamAction.Convert,
        'ffmpeg_stream_parameters': [
            '-map', '{in_file_idx}:{in_stream}',
            '-c:{out_stream}', codec
        ] + parameters,
        'codec': codec,
        'repr': codec if repr_complement is None else codec+repr_complement,
        'output_format': output_format
    }


def FFMPEGExtractStream( codec: str = 'copy', output_format: str = 'mkv', parameters: list = None ) -> dict:
    ''' Returns a partial stream-specific stream extraction.
    Use when extracting stream, with or without conversion.

    Convention: `in_file_idx`, `in_stream`, `out_stream` are FFMPEG-related indexes
        and `in_file`, `out_file` are Path representing input/output file
    '''
    if parameters is None:
        parameters = []
    return {
        'action': StreamAction.Extract,
        'ffmpeg_stream_parameters': [
            '-map', '{in_file_idx}:{in_stream}',
            '-c', codec
        ] + parameters,
        'codec': codec,
        'output_format': output_format,
        'repr': codec + ' (extract)'
    }


def ExternalCommand( command: Command, output_codec: str, output_format: str, custom_output_file: Callable = None ) -> dict:
    ''' Represents an arbitrary command called upon the file containing the stream.
    Recommended to use on extracted streams.

    Convention: `in_file_idx`, `in_stream`, `out_stream` are FFMPEG-related indexes
        and `in_file`, `out_file` are Path representing input/output file
    '''
    return {
        'action': StreamAction.External,
        'external_command': command,
        'codec': output_codec,
        'output_format': output_format,
        'repr': output_codec + ' (external)',
        'custom_output_file': custom_output_file
    }


def DropStream() -> Callable:
    ''' Simply drop the stream
    '''
    return {
        'action': StreamAction.Drop
    }


class CodecConstraintConverter:

    ''' This object's purpose is to allow for automated
    rule-based video file conversion.
    '''

    CODEC_TYPES = { 'video', 'audio', 'subtitle', 'attachment' }
    FFMPEG_CALL = [
            'ffmpeg',
            '-loglevel', 'warning',
            '-stats',
            '-probesize', '100G',
            '-analyzeduration', '100G'
        ]

    def __init__(
        self,
        ffmpeg_parameters: List[str],
        format_rules: dict,
        conversion_rules: dict,
        keep_original_streams_rules: dict,
        drop_unknown_streams: bool = True,
        bitrate_limit: Union[int,float] = float('inf')
    ) -> None:
        ''' Requires following parameters:

        `ffmpeg_parameters`: parameters for ffmpeg (eg: ["-loglevel", "warning", "-stats"])

        `format_rules`: An access to format_rules[<format:str>][<codec_type:str>] must yield a CodecRule representing expected
            codecs and whether conversion is warranted. Eg:
            format_rules['mp4']['video'] = CodecRule( passthrough={'h264'}, convert={'mjpeg','mpeg4','mpeg2video','hevc','av1'} )

        `conversion_rules`: A call to encode_rules[<codec_type:str>] should yield a Callable object with signature:
                <stream_info:dict>, <ouput_container:str> -> <steps:List[dict]>
            Each step being a dict produced by either FFMPEGConvertStream, FFMPEGExtractStream or ExternalCommand

        `drop_unknown_streams`: Whether to drop streams not covered by `format_rules`. May raise warnings on format
            incompatibility.

        `keep_original_streams_rules`: Whether to drop stream that required transcoding. Recommended: True

        `bitrate_limit`: Overrides format_rules for any stream with higher bitrate, forcing them to be converted.
        '''
        self.ffmpeg_parameters = ffmpeg_parameters
        self.format_rules = format_rules
        self.conversion_rules = conversion_rules
        self.drop_unknown_streams = drop_unknown_streams
        self.keep_original_streams_rules = {} if keep_original_streams_rules is None else keep_original_streams_rules
        self.bitrate_limit = bitrate_limit
        self.OS = Os()

        global FORMAT_COMPATIBILITY
        format_compatibility_f = Path(__file__).parent / 'format_compatibility.json'
        assert format_compatibility_f.is_file(), "ERROR: Could not load `format_compatibility.json`"
        FORMAT_COMPATIBILITY = json.loads(format_compatibility_f.read_text())


    def produce_cmd_script( self, script: Path, commands: List[Command] ) -> None:
        ''' writes a BAT file with commands
        '''

        def patch_macro( c: Command ) -> Command:
            if len(c)==1 and isinstance(c[0], str):
                # May be a macro
                if c[0].startswith("[ASSERT_EXIST]"):
                    _file = c[0].replace("[ASSERT_EXIST]",'')
                    return [
                        f'IF NOT EXIST "{_file}" ( ECHO Error: Missing file "{_file} !" ) ELSE ( ECHO File confirmed to exist )'
                    ]
                if c[0].startswith("[MKDIR]"):
                    return [c[0].replace("[MKDIR]",'MD')]
                if c[0].startswith("[RMDIR]"):
                    return [c[0].replace("[RMDIR]",'RD /S /Q')]
            return c

        script.write_text(
            'chcp 65001\n@echo off\n\n' +
            '\n\n'.join(
                self.command_to_str(patch_macro(_cmd))
                for _cmd in commands
            ),
            encoding='utf8',
            errors='ignore'
        )


    def produce_bash_script( self, script: Path, commands: List[Command] ) -> None:
        ''' writes a SH file with commands
        '''

        def patch_macro( c: Command ) -> Command:
            if len(c)==1 and isinstance(c[0], str):
                # May be a macro
                if c[0].startswith("[ASSERT_EXIST]"):
                    _file = c[0].replace("[ASSERT_EXIST]",'')
                    return [
                        f'if [ test -f "{_file}"]; then echo "Error: Missing file "{_file} !" else echo "File confirmed to exist" fi'
                    ]
                if c[0].startswith("[MKDIR]"):
                    return [c[0].replace("[MKDIR]",'mkdir')]
                if c[0].startswith("[RMDIR]"):
                    return [c[0].replace("[RMDIR]",'rm -rf')]
            return c

        script.write_text(
            '#!/bin/bash\n\n' +
            '\n\n'.join(
                self.command_to_str(patch_macro(_cmd))
                for _cmd in commands
            ),
            encoding='utf8',
            errors='ignore'
        )


    def __get_streams_info( self, file: Path ) -> Dict[int,dict]:
        ''' Use ffprobe to get stream information
        '''
        # Run ffprobe
        cmd = [
            'ffprobe',
            '-loglevel', 'error', # disable most messages
            '-show_entries', 'stream', # output all streams
            '-of', 'json', # output format as json
            file
        ]
        stdX = execute( cmd )

        # Handle and decode output
        if stdX['stderr'] != '':
            print(f"Something went wrong: ffprobe stderr is: '{stdX['stderr']}' (type:{type(stdX['stderr'])})")
            return None

        file_info = json.loads(stdX['stdout'])
        assert "streams" in file_info, "No 'streams' in info"

        if DUMP_FFPROBE:
            dump_json(file_info, file.with_suffix('.ffprobe.json'))

        # package information
        return {
            int(s['index']):s
            for s in file_info['streams']
            if s['codec_type'] in self.CODEC_TYPES
        }


    def stream_conversion( self, stream_info: dict, _format: str ) -> dict:
        ''' Plans optimization for a particular stream given a target format
        '''
        #idx = stream_info['index']
        codec_type, codec_name = stream_info.get("codec_type"), stream_info.get("codec_name")
        _codec_rule = self.format_rules[_format][codec_type]
        __bitrates = [ y for y in [ stream_info.get('tags',{}).get(x) for x in ('BPS','BPS-eng') ] if y is not None ]
        _bitrate = int( __bitrates.pop() ) if __bitrates else 0
        if _bitrate==0 and codec_type!='attachment':
            print("Warning: Could not retrieve bitrate")

        if codec_name in _codec_rule.passthrough:
            # Passthrough => copy if bitrate isn't too high, otherwise convert
            if _bitrate > self.bitrate_limit:
                print(f"Warning: Forcing transcoding of stream {stream_info.get('index')}. Cause: bitrate too high ({_bitrate} > {self.bitrate_limit})")
                return self.conversion_rules[codec_type](stream_info=stream_info,format=_format)
            return [{'action': StreamAction.Copy}]
        if codec_name not in _codec_rule.convert:
            # Unlisted codec => drop or copy
            if self.drop_unknown_streams:
                return [DropStream()]
            if not codec_name in FORMAT_COMPATIBILITY[_format]:
                print(f"Warning: Forced to drop stream {stream_info['index']} of " \
                    + f"unhandled codec {codec_name}. Cause: incompatible with format {_format}.")
                print("You may want to add this codec to the explicity handled codec list.")
                return [DropStream()]
            return [{'action': StreamAction.Copy}]

        # Current stream needs to be converted => construct optimization plan
        return self.conversion_rules[codec_type](stream_info=stream_info,format=_format)


    def ffmpeg_craft_command( self, in_file: Path, out_file: Path, conversion_plan: dict ) -> Command:
        ''' Craft a ffmpeg command for simple multi-stream conversion from `in_file` to `out_file`
        '''
        cmd = self.FFMPEG_CALL + [ '-i', in_file ]
        out_idx = 0
        for stream_idx, stream_plan in conversion_plan.items():
            patch = {'{in_file_idx}': '0', '{in_stream}': str(stream_idx), '{out_stream}': str(out_idx)}
            cmd += [
                patch_string(s, patch)
                for s in stream_plan[0].get('ffmpeg_stream_parameters',[])
            ]
            out_idx += 1

        cmd.append( out_file )
        return cmd


    def craft_complex_command( self, in_file: Path, in_stream: int, tmp_dir: Path, conversion_plan: dict ) -> Tuple[List[Command],Path]:
        ''' Crafts commands for stream, returns them plus the output file path
        '''
        cmds = []
        _in_file, _in_stream = in_file, in_stream
        for step in conversion_plan:

            # Specify output file from output format
            assert step['output_format'] is not None, f"Step has no output format: {step}"
            _out_fmt = step['output_format']
            if _out_fmt=='[NULL]':
                out_file = 'NUL' if self.OS.windows else '/dev/null'
            else:
                out_file = find_available_path(
                    root=tmp_dir,
                    base_name=f"{_in_file.name}_{_in_stream}.{step['codec']}.{step['output_format']}",
                    file=True
                )

            # Craft command for step
            patch = {'{in_file}': _in_file, '{in_file_idx}': '0', '{in_stream}': str(_in_stream), '{out_stream}': '0', '{out_file}': out_file}
            _action = step['action']

            if _action in { StreamAction.Convert, StreamAction.Extract }:
                _cmd = self.FFMPEG_CALL \
                    + (['-y'] if _out_fmt=='[NULL]' else []) \
                    + [ '-i', _in_file ] + [
                    patch_string(s, patch)
                    for s in step['ffmpeg_stream_parameters']
                ] + [ out_file ]
            elif _action==StreamAction.External:
                if 'custom_output_file' in step and step['custom_output_file'] is not None:
                    out_file = step['custom_output_file'](_in_file)
                _cmd = [
                    patch_string(s, patch)
                    for s in step['external_command']
                ]
            else:
                raise ValueError(f"Unexpected action: {_action}")

            cmds.append(_cmd)
            if _out_fmt!='[NULL]':
                _in_file = out_file
            _in_stream = 0

        return cmds, _in_file


    def command_to_str( self, cmd: Command ) -> str:
        ''' Converts Command to string to export to script
        '''
        #print(f"command_to_str={cmd} ({type(cmd)})")
        return ' '.join(
            c if isinstance(c, str) else f'"{c}"'
            for c in cmd
        ) if not isinstance(cmd, str) else cmd


    def remux( self, source_file: Path, copy_streams: set, stream_files: dict, streams_info: dict, output_file: Path, optimized_streams: set ) -> Command:
        ''' Crafts remux command from N input stream in M individual files (`stream_files`;N>=M) to a single output file.

        `copy_streams`: set containing `stream_idx` for streams that are to be copied from source

        `stream_files`: contains N entries:
            <stream_idx:int>:{'file':<input_file:Path>,'idx':<stream_index_in_file:int>}
            where `stream_idx` is the stream index at the original file and
            `stream_index_in_file` is the corresponding stream index at `input_file`

        `streams_info`: contains entries:
            <stream_idx:int>:<stream_info:dict>

        `optimized_streams`: set containing `stream_idx` for streams that are converted
        '''
        if DEBUG_REMUX:
            print(f"stream_files:{stream_files}")
        cmd = self.FFMPEG_CALL.copy() + [ '-i', source_file ]
        # Index stream temporary files
        _files = list(set(x['file'] for x in stream_files.values()))
        _file_index_by_stream = {
            stream_idx: _files.index(stream_files[stream_idx]['file'])+1
            for stream_idx in stream_files
        }
        # Add input files
        for f in _files:
            cmd += [ '-i', f ]

        out_stream_idx = 0
        nb_streams = max(streams_info.keys())+1
        for stream_idx in range(nb_streams):
            _stream_info = streams_info[stream_idx]
            _lang = _stream_info.get('tags',{}).get('language', None)
            _title = _stream_info.get('tags',{}).get('title', '')
            _included_stream = False

            # Attempt to save disposition information (TODO: evaluate effectiveness)
            disposition =  '+'.join(
                d for d in ['default','forced']
                if _stream_info.get('disposition',{}).get(d, 0)==1
            )
            if not disposition:
                disposition = '0'

            if stream_idx in optimized_streams:
                _file_index = _file_index_by_stream[stream_idx]
                _file_stream_idx = stream_files[stream_idx]['idx']
                _cmd = [
                    '-map', f"{_file_index}:{_file_stream_idx}",
                    f'-c:{out_stream_idx}', 'copy'
                ]

                if _stream_info['codec_type']!='attachment':
                    metadata = lambda _name, _val: [ f'-metadata:s:{out_stream_idx}', f'{_name}="{_val}"' ]
                    # Add language tag
                    if _lang:
                        _cmd += metadata('language', _lang)

                    # Add title tag
                    new_title = (f'[COMPAT] {_title}' if _title else '[COMPAT]') if stream_idx in optimized_streams else _title
                    _cmd += metadata('title', new_title)

                    # If possible, copy stream 'disposition': 'default' and 'forced' metadata
                    # Note: MP4 container picks first stream of each type as default
                    _cmd += [ f'-disposition:s:{out_stream_idx}', disposition ]
                if DEBUG_REMUX:
                    print(f"Adding optimized stream {stream_idx} with cmd: '{_cmd}'")
                cmd += _cmd
                out_stream_idx += 1
                _included_stream = True

            if stream_idx in copy_streams or _included_stream is False or self.keep_original_streams_rules[_stream_info['codec_type']]:
                metadata = lambda _name, _val: [ f'-metadata:s:{out_stream_idx}', f'{_name}="{_val}"' ]
                _cmd = [
                    '-map', f"0:{stream_idx}",
                    f'-c:{out_stream_idx}', 'copy'
                ]
                if _stream_info['codec_type']!='attachment':
                    _cmd += metadata('title', _stream_info.get('tags',{}).get('title', '')) \
                            + (metadata('language', _lang) if _lang else []) \
                            + [ f'-disposition:s:{out_stream_idx}', disposition ]
                if DEBUG_REMUX:
                    print(("Keeping a copy of" if _included_stream else "Copying original") + f" stream {stream_idx} with cmd: '{_cmd}'")
                cmd += _cmd
                out_stream_idx += 1

        cmd.append(output_file)
        return cmd



    def plan_conversion( self, file: Path, output_format: str, output_file: Path ) -> List[Command]:
        ''' Plan the conversion of `file`

        `output_format`: container-specific file extension, must match an
            entry in `format_rules`.
        '''

        assert output_format in self.format_rules
        all_commands = []

        # Prepare temporary directory for intermediary files
        tmp_dir = find_available_path(
            root=file.parent,
            base_name=file.stem,
            file=False
        )
        all_commands.append( [f'[MKDIR] "{tmp_dir}"'] )

        # Get infos for each stream
        streams_info = self.__get_streams_info(file)
        if streams_info is None:
            return

        def is_format_compatible( info: dict, plan: list ) -> bool:
            ''' Prints per-stream plan to output '''
            nonlocal output_format

            # keep orginal stream => its codec must be supported
            if self.keep_original_streams_rules[info['codec_type']]:
                if info['codec_name'] not in FORMAT_COMPATIBILITY[output_format]:
                    print(f"Aborting conversion: (Can't keep original stream) Codec {info['codec_name']} not compatible with format {output_format}")
                    return False

            # target stream codec must be supported
            _plan_codecs = [step['codec'] for step in plan if 'codec' in step and step['codec']!='copy']
            if _plan_codecs:
                if _plan_codecs[-1] not in FORMAT_COMPATIBILITY[output_format]:
                    print(f"Aborting conversion: Codec {_plan_codecs[-1]} not compatible with format {output_format}")
                    return False

            return True

        def display_plan_steps( idx: int, info: dict, plan: list ) -> None:
            ''' Prints per-stream plan to output '''
            if any(step['action']==StreamAction.Drop for step in plan):  # Dropped stream
                print(f"Dropping stream {idx} ({info['codec_name']} {info['codec_type']})")
                return
            stream_lang = info.get('tags',{}).get('language',None)
            _lang =  f' (lang:{stream_lang})' if stream_lang else ''
            #_codecs = [info['codec_name']] + [step['codec'] for step in plan if 'codec' in step and step['codec']!='copy']
            if all(step['action'] is StreamAction.Copy for step in plan):  # Copied stream
                return
            codecs = [info['codec_name']] + [step['repr'] for step in plan if 'repr' in step]
            print(f"Optimizing stream {idx}{_lang}: " + ' -> '.join( codecs ) )


        # Get plans for individual streams
        simple_conversion, other_conversion, optimized_streams, copy_streams = {}, {}, set(), set()
        for stream_idx, stream_info in streams_info.items():
            stream_plan = self.stream_conversion(stream_info, output_format)
            if not is_format_compatible(stream_info, stream_plan):
                return
            display_plan_steps( stream_idx, stream_info, stream_plan )
            if len(stream_plan)==0:
                raise ValueError(f"No plan for stream {stream_idx}")
            if len(stream_plan)==1:
                if stream_plan[0]['action'] == StreamAction.Copy and stream_info['codec_name'] in FORMAT_COMPATIBILITY[file.suffix[1:]]:
                    copy_streams.add(stream_idx)
                    continue
                if stream_plan[0]['action'] == StreamAction.Convert and stream_plan[0]['codec'] in FORMAT_COMPATIBILITY[file.suffix[1:]]:
                    simple_conversion[stream_idx] = stream_plan
                    optimized_streams.add(stream_idx)
                    continue
                if stream_plan[0]['action'] == StreamAction.Drop:
                    continue
            other_conversion[stream_idx] = stream_plan
            optimized_streams.add(stream_idx)

        # Steps for streams with simple conversion or copy
        if simple_conversion:
            simple_conversion_file = tmp_dir / f'simple_conversion{file.suffix}'
            simple_conversion_cmd = self.ffmpeg_craft_command(
                in_file=file,
                out_file=simple_conversion_file,
                conversion_plan=simple_conversion
            )
            all_commands.append( simple_conversion_cmd )

        # Steps for other streams
        tmp_files = {
            in_idx: { 'file': simple_conversion_file, 'idx': out_idx }
            for out_idx,in_idx in enumerate([
                _idx
                for _idx in simple_conversion
                if _idx in optimized_streams
            ])
        }
        for stream_idx, stream_plan in other_conversion.items():
            commands, out_file = self.craft_complex_command(
                in_file=file,
                in_stream=stream_idx,
                tmp_dir=tmp_dir,
                conversion_plan=stream_plan
            )
            all_commands += commands
            tmp_files[stream_idx] = { 'file': out_file, 'idx': 0 }

        # Check for individual steps completion
        all_commands += [
            [ f"[ASSERT_EXIST]{_out_file}" ]
            for _out_file in {
                x['file']
                for x in tmp_files.values()
            }
        ]

        # Remux step
        remux_cmd = self.remux(
            source_file=file,
            copy_streams=copy_streams,
            stream_files=tmp_files,
            streams_info=streams_info,
            output_file=output_file,
            optimized_streams=optimized_streams
        )
        all_commands.append( remux_cmd )

        # Cleanup
        all_commands.append( [f'[RMDIR] "{tmp_dir}"'] )

        return all_commands
