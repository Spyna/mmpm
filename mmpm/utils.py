#!/usr/bin/env python3
import sys
import os
import subprocess
import time

from re import sub
from logging import Logger
from multiprocessing import cpu_count
from typing import List, Optional, Tuple, Dict
from ctypes import cdll, c_char_p, c_int, POINTER
from collections import defaultdict

import mmpm.color
import mmpm.consts
import mmpm.models

MagicMirrorPackage = mmpm.models.MagicMirrorPackage
MMPMLogger = mmpm.models.MMPMLogger


log: Logger = MMPMLogger().logger


def plain_print(msg: str) -> None:
    '''
    Prints message 'msg' without a new line

    Parameters:
        msg (str): The message to be printed to stdout

    Returns:
        None
    '''
    sys.stdout.write(msg)
    sys.stdout.flush()


def error_msg(msg: str) -> None:
    '''
    Logs error message, displays error message to user, and continues program execution

    Parameters:
        msg (str): The error message to be printed to stdout

    Returns:
        None
    '''
    log.error(msg)
    print(colored_text(mmpm.color.B_RED, "ERROR:"), msg)


def keyboard_interrupt_log() -> None:
    '''
    Logs info message stating user killed a process with a keyboard interrupt,
    and exits program with error code of 127

    Parameters:
        None

    Returns:
        None
    '''
    print()
    log.info('User killed process with keyboard interrupt')
    sys.exit(127)


def warning_msg(msg: str) -> None:
    '''
    Logs warning message, displays warning message to user, and continues program execution

    Parameters:
        msg (str): The warning message to be printed to stdout

    Returns:
        None
    '''
    log.warning(msg)
    print(colored_text(mmpm.color.B_YELLOW, "WARNING:"), msg)


def fatal_msg(msg: str) -> None:
    '''
    Logs fatal message, displays fatal message to user, and halts program execution

    Parameters:
        msg (str): The fatal error message to be printed to stdout

    Returns:
        None
    '''
    log.critical(msg)
    print(colored_text(mmpm.color.B_RED, "FATAL:"), msg)
    sys.exit(127)


def assert_snapshot_directory() -> bool:
    if not os.path.exists(mmpm.consts.MMPM_CONFIG_DIR):
        try:
            os.mkdir(mmpm.consts.MMPM_CONFIG_DIR)
        except OSError:
            error_msg('Failed to create directory for snapshot')
            return False
    return True


def calc_snapshot_timestamps() -> Tuple[float, float]:
    '''
    Calculates the expiration timestamp of the MagicMirror snapshot file

    Parameters:
        None

    Returns:
        Tuple[curr_snap (float), next_snap (float)]: The current timestamp and the exipration timestamp of the MagicMirror snapshot
    '''
    curr_snap = next_snap = None

    if os.path.exists(mmpm.consts.MAGICMIRROR_3RD_PARTY_PACKAGES_SNAPSHOT_FILE):
        curr_snap = os.path.getmtime(mmpm.consts.MAGICMIRROR_3RD_PARTY_PACKAGES_SNAPSHOT_FILE)
        next_snap = curr_snap + 6 * 60 * 60

    return curr_snap, next_snap


def should_refresh_packages(current_snapshot: float, next_snapshot: float) -> bool:
    '''
    Determines if the MagicMirror snapshot is expired

    Parameters:
        current_snapshot (float): The 'last modified' timestamp from os.path.getmtime
        next_snapshot (float): When the file should 'expire' based on a one day interval

    Returns:
        should_update (bool): If the file is expired and the data needs to be refreshed
    '''
    if not current_snapshot and not next_snapshot:
        return True
    return not os.path.exists(mmpm.consts.MAGICMIRROR_3RD_PARTY_PACKAGES_SNAPSHOT_FILE) or next_snapshot - time.time() <= 0.0


