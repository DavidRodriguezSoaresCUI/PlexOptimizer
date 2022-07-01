#pylint: disable=eval-used
''' Utilities functions
'''
import collections
import sys
import re
import json
from typing import Iterable, Union, Any, Callable, Dict, List
from pathlib import Path
from subprocess import Popen, PIPE

KBI_msg = "A KEYBOARDINTERRUPT WAS RAISED. THE PROGRAM WILL EXIT NOW."
MAKE_FS_SAFE_PATTERN = re.compile( pattern=r'[\\/*?:"<>|]' )

#################### Execute external programs ####################

def execute( command: Union[str,Iterable[str]], shell: bool = False ) -> Dict[str,str]:
    ''' Passes command to subprocess.Popen, retrieves stdout/stderr and performs
    error management.
    Returns a dictionnary containing stdX.
    Upon command failure, prints exception and returns empty dict. '''

    try:
        with Popen( command, stdout=PIPE, stderr=PIPE, shell=shell ) as process:
            # wait and retrieve stdout/err
            _stdout, _stderr = process.communicate()
            # handle text encoding issues and return stdX
            return {
                'stdout': _stdout.decode('utf8', errors='backslashreplace'),
                'stderr': _stderr.decode('utf8', errors='backslashreplace')
            }
    except Exception as e:
        print(f"execute: Error while executing command '{command}' : {e}")
        raise

#################### CLI interactions ####################

def __input_KBI( message: str, exit_on_KBI: bool = True ) -> str:
    ''' Handles `KeyboardInterrupts` on `input` calls, used by other more complex functions.
    `exit_on_KBI`: If True, user can exit the program. If False, handling
    of KeyboardInterrupt is delegated to calling code.
    '''
    if exit_on_KBI:
        try:
            return input( message )
        except KeyboardInterrupt:
            print( KBI_msg )
            end_of_program()
    return input( message )


def pause() -> None:
    ''' Implements a 'pause' feature. Press ENTER to continue. If 'Ctrl+C' is pressed,
    it exits the program '''

    __input_KBI( "Press the <ENTER> key to continue...", exit_on_KBI=False )


def end_of_program( exit_code: int = 0, halt: bool = False ) -> None:
    ''' Standardized way of ending programs '''
    print("\nEND OF PROGRAM\n")
    if halt:
        pause()
    sys.exit(exit_code)


def user_input( prompt: str, accepted: Union[Iterable[Union[str,int]],Callable], default: Any = None ) -> str:
    ''' Asks user for input, with restrictions on acceptable values.
    `prompt`: appropriate text asking the user for input. Should be straightforward and informative about the kind of data that is asked
    `accepted`: either a function testing if the user input is acceptable, or an iterable containing all acceptable values
    `default`: When given, if the user input is not acceptes, default is returned. When abscent, the user will be prompted again until either
    an accepted value is entered or a KeyboardInterrupt is raised.
    Note: this is only designed to retrieve values of the following types: str, int, float
    '''

    # Smart prompt reformat
    if default is not None:
        prompt += f" [default:{default}] "
    if prompt[-1] == ':':
        prompt += ' '
    elif prompt[-2:]!=': ':
        prompt += ': '

    acceptable_UI = lambda ui: accepted(ui) if callable(accepted) else (ui in accepted)

    while True:
        # main loop: ask user until an acceptable input is received, or a KeyboradInterrupt ends the program
        _user_input = __input_KBI( prompt )

        # case: raw user input is accepted
        if acceptable_UI( _user_input ):
            return _user_input

        # case: processed user input is accepted
        variations = [ 'int(_user_input)', 'float(_user_input)', '_user_input.lower()' ]
        for variation in variations:
            try:
                __user_input = eval( variation )
                if acceptable_UI( __user_input ):
                    return __user_input
            except (ValueError, AttributeError):
                pass

        # case: user input is not accepted AND there is a default
        if default is not None:
            return default

        # case: user input is not accepted AND there is no default => notify user, ask again
        print("Input '%s' is not a valid input. %s", _user_input, (f"Please choose one of : {accepted}" if not callable(accepted) else "") )


def choose_from_list( choices: list, default: int ) -> Any:
    ''' Prints then asks the user to choose an item from a list
    `default`
    '''
    # Print choices
    print( "Choices:\n  " + '\n  '.join([
        f"[{idx}] {choice}"
        for idx, choice in enumerate(choices)
    ]) + '\n' )

    # Get user selection
    idx = user_input(
        "Selection",
        accepted=list(range(len(choices))),
        default=default
    )

    # Return choice
    return choices[idx]


def cli_explorer( root_dir: Path, allow_mkdir: bool = True, windows_behavior: bool = True ) -> Path:
    ''' Allows for the user to explore directories to select one.
    Note: windows-specific behavior
    '''
    assert root_dir and root_dir.is_dir()
    _root_dir = root_dir.resolve()
    cwd = _root_dir
    NEW_FOLDER_TEXT = '<Make new folder here>'

    while True:
        # Craft selection list
        sub_dirs = folder_get_subdirs( cwd ) if cwd else windows_list_logical_drives()
        selection_list = [ d.name if 0<len(d.name) else str(d) for d in sub_dirs ]
        extra_options = []
        cwd_has_parents = cwd and len(cwd.parents)>0
        windows_but_not_displaying_drives = windows_behavior and cwd is not None
        if cwd_has_parents or windows_but_not_displaying_drives:
            extra_options.append('..')
        if cwd:
            extra_options.append('.')
            if allow_mkdir:
                extra_options.append(NEW_FOLDER_TEXT)

        # ask user
        print(f"cwd : {cwd}")
        next_dir = choose_from_list(
            choices=extra_options + selection_list,
            default=extra_options.index('.') if '.' in extra_options else None
        )

        # Act upon user choice
        if next_dir=='..':
            cwd = None if windows_behavior and not cwd_has_parents else cwd.parent
        elif next_dir=='.':
            return cwd
        elif next_dir==NEW_FOLDER_TEXT:
            while True:
                # Ask user for new folder name
                new_dir_name = user_input(
                    prompt="New folder name",
                    accepted=lambda x: isinstance(x, str)
                )
                # create path, make sure it's safe and it doesn't exist yet
                new_dir = cwd / make_FS_safe(new_dir_name.replace('.',''))
                if new_dir.is_dir():
                    print(f"'{new_dir_name}' already exists !")
                    continue
                # Create it and move to it
                new_dir.mkdir()
                cwd = new_dir
                break
        else:
            # Move to selected directory
            cwd = sub_dirs[ selection_list.index( next_dir ) ]