def run_cmd(command: List[str], progress=True, background=False) -> Tuple[int, str, str]:
    '''
    Executes shell command and captures errors

    Parameters:
        command (List[str]): The command string to be executed

    Returns:
        Tuple[returncode (int), stdout (str), stderr (str)]
    '''

    log.info(f'Executing process `{" ".join(command)}` in foreground')

    if background:
        log.info(f'Executing process `{" ".join(command)}` in background')
        process = subprocess.Popen(command, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        return process.returncode, str(), str()

    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    symbols = [u'\u25DC', u'\u25DD', u'\u25DE', u'\u25DF']

    if progress:
        def __spinner__():
            while True:
                for symbol in symbols:
                    yield symbol

        spinner = __spinner__()

        sys.stdout.write(' ')

        while process.poll() is None:
            sys.stdout.write(next(spinner))
            sys.stdout.flush()
            time.sleep(0.1)
            sys.stdout.write('\b')

    stdout, stderr = process.communicate()

    return process.returncode, stdout.decode('utf-8'), stderr.decode('utf-8')


def sanitize_name(orig_name: str) -> str:
    '''
    Sanitizes a file- or foldername in that it removes bad characters.

    Parameters:
        orig_name (str): A file- or foldername with potential bad characters

    Returns:
        a cleaned version of the file- or foldername
    '''
    return sub('[//]', '', orig_name)


def open_default_editor(path_to_file: str) -> Optional[None]:
    '''
    Method to determine user's text editor. First, checks the EDITOR env
    variable, if not found, attempts to see if 'nano' is installed, and if not,
    lets the system determine the editor using the 'edit' command

    Parameters:
        path_to_file (str): file path to open with editor

    Returns:
        None
    '''
    log.info(f'Attempting to open {path_to_file} in users default editor')

    if not os.path.exists(path_to_file):
        fatal_msg(f'{path_to_file} not found. Please ensure the env variable {mmpm.consts.MMPM_MAGICMIRROR_ROOT} is set properly.')

    editor = os.getenv('EDITOR') if os.getenv('EDITOR') else 'nano'
    error_code, _, _ = run_cmd(['which', editor], progress=False)

    # fall back to the 'edit' command if you don't even have nano for some reason
    os.system(f'{editor} {path_to_file}') if not error_code else os.system(f'edit {path_to_file}')


def clone(title: str, repo: str, target_dir: str = '') -> Tuple[int, str, str]:
    '''
    Wrapper method to clone a repository with logging information included

    Parameters:
        title (str): The title of the repository
        repo (str): The url of the repository
        target_dir (str): The target_dir of the repository (Optional)

    Returns:
        Tuple[returncode (int), stdout (str), stderr (str)]: Return code, stdout, and stderr of the process
    '''
    # by using "repo.split()", it allows the user to bake in additional commands when making custom sources
    # ie. git clone [repo] -b [branch] [target]
    log.info(f'Cloning {repo} into {target_dir if target_dir else os.path.join(os.getcwd(), title)}')
    plain_print(mmpm.consts.GREEN_PLUS_SIGN + f" Cloning {colored_text(mmpm.color.N_GREEN, f'{title}')} repository" + mmpm.color.RESET)

    command = ['git', 'clone'] + repo.split()

    if target_dir:
        command += [target_dir]

    return run_cmd(command)


def package_requirements_file_exists(file_name: str) -> bool:
    '''
    Case-insensitive search for existing package specification file in current directory

    Parameters:
        file_name (str): The name of the file to search for

    Returns:
        bool: True if the file exists, False if not
    '''
    for name in [file_name, file_name.lower(), file_name.upper()]:
        if os.path.isfile(os.path.join(os.getcwd(), name)):
            return True
    return False


def cmake() -> Tuple[int, str, str]:
    ''' Used to run make from a directory known to have a CMakeLists.txt file

    Parameters:
        None

    Returns:
        Tuple[error_code (int), stdout (str), error_message (str)]

    '''
    log.info(f"Running 'cmake ..' in {os.getcwd()}")
    plain_print(mmpm.consts.GREEN_PLUS_SIGN + " Found CMakeLists.txt. Attempting build with 'cmake'")

    run_cmd(['mkdir', '-p', 'build'], progress=False)
    os.chdir('build')
    run_cmd(['rm', '-rf', '*'], progress=False)
    return run_cmd(['cmake', '..'])


def make() -> Tuple[int, str, str]:
    '''
    Used to run make from a directory known to have a Makefile

    Parameters:
        None

    Returns:
        Tuple[error_code (int), stdout (str), error_message (str)]
    '''
    log.info(f"Running 'make -j {cpu_count()}' in {os.getcwd()}")
    plain_print(mmpm.consts.GREEN_PLUS_SIGN + f" Found Makefile. Attempting to run 'make -j {cpu_count()}'")
    return run_cmd(['make', '-j', f'{cpu_count()}'])


def npm_install() -> Tuple[int, str, str]:
    '''
    Used to run npm install from a directory known to have a package.json file

    Parameters:
        None

    Returns:
        Tuple[error_code (int), stdout (str), error_message (str)]
    '''
    log.info(f"Running 'npm install' in {os.getcwd()}")
    plain_print(mmpm.consts.GREEN_PLUS_SIGN + " Found package.json. Running 'npm install'")
    return run_cmd(['npm', 'install'])


def bundle_install() -> Tuple[int, str, str]:
    '''
    Used to run npm install from a directory known to have a package.json file

    Parameters:
        None

    Returns:
        Tuple[error_code (int), stdout (str), error_message (str)]
    '''
    log.info(f"Running 'bundle install' in {os.getcwd()}")
    plain_print(mmpm.consts.GREEN_PLUS_SIGN + "Found Gemfile. Running 'bundle install'")
    return run_cmd(['bundle', 'install'])


def basic_fail_log(error_code: int, error_message: str) -> None:
    '''
    Wrapper method for simple failure logging

    Parameters:
        error_code (int): The return code
        error_message (str): The error message itself

    Returns:
        None
    '''
    log.info(f'Failed with return code {error_code}, and error message {error_message}')


def install_dependencies() -> str:
    '''
    Utility method that detects package.json, Gemfiles, Makefiles, and
    CMakeLists.txt files, and handles the build process for each of the
    previously mentioned files. If the install is successful, an empty string
    is returned. The installation process relies on the location of the current
    directory the os library detects.

    Parameters:
        None

    Returns:
        stderr (str): Success if the string is empty, fail if not
    '''

    if package_requirements_file_exists(mmpm.consts.PACKAGE_JSON):
        error_code, _, stderr = npm_install()

        if error_code:
            basic_fail_log(error_code, stderr)
            print()
            return str(stderr)
        else:
            print(mmpm.consts.GREEN_CHECK_MARK)

    if package_requirements_file_exists(mmpm.consts.GEMFILE):
        error_code, _, stderr = bundle_install()

        if error_code:
            basic_fail_log(error_code, stderr)
            print()
            return str(stderr)
        else:
            print(mmpm.consts.GREEN_CHECK_MARK)

    if package_requirements_file_exists(mmpm.consts.MAKEFILE):
        error_code, _, stderr = make()

        if error_code:
            basic_fail_log(error_code, stderr)
            print()
            return str(stderr)
        else:
            print(mmpm.consts.GREEN_CHECK_MARK)


    if package_requirements_file_exists(mmpm.consts.CMAKELISTS):
        error_code, _, stderr = cmake()

        if error_code:
            basic_fail_log(error_code, stderr)
            print()
            return str(stderr)
        else:
            print(mmpm.consts.GREEN_CHECK_MARK)

        if package_requirements_file_exists(mmpm.consts.MAKEFILE):
            error_code, _, stderr = make()

            if error_code:
                basic_fail_log(error_code, stderr)
                print()
                return str(stderr)
            else:
                print(mmpm.consts.GREEN_CHECK_MARK)

    print(mmpm.consts.GREEN_PLUS_SIGN + f' Installation ' + mmpm.consts.GREEN_CHECK_MARK)
    log.info(f'Exiting installation handler from {os.getcwd()}')
    return ''


def get_pids(process_name: str) -> List[str]:
    '''
    Kills all processes of given name

    Parameters:
        process (str): the name of the process

    Returns:
        processes (List[str]): list of the processes IDs found
    '''

    log.info(f'Getting process IDs for {process_name} proceses')

    pids = subprocess.Popen(['pgrep', process_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, _ = pids.communicate()
    processes = stdout.decode('utf-8')

    log.info(f'Found processes: {processes}')

    return [proc_id for proc_id in processes.split('\n') if proc_id]


def kill_pids_of_process(process: str):
    '''
    Kills all processes of given name

    Parameters:
        process (str): the name of the process

    Returns:
        processes (str): the processes IDs found
    '''
    log.info(f'Killing all processes of type {process}')
    os.system(f'for process in $(pgrep {process}); do kill -9 $process; done')


def kill_magicmirror_processes() -> None:
    '''
    Kills all processes commonly related to MagicMirror

    Parameters:
        None

    Returns:
        None
    '''

    processes = ['node', 'npm', 'electron']

    log.info('Killing processes associated with MagicMirror: {processes}')

    for process in processes:
        kill_pids_of_process(process)
        log.info(f'Killed pids of process {process}')


def display_table(table, rows: int, columns: int) -> None:
    '''
    Calls the shared mmpm library to print the contents of a provided matrix

    Parameters:
        data: List[bytes]

    Returns:
        None
    '''

    libmmpm = cdll.LoadLibrary(mmpm.consts.MMPM_LIBMMPM_SHARED_OBJECT_FILE)

    __display_table__ = libmmpm.display_table
    __display_table__.argtypes = [POINTER(POINTER(c_char_p)), c_int, c_int]
    __display_table__.restype = None
    __display_table__(table, rows, columns)


def allocate_table_memory(rows: int, columns: int):
    '''
    Calls the shared mmpm library to allocate memory for a matrix `rows` times
    `columns` times `sizeof(char*)`, and returns a pointer to the memory

    Parameters:
        data: List[bytes]

    Returns:
        table (POINTER(POINTER(c_char_p))): the allocated memory
    '''
    if not rows or not columns:
        fatal_msg('Positive integers must be provided as arguments')

    libmmpm = cdll.LoadLibrary(mmpm.consts.MMPM_LIBMMPM_SHARED_OBJECT_FILE)

    _allocate_table_memory = libmmpm.allocate_table_memory
    _allocate_table_memory.argtypes = [c_int, c_int]
    _allocate_table_memory.restype = POINTER(POINTER(c_char_p))

    table = _allocate_table_memory(rows, columns)
    return table


def to_bytes(string: str) -> bytes:
    '''
    Wrapper method to convert a string to UTF-8 encoded bytes

    Parameters:
        string (str): text that will be UTF-8 encoded

    Returns:
        message (str): the UTF-8 encoded string

    '''
    return bytes(string, 'utf-8')


def colored_text(text_color: str, message: str) -> str:
    '''
    Returns the `color` concatenated with the `message` string

    Parameters:
        text_color (str): a colorama color
        message (str): text that will be displayed in the `color`

    Returns:
        message (str): The original text concatenated with the colorama color
    '''
    return (text_color + message + mmpm.color.RESET)


def prompt_user(user_prompt: str, valid_ack: List[str] = ['yes', 'y'], valid_nack: List[str] = ['no', 'n'], assume_yes: bool = False) -> bool:
    '''
    Prompts user with the `user_prompt` until a response matches a value in the
    `valid_ack` or `valid_nack` lists, or a KeyboardInterrupt is caught. If
    `assume_yes` is true, the `user_prompt` is printed followed by a 'yes', and
    function returns True

    Parameters:
        user_prompt (str): the text that will be presented to the user
        valid_ack (List[str]): valid 'yes' responses
        valid_nack (List[str]): valid 'no' responses
        assume_yes (bool): if True, the `user_prompt` is printed followed by 'yes'

    Returns:
        response (bool): True if the response is in the `valid_ack` list, False if in `valid_nack` or KeyboardInterrupt
    '''
    if assume_yes:
        print(f"{user_prompt} [{'/'.join(valid_ack)}] or [{'/'.join(valid_nack)}]: yes")
        return True

    response = None

    try:
        while response not in (valid_ack, valid_nack):
            response = input(f"{user_prompt} [{'/'.join(valid_ack)}] or [{'/'.join(valid_nack)}]: ")

            if response in valid_ack:
                return True
            elif response in valid_nack:
                return False
            else:
                warning_msg(f"Respond with [{'/'.join(valid_ack)}] or [{'/'.join(valid_nack)}]")

    except KeyboardInterrupt:
        return False

    return False


def fatal_invalid_additional_arguments(subcommand: str) -> None:
    '''
    Helper method to return a standardized error message when the user provides too many arguments

    Parameters:
        subcommand (str): the name of the mmpm subcommand

    Returns:
        None
    '''
    fatal_msg(f'`mmpm {subcommand}` does not accept additional arguments. See `mmpm {subcommand} --help`')


def fatal_invalid_option(subcommand: str) -> None:
    '''
    Helper method to return a standardized error message when the user provides an invalid option

    Parameters:
        subcommand (str): the name of the mmpm subcommand

    Returns:
        None
    '''
    fatal_msg(f'Invalid option supplied to `mmpm {subcommand}`. See `mmpm {subcommand} --help`')



def fatal_too_many_options(args) -> None:
    '''
    Helper method to return a standardized error message when the user provides too many options

    Parameters:
        subcommand (str): the name of the mmpm subcommand

    Returns:
        None
    '''

    if 'table_formatted' in args.__dict__:
        message: str = f'`mmpm {args.subcmd}` only accepts one optional argument in addition to `--table`. See `mmpm {args.subcmd} --help`'
    else:
        message = f'`mmpm {args.subcmd}` only accepts one optional argument. See `mmpm {args.subcmd} --help`'
    fatal_msg(message)


def fatal_no_arguments_provided(subcommand: str) -> None:
    '''
    Helper method to return a standardized error message when the user provides no arguments

    Parameters:
        subcommand (str): the name of the mmpm subcommand

    Returns:
        None
    '''
    fatal_msg(f'no arguments provided. See `mmpm {subcommand} --help` for usage')


def assert_valid_input(prompt: str, forbidden_responses: List[str] = [], reason: str = '') -> str:
    '''
    Continues to prompt user with given input until the response provided is of
    non-zero length and not found in the list forbidden responses

    Parameters:
        prompt (str): the prompt given to the user
        forbidden_responses (List[str]): a list of responses the user may not supply
        reason (str): a reason why the user may not supply one of the 'forbidden_responses'

    Returns:
        user_response (str): valid, user provided input
    '''
    while True:
        user_response = input(prompt)
        if not user_response:
            warning_msg('A non-empty response must be given')
            continue
        elif user_response in forbidden_responses:
            warning_msg(f'Invalid response, {user_response} {reason}')
            continue
        return user_response


def get_existing_package_directories() -> List[str]:
    '''
    Retrieves list of directories found in MagicMirror modules directory

    Parameters:
        None

    Returns:
        directories (List[str]): a list of directories found in the MagicMirror modules directory
    '''
    if not os.path.exists(mmpm.consts.MAGICMIRROR_MODULES_DIR):
        return []

    dirs: List[str] = os.listdir(mmpm.consts.MAGICMIRROR_MODULES_DIR)
    return [d for d in dirs if os.path.isdir(os.path.join(mmpm.consts.MAGICMIRROR_MODULES_DIR, d))]


def list_of_dict_to_list_of_magicmirror_packages(list_of_dict: List[dict]) -> List[MagicMirrorPackage]:
    '''
    Converts a list of dictionary contents to a list of MagicMirrorPackage objects

    Parameters:
        list_of_dict (List[dict]): a list of dictionaries representing MagicMirrorPackage data

    Returns:
        packages (List[MagicMirrorPackage]): a list of MagicMirrorPackage objects
    '''

    return [MagicMirrorPackage(**pkg) for pkg in list_of_dict]


def get_difference_of_packages(original: Dict[str, List[MagicMirrorPackage]], exclude: Dict[str, List[MagicMirrorPackage]]) -> Dict[str, List[MagicMirrorPackage]]:
    '''
    Calculates the difference between two dictionaries of MagicMirrorPackages.
    The result returned is the 'original' minus 'exclude'

    Parameters:
        original (Dict[str, List[MagicMirrorPackage]]): the full dictionary of packages
        exclude (Dict[str, List[MagicMirrorPackage]]): the dictionary of packges to be removed

    Returns:
        difference (Dict[str, List[MagicMirrorPackage]]]): the reduced set of packages
    '''

    difference: Dict[str, List[MagicMirrorPackage]] = defaultdict(list)

    for category in original.keys():
        if not exclude[category]:
            difference[category] = original[category]
            continue

        for orig_pkg in original[category]:
            if orig_pkg not in exclude[category]:
                difference[category].append(orig_pkg)

    return difference


def assert_one_option_selected(args) -> bool:
    '''
    Determines if more than one option has been selected by a user for use with a subcommand

    Parameters:
        args (argparse.Namespace): an argparse Namespace object containing chosen arguments

    Returns:
        yes (bool): True if one option is selected, False if more than one is selected
    '''
    args = args.__dict__
    return not len([args[option] for option in args if args[option] == True and option != 'table_formatted']) > 1