def find_available_path( root: Path, base_name: str, file: bool = True ) -> Path:
    ''' Returns a path to a file/directory that DOESN'T already exist.
    The file/dir the user wishes to make a path for is referred as X.

    `root`: where X must be created. Can be a list of path parts

    `base_name`: the base name for X. Can contain '{suffix}' to manually set where
        the name may be completed with ' (index)' if name already exists. eg:
        'file_something.txt' -> 'file_something (3).txt', but
        'file{suffix}_something.txt' -> 'file (3)_something.txt'

    `file`: True if X is a file, False if it is a directory
    '''
    # Helper function: makes suffixes for already existing files/directories
    def suffixes() -> str:
        yield ''
        idx=0
        while True:
            idx+=1
            yield f" ({idx})"

    # automatic '{suffix}' placement
    if '{suffix}' not in base_name:
        # print(f"base_name='{base_name}'", end='')
        ext_idx = base_name.rfind('.')
        if ext_idx==-1:
            base_name += '{suffix}'
        else:
            base_name = base_name[:ext_idx] + '{suffix}' + base_name[ext_idx:]
        # print(f" -> '{base_name}', ext_idx={ext_idx}")

    # Iterate over candidate paths until an unused one is found
    safe_base_name = make_FS_safe( base_name )

    for _suffix in suffixes():
        _object = root / safe_base_name.format(suffix=_suffix)
        if file and not _object.is_file(): # file mode
            return _object
        if not file and not _object.is_dir(): # directory mode
            return _object


def folder_get_subdirs( root_dir: Path ) -> List[Path]:
    ''' Return a list of first level subdirectories '''
    assert root_dir.is_dir()
    return [
        item
        for item in root_dir.resolve().iterdir()
        if item.is_dir() and (not '$RECYCLE.BIN' in item.parts)
    ]


def make_FS_safe( s: str ) -> str:
    ''' File Systems don't accept all characters on file/directory names.

    Return s with illegal characters stripped

    Note: OS/FS agnostic, applies a simple filter on characters: ``\\, /, *, ?, :, ", <, >, |``
    '''
    return re.sub(
        pattern=MAKE_FS_SAFE_PATTERN,
        repl="",
        string=s
    )


def windows_list_logical_drives() -> List[Path]:
    ''' Uses windows-specific methods to retrieve a list of logical drives.

    Warning: Only works on Windows !
    '''

    # uses a windows shell command to list drives
    command = [ 'wmic', 'logicaldisk', 'get', 'name' ]
    stdout = execute( command )['stdout']

    def return_cleaned( l ):
        for item in l:
            if len(item) < 2:
                continue
            if item[0].isupper() and item[1] == ':':
                # Bugfix : the '<driveletter>:' format was resolving to CWD when driveletter==CWD's driveletter.
                # This seems to be an expected Windows behavior. Fix: switch to '<driveletter>:\\' format, whis is more appropriate.
                yield Path(item[:2]+'\\').resolve()

    drives = list( return_cleaned(stdout.splitlines()) )
    return drives


def file_collector( root: Path, pattern: Union[str,Iterable[str]] = '**/*.*' ) -> List[Path]:
    ''' Easy to use tool to collect files matching a pattern (recursive or not), using pathlib.glob.
    Collect files matching given pattern(s) '''
    assert root.is_dir()
    root.resolve()
    #log.debug( "root=%s", root )

    def collect( _pattern: str ) -> List[Path]:
        # 11/11/2020 BUGFIX : was collecting files in trash like a cyber racoon
        _files = [
            item
            for item in root.glob( _pattern )
            if item.is_file() and (not '$RECYCLE.BIN' in item.parts)
        ]
        # log.debug( "\t'%s': Found %s files in %s", _pattern, len(_files), root )
        return _files

    files = []
    if isinstance( pattern, str ):
        files = collect( pattern )
    elif isinstance( pattern, collections.abc.Iterable ):
        patterns = pattern
        assert 0 < len(patterns)
        for p in patterns:
            files.extend( collect(p) )
    else:
        raise ValueError(f"FileCollector: 'pattern' ({pattern}) must be an Iterable or a string, but is a {type(pattern)}")

    return files


def dump_json( obj, file ):
    ''' Dump object (preferably dict or list containing basic types) to JSON file
    '''
    file.write_text(
        json.dumps(obj, indent=2, default=str),
        encoding='utf8',
        errors='ignore'
    )


def patch_string( s: str, patch: dict ) -> str:
    ''' Applies a patch on string s
    Returns s if not a str or no patch could be applied.

    `patch` must be a dict with entries:
        <to_replace:str>:<replacement:Union[str,Path]>
    '''

    if not isinstance(s, str):
        return s
    _s = s
    for to_replace, replacement in patch.items():
        _s = _s.replace(to_replace, replacement if isinstance(replacement, str) else f'"{replacement}"')
    return _s
